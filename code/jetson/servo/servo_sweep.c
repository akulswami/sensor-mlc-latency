/*
 * servo_sweep.c
 *
 * Oscillates an SG90 servo via PCA9685 on Jetson I2C bus 1, address 0x60.
 * Two modes:
 *   --mode continuous : alternates between min/max endpoints every period-ms
 *   --mode burst      : alternates motion-phase (oscillating) with still-phase
 *                       (held at center) for ground-truth labeling
 *
 * Logs every PWM register write to a file with host-side microsecond
 * timestamps. Timestamps are the time the host issued the i2c_write
 * call; the actual PWM edge appears on the wire ~100 us later. For
 * precise PWM edge times, use the corresponding Saleae capture and
 * cross-correlate via PWM edge alignment.
 *
 * Build:
 *   gcc -Wall -O2 -o servo_sweep servo_sweep.c
 *
 * Run (must be sudo for /dev/i2c-1 access):
 *   sudo ./servo_sweep --mode continuous --duration 30 --log /tmp/sweep.log
 *   sudo ./servo_sweep --mode burst --motion-ms 5000 --still-ms 8000 \
 *                      --duration 120 --log /tmp/sweep.log
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>

#define I2C_DEV       "/dev/i2c-1"
#define PCA9685_ADDR  0x60
#define REG_MODE1      0x00
#define REG_PRE_SCALE  0xFE
#define REG_LED0_ON_L  0x06
#define REG_LED0_ON_H  0x07
#define REG_LED0_OFF_L 0x08
#define REG_LED0_OFF_H 0x09

/* PRE_SCALE for 50 Hz PWM (standard servo rate):
 *   PRE_SCALE = round(25 MHz / (4096 * 50 Hz)) - 1 = 121 = 0x79
 * PCA9685 chip POR default is 0x1E (~200 Hz, too fast for servos),
 * so we MUST configure PRE_SCALE explicitly on every invocation. */
#define PRESCALE_50HZ  0x79

#define DEFAULT_MIN_TICKS    102   /* 0x0066 */
#define DEFAULT_MAX_TICKS    511   /* 0x01FF */
#define DEFAULT_CENTER_TICKS 307   /* 0x0133 */

static volatile int g_stop = 0;

static void sigint_handler(int sig) {
    (void)sig;
    g_stop = 1;
}

static uint64_t now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}

/* Write 4 PWM registers in a single transaction using auto-increment. */
static int write_pwm(int fd, uint16_t on_ticks, uint16_t off_ticks) {
    uint8_t buf[5];
    buf[0] = REG_LED0_ON_L;
    buf[1] = (uint8_t)(on_ticks & 0xFF);
    buf[2] = (uint8_t)((on_ticks >> 8) & 0xFF);
    buf[3] = (uint8_t)(off_ticks & 0xFF);
    buf[4] = (uint8_t)((off_ticks >> 8) & 0xFF);
    if (write(fd, buf, 5) != 5) {
        perror("write_pwm");
        return -1;
    }
    return 0;
}

static void log_event(FILE *log, const char *event, uint16_t ticks) {
    fprintf(log, "%llu,%s,%u\n",
            (unsigned long long)now_us(), event, ticks);
    fflush(log);
}

static void sleep_ms_interruptible(unsigned int ms) {
    /* Sleep but wake on SIGINT */
    struct timespec req = { .tv_sec = ms / 1000,
                            .tv_nsec = (long)(ms % 1000) * 1000000L };
    while (nanosleep(&req, &req) == -1 && !g_stop) {
        /* interrupted; nanosleep updated req with remaining time */
    }
}

/* Initialize PCA9685 for 50 Hz servo PWM.
 *
 * On chip power-up, PCA9685 is in SLEEP mode (MODE1 bit 4 = 1) and
 * PRE_SCALE is at its POR default (0x1E, giving ~200 Hz PWM, far too
 * fast for servos). This function performs the documented init
 * sequence per the PCA9685 datasheet:
 *
 *   1. Put chip in SLEEP mode (required to write PRE_SCALE)
 *   2. Write PRE_SCALE for 50 Hz PWM
 *   3. Wake chip (clear SLEEP), enable register auto-increment (AI)
 *   4. Wait for oscillator to stabilize, then set RESTART bit
 *
 * Idempotent: running this on an already-configured chip just
 * re-applies the same state (cost is ~5 I2C writes, <10 ms).
 *
 * Without this init, all PWM register writes silently produce no
 * output because the chip is asleep. Sessions S1-S6 depended on
 * undocumented prior PCA9685 state; S7 (2026-05-24) failed because
 * power had been cycled and the chip reverted to POR defaults.
 */
static int pca9685_init(int fd) {
    uint8_t buf[2];

    /* Step 1: sleep the chip */
    buf[0] = REG_MODE1;
    buf[1] = 0x10;  /* SLEEP=1, AI=0, ALLCALL=0, RESTART=0 */
    if (write(fd, buf, 2) != 2) {
        perror("pca9685_init: sleep");
        return -1;
    }

    /* Step 2: write PRE_SCALE for 50 Hz */
    buf[0] = REG_PRE_SCALE;
    buf[1] = PRESCALE_50HZ;
    if (write(fd, buf, 2) != 2) {
        perror("pca9685_init: prescale");
        return -1;
    }

    /* Step 3: wake the chip, enable auto-increment */
    buf[0] = REG_MODE1;
    buf[1] = 0x20;  /* SLEEP=0, AI=1, ALLCALL=0, RESTART=0 */
    if (write(fd, buf, 2) != 2) {
        perror("pca9685_init: wake");
        return -1;
    }

    /* Step 4: wait 500 us for internal oscillator to stabilize,
     * then set RESTART bit to apply settings cleanly. */
    struct timespec stab = { .tv_sec = 0, .tv_nsec = 500000L };
    nanosleep(&stab, NULL);

    buf[0] = REG_MODE1;
    buf[1] = 0xA0;  /* RESTART=1, SLEEP=0, AI=1 */
    if (write(fd, buf, 2) != 2) {
        perror("pca9685_init: restart");
        return -1;
    }

    fprintf(stderr, "pca9685_init: configured for 50 Hz (PRE_SCALE=0x%02x)\n",
            PRESCALE_50HZ);
    return 0;
}

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s --mode {continuous|burst} [options]\n"
        "  Common:\n"
        "    --duration SEC      total run time in seconds (default: 60)\n"
        "    --min-ticks N       PWM min endpoint (default: 102)\n"
        "    --max-ticks N       PWM max endpoint (default: 511)\n"
        "    --center-ticks N    PWM center / still position (default: 307)\n"
        "    --log PATH          log file path (default: stdout)\n"
        "  Continuous mode:\n"
        "    --period-ms MS      time per half-cycle (default: 1000)\n"
        "  Burst mode:\n"
        "    --motion-ms MS      motion phase duration (default: 5000)\n"
        "    --still-ms MS       still phase duration (default: 8000)\n"
        "    --burst-period-ms MS oscillation half-period during motion phase\n"
        "                         (default: 1000)\n",
        prog);
}

int main(int argc, char **argv) {
    /* Defaults */
    const char *mode = NULL;
    int duration_sec = 60;
    uint16_t min_ticks = DEFAULT_MIN_TICKS;
    uint16_t max_ticks = DEFAULT_MAX_TICKS;
    uint16_t center_ticks = DEFAULT_CENTER_TICKS;
    const char *log_path = NULL;
    int period_ms = 1000;
    int motion_ms = 5000;
    int still_ms = 8000;
    int burst_period_ms = 1000;

    /* Parse args */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            mode = argv[++i];
        } else if (strcmp(argv[i], "--duration") == 0 && i + 1 < argc) {
            duration_sec = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--min-ticks") == 0 && i + 1 < argc) {
            min_ticks = (uint16_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--max-ticks") == 0 && i + 1 < argc) {
            max_ticks = (uint16_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--center-ticks") == 0 && i + 1 < argc) {
            center_ticks = (uint16_t)atoi(argv[++i]);
        } else if (strcmp(argv[i], "--log") == 0 && i + 1 < argc) {
            log_path = argv[++i];
        } else if (strcmp(argv[i], "--period-ms") == 0 && i + 1 < argc) {
            period_ms = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--motion-ms") == 0 && i + 1 < argc) {
            motion_ms = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--still-ms") == 0 && i + 1 < argc) {
            still_ms = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--burst-period-ms") == 0 && i + 1 < argc) {
            burst_period_ms = atoi(argv[++i]);
        } else {
            usage(argv[0]);
            return 1;
        }
    }

    if (!mode || (strcmp(mode, "continuous") != 0 && strcmp(mode, "burst") != 0)) {
        usage(argv[0]);
        return 1;
    }

    /* Open log */
    FILE *log = stdout;
    if (log_path) {
        log = fopen(log_path, "w");
        if (!log) { perror("fopen log"); return 1; }
    }

    /* Header. Document what each timestamp means. */
    fprintf(log, "# servo_sweep log\n");
    fprintf(log, "# mode=%s duration=%d min_ticks=%u max_ticks=%u center_ticks=%u\n",
            mode, duration_sec, min_ticks, max_ticks, center_ticks);
    if (strcmp(mode, "continuous") == 0) {
        fprintf(log, "# period_ms=%d\n", period_ms);
    } else {
        fprintf(log, "# motion_ms=%d still_ms=%d burst_period_ms=%d\n",
                motion_ms, still_ms, burst_period_ms);
    }
    fprintf(log, "# timestamp = CLOCK_REALTIME microseconds at host i2c_write call\n");
    fprintf(log, "# actual PWM wire edge appears ~100us after timestamp\n");
    fprintf(log, "# columns: timestamp_us,event,ticks\n");

    /* Open I2C device */
    int fd = open(I2C_DEV, O_RDWR);
    if (fd < 0) { perror("open " I2C_DEV); return 1; }
    if (ioctl(fd, I2C_SLAVE, PCA9685_ADDR) < 0) {
        perror("ioctl I2C_SLAVE");
        close(fd);
        return 1;
    }

    /* Initialize PCA9685 to 50 Hz PWM. POR state is SLEEP=1 with
     * PRE_SCALE=0x1E (~200 Hz), neither of which can drive a servo.
     * This init is the missing dependency that caused S7 (2026-05-24)
     * to capture a "motion" arm with no physical motion. */
    if (pca9685_init(fd) < 0) {
        fprintf(stderr, "pca9685_init failed\n");
        close(fd);
        if (log != stdout) fclose(log);
        return 1;
    }

    signal(SIGINT, sigint_handler);

    log_event(log, "START", center_ticks);
    write_pwm(fd, 0, center_ticks);
    sleep_ms_interruptible(200);  /* let servo settle at center before run begins */

    uint64_t t_start = now_us();
    uint64_t t_end = t_start + (uint64_t)duration_sec * 1000000ULL;

    if (strcmp(mode, "continuous") == 0) {
        /* Alternate between max and min every period_ms */
        int direction = 0;  /* 0 = next is max, 1 = next is min */
        while (!g_stop && now_us() < t_end) {
            uint16_t target = direction ? min_ticks : max_ticks;
            const char *event = direction ? "TO_MIN" : "TO_MAX";
            log_event(log, event, target);
            write_pwm(fd, 0, target);
            sleep_ms_interruptible(period_ms);
            direction = !direction;
        }
    } else {
        /* Burst mode */
        int in_motion = 1;  /* start with motion phase */
        while (!g_stop && now_us() < t_end) {
            if (in_motion) {
                /* Motion phase: oscillate for motion_ms */
                log_event(log, "MOTION_PHASE_START", 0);
                uint64_t phase_end = now_us() + (uint64_t)motion_ms * 1000ULL;
                int direction = 0;
                while (!g_stop && now_us() < phase_end && now_us() < t_end) {
                    uint16_t target = direction ? min_ticks : max_ticks;
                    const char *event = direction ? "TO_MIN" : "TO_MAX";
                    log_event(log, event, target);
                    write_pwm(fd, 0, target);
                    sleep_ms_interruptible(burst_period_ms);
                    direction = !direction;
                }
            } else {
                /* Still phase: hold center for still_ms */
                log_event(log, "STILL_PHASE_START", center_ticks);
                write_pwm(fd, 0, center_ticks);
                sleep_ms_interruptible(still_ms);
            }
            in_motion = !in_motion;
        }
    }

    /* Clean exit: return to center */
    log_event(log, "END", center_ticks);
    write_pwm(fd, 0, center_ticks);
    close(fd);
    if (log != stdout) fclose(log);
    return 0;
}

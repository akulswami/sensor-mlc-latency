/*
 * host_pipeline.c
 *
 * B5: On-host classification pipeline.
 *
 * Configures LSM6DSOX as a streaming accelerometer with data-ready
 * interrupts on I1 (same physical wiring as the on-sensor pipeline).
 * Blocks on I1, reads X/Y/Z, runs a sliding-window peak-to-peak
 * threshold tap classifier in software. On positive classification,
 * toggles the decision GPIO (same Pin 11 as B4).
 *
 * Saleae setup (identical to B4):
 *   D0 = Pin 15 (sensor INT)    -- sensor data-ready edge
 *   D1 = Pin 11 (decision GPIO) -- host's classification edge
 *   Wire-level latency = t(D1 rising) - t(D0 rising) for the sample
 *   that triggered classification.
 *
 * Build: gcc -O2 -Wall -o host_pipeline host_pipeline.c -lgpiod -lm
 * Run:   sudo ./host_pipeline
 */

#define _POSIX_C_SOURCE 200809L
#include <gpiod.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <time.h>
#include <errno.h>
#include <signal.h>
#include <math.h>

/* --- Hardware bindings --- */
#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A

#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define INT_LINE        85    /* PN.01 = pin 15 (sensor I1) */
#define DECISION_LINE   112   /* PR.04 = pin 11 (decision GPIO) */

#define CONSUMER_NAME   "sensor-mlc-latency-host"

/* --- LSM6DSOX registers --- */
#define REG_CTRL1_XL    0x10
#define REG_CTRL3_C     0x12
#define REG_INT1_CTRL   0x0D
#define REG_OUTX_L_A    0x28

/* Sensitivity: +/-2g range -> 0.061 mg/LSB */
#define SENS_G_PER_LSB  (0.061e-3f)

/* --- Classifier parameters --- */
#define ODR_HZ              416
#define WINDOW_MS           50
#define WINDOW_N            21      /* (50ms * 416Hz / 1000) ~= 21 */
#define TAP_THRESHOLD_G     1.0f    /* peak-to-peak g, any axis */
#define COOLDOWN_MS         150     /* ignore re-fires within this window */

/* --- I2C helpers --- */
static int i2c_open_and_select(const char *dev, uint8_t addr) {
    int fd = open(dev, O_RDWR);
    if (fd < 0) return -1;
    if (ioctl(fd, I2C_SLAVE, addr) < 0) { close(fd); return -1; }
    return fd;
}
static int i2c_write_reg(int fd, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = { reg, val };
    return (write(fd, buf, 2) == 2) ? 0 : -1;
}
static int i2c_read_block(int fd, uint8_t reg, uint8_t *buf, size_t n) {
    /* Use I2C_RDWR ioctl to issue write+read as a single combined
     * transaction with repeated-start. Plain write()+read() on i2c-dev
     * inserts a STOP between the two, which resets the LSM6DSOX register
     * pointer and produces garbage reads. */
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = (uint16_t)n, .buf = buf },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}

/* --- Sensor configuration --- */
static int i2c_write_reg_retry(int fd, uint8_t reg, uint8_t val, int retries) {
    for (int attempt = 0; attempt <= retries; ++attempt) {
        if (i2c_write_reg(fd, reg, val) == 0) return 0;
        if (attempt < retries) {
            fprintf(stderr, "i2c write reg 0x%02X failed, retrying: %s\n",
                    reg, strerror(errno));
            struct timespec ts = { .tv_sec = 0, .tv_nsec = 100 * 1000 * 1000 };
            nanosleep(&ts, NULL);
        }
    }
    return -1;
}

static int configure_streaming(int i2c_fd) {
    uint8_t scratch;
    uint8_t reg;

    /* 1. Drain any latched interrupts by reading the data registers.
     * In latched DRDY mode the chip clears INT1 only when the high byte of
     * an enabled axis (0x29, 0x2B, 0x2D) is read. In latched tap mode the
     * chip clears INT1 when TAP_SRC (0x1C) is read. Read both so we're
     * agnostic to whatever state the chip was in before. */
    reg = 0x1C;  /* TAP_SRC */
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1) {
        /* Drain failed; not fatal — chip might be silent until reset. */
    }
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1) {
        /* Same — best effort drain. */
    }

    /* 2. Software reset. Try up to 3 times because the very first I2C write
     * after a chip lock-up sometimes NAKs. */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed after retries. "
                "Power-cycle the sensor and rerun.\n");
        return -1;
    }

    /* Wait for reset (datasheet: ~50us; give it 50ms to be safe) */
    struct timespec ts1 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    /* 3. Verify chip is responsive after reset */
    reg = 0x0F;  /* WHO_AM_I */
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1) {
        fprintf(stderr, "WHO_AM_I read after reset failed: %s\n",
                strerror(errno));
        return -1;
    }
    if (scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I=0x%02X (expected 0x6C) after reset\n", scratch);
        return -1;
    }

    /* 4. Now configure for streaming. */
   struct { uint8_t reg, val; } cfg[] = {
        { REG_CTRL3_C,   0x44 },  /* BDU=1, IF_INC=1 */
        { REG_CTRL1_XL,  0x60 },  /* ODR 416 Hz, +/-2g */
        { 0x0B,          0x80 },  /* COUNTER_BDR_REG1: dataready_pulsed=1 */
        { REG_INT1_CTRL, 0x01 },  /* INT1_DRDY_XL: route accel DRDY to I1 */
    };
    for (size_t i = 0; i < sizeof(cfg)/sizeof(cfg[0]); ++i) {
        if (i2c_write_reg_retry(i2c_fd, cfg[i].reg, cfg[i].val, 2) < 0) {
            fprintf(stderr, "config write to reg 0x%02X failed.\n", cfg[i].reg);
            return -1;
        }
    }

    /* Settling */
    struct timespec ts2 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    return 0;
}

/* --- Time helpers --- */
static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

/* --- Sliding-window classifier --- */
typedef struct {
    float buf_x[WINDOW_N];
    float buf_y[WINDOW_N];
    float buf_z[WINDOW_N];
    int   idx;
    int   filled;     /* count of samples written; saturates at WINDOW_N */
} window_t;

static void window_init(window_t *w) {
    memset(w, 0, sizeof(*w));
}

static void window_push(window_t *w, float x, float y, float z) {
    w->buf_x[w->idx] = x;
    w->buf_y[w->idx] = y;
    w->buf_z[w->idx] = z;
    w->idx = (w->idx + 1) % WINDOW_N;
    if (w->filled < WINDOW_N) w->filled++;
}

static float p2p(const float *buf, int n) {
    float mn = buf[0], mx = buf[0];
    for (int i = 1; i < n; ++i) {
        if (buf[i] < mn) mn = buf[i];
        if (buf[i] > mx) mx = buf[i];
    }
    return mx - mn;
}

/* Returns true if any axis P2P exceeds threshold. */
static bool window_classify(const window_t *w) {
    if (w->filled < WINDOW_N) return false;  /* warmup */
    float px = p2p(w->buf_x, WINDOW_N);
    float py = p2p(w->buf_y, WINDOW_N);
    float pz = p2p(w->buf_z, WINDOW_N);
    return (px > TAP_THRESHOLD_G) ||
           (py > TAP_THRESHOLD_G) ||
           (pz > TAP_THRESHOLD_G);
}

/* --- Signal handling --- */
static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

int main(void) {
    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    struct gpiod_line *dec_line = NULL;

    signal(SIGINT, on_sigint);

    /* I2C: open and configure data-ready streaming */
    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_streaming(i2c_fd) < 0) goto cleanup;
    printf("Sensor configured: 416 Hz streaming, DRDY on I1.\n");

    /* GPIO: chip + lines */
    chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) {
        fprintf(stderr, "gpiod_chip_open failed: %s\n", strerror(errno));
        goto cleanup;
    }
    int_line = gpiod_chip_get_line(chip, INT_LINE);
    dec_line = gpiod_chip_get_line(chip, DECISION_LINE);
    if (!int_line || !dec_line) {
        fprintf(stderr, "gpiod_chip_get_line failed\n");
        goto cleanup;
    }
    if (gpiod_line_request_output(dec_line, CONSUMER_NAME, 0) < 0) {
        fprintf(stderr, "request decision line as output failed: %s\n",
                strerror(errno));
        goto cleanup;
    }
    if (gpiod_line_request_rising_edge_events(int_line, CONSUMER_NAME) < 0) {
        fprintf(stderr, "request DRDY line as rising-edge event failed: %s\n",
                strerror(errno));
        goto cleanup;
    }

    printf("Listening for samples at 416 Hz. Tap the breadboard.\n");
    printf("Threshold = %.2f g peak-to-peak, window = %d ms (%d samples).\n",
           TAP_THRESHOLD_G, WINDOW_MS, WINDOW_N);
    printf("Cooldown after positive = %d ms.\n\n", COOLDOWN_MS);
    printf("%-6s %-12s %-8s %-8s %-8s\n",
           "TAP#", "host_dt(us)", "p2p_x", "p2p_y", "p2p_z");

    window_t w;
    window_init(&w);

    int tap_count = 0;
    uint64_t sample_count = 0;
    uint64_t last_positive_ns = 0;
    bool warmed_up = false;

    while (!stop_flag) {
        struct timespec timeout = { .tv_sec = 1, .tv_nsec = 0 };
        int ev = gpiod_line_event_wait(int_line, &timeout);
        if (ev < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, "event_wait error: %s\n", strerror(errno));
            break;
        }
        if (ev == 0) continue;  /* timeout */

        uint64_t t_int_seen_ns = now_ns();

        struct gpiod_line_event line_event;
        if (gpiod_line_event_read(int_line, &line_event) < 0) {
            fprintf(stderr, "event_read error: %s\n", strerror(errno));
            continue;
        }

        /* Read 6 bytes of accelerometer data */
        uint8_t raw[6];
        if (i2c_read_block(i2c_fd, REG_OUTX_L_A, raw, 6) < 0) {
            fprintf(stderr, "i2c read accel failed: %s\n", strerror(errno));
            continue;
        }
        int16_t rx = (int16_t)((raw[1] << 8) | raw[0]);
        int16_t ry = (int16_t)((raw[3] << 8) | raw[2]);
        int16_t rz = (int16_t)((raw[5] << 8) | raw[4]);
        float x = rx * SENS_G_PER_LSB;
        float y = ry * SENS_G_PER_LSB;
        float z = rz * SENS_G_PER_LSB;

        window_push(&w, x, y, z);
        sample_count++;

        if (!warmed_up && w.filled >= WINDOW_N) {
            warmed_up = true;
            printf("Warmup complete after %llu samples (%.1f ms).\n",
                   (unsigned long long)sample_count,
                   (float)sample_count * 1000.0f / ODR_HZ);
        }

        bool positive = window_classify(&w);

        /* Cooldown: ignore positives within COOLDOWN_MS of last positive */
        uint64_t cooldown_ns = (uint64_t)COOLDOWN_MS * 1000000ULL;
        if (positive && (t_int_seen_ns - last_positive_ns) < cooldown_ns) {
            positive = false;
        }

        if (positive) {
            gpiod_line_set_value(dec_line, 1);
            uint64_t t_dec_high_ns = now_ns();
            gpiod_line_set_value(dec_line, 0);

            last_positive_ns = t_int_seen_ns;
            ++tap_count;

            float px = p2p(w.buf_x, WINDOW_N);
            float py = p2p(w.buf_y, WINDOW_N);
            float pz = p2p(w.buf_z, WINDOW_N);

            uint64_t host_dt_us = (t_dec_high_ns - t_int_seen_ns) / 1000ULL;
            printf("%-6d %-12llu %-8.3f %-8.3f %-8.3f\n",
                   tap_count,
                   (unsigned long long)host_dt_us,
                   px, py, pz);
            fflush(stdout);
        }
    }

    printf("\nStopped after %d positive classifications (%llu samples).\n",
           tap_count, (unsigned long long)sample_count);
    rc = 0;

cleanup:
    if (dec_line) gpiod_line_release(dec_line);
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    return rc;
}

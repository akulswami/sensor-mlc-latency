/*
 * imu_logger.c
 *
 * Streams LSM6DSOX accelerometer at configurable ODR via DRDY interrupts
 * on I1, writes each sample to a CSV file with monotonic-clock timestamp.
 *
 * Output format (matches MEMS Studio Unico/Unicleo CSV expectation):
 *   TIME [s],   A_X [g],   A_Y [g],   A_Z [g]
 *   0.000000,   0.015,    -0.018,    1.020
 *   ...
 *
 * Usage: sudo ./imu_logger [--odr HZ] [--fflush] <output_csv>
 *
 *   --odr HZ     Sample rate. Allowed: 26, 52, 104, 208, 416, 833.
 *                Default: 208 (matches docs/training-data-spec.md).
 *   --fflush     fflush() after each sample. Defends against data loss
 *                on kill -9 at the cost of throughput. Default: off.
 *
 * Build: gcc -O2 -Wall -o imu_logger imu_logger.c -lgpiod -lm
 */

#define _POSIX_C_SOURCE 200809L
#include <gpiod.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <sys/ioctl.h>
#include <sys/file.h>
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

/* Hardware bindings (same as host_pipeline) */
#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A
#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define INT_LINE        85    /* PN.01 = pin 15 (sensor I1) */
#define CONSUMER_NAME   "imu-logger"

/* Registers */
#define REG_CTRL1_XL    0x10
#define REG_CTRL3_C     0x12
#define REG_INT1_CTRL   0x0D
#define REG_OUTX_L_A    0x28
#define SENS_G_PER_LSB  (0.061e-3f)

#define BUS_LOCK_PATH   "/tmp/lsm6dsox-bus.lock"

/* ODR table: maps Hz to CTRL1_XL register value (ODR bits in 7:4,
 * range bits in 3:2). All entries use FS=00 (+/-2g). */
typedef struct {
    int hz;
    uint8_t ctrl1_xl;
} odr_entry_t;

static const odr_entry_t ODR_TABLE[] = {
    {  26, 0x20 },
    {  52, 0x30 },
    { 104, 0x40 },
    { 208, 0x50 },
    { 416, 0x60 },
    { 833, 0x70 },
};
static const size_t ODR_TABLE_LEN = sizeof(ODR_TABLE) / sizeof(ODR_TABLE[0]);

#define DEFAULT_ODR_HZ 208

static uint8_t odr_hz_to_ctrl1_xl(int hz) {
    for (size_t i = 0; i < ODR_TABLE_LEN; ++i) {
        if (ODR_TABLE[i].hz == hz) return ODR_TABLE[i].ctrl1_xl;
    }
    return 0;  /* invalid */
}

static void print_supported_odrs(FILE *fp) {
    fprintf(fp, "Supported ODRs (Hz):");
    for (size_t i = 0; i < ODR_TABLE_LEN; ++i) {
        fprintf(fp, " %d", ODR_TABLE[i].hz);
    }
    fprintf(fp, "\n");
}

/* Helpers */
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
static int i2c_write_reg_retry(int fd, uint8_t reg, uint8_t val, int retries) {
    for (int attempt = 0; attempt <= retries; ++attempt) {
        if (i2c_write_reg(fd, reg, val) == 0) return 0;
        if (attempt < retries) {
            struct timespec ts = { .tv_sec = 0, .tv_nsec = 100 * 1000 * 1000 };
            nanosleep(&ts, NULL);
        }
    }
    return -1;
}
static int i2c_read_block(int fd, uint8_t reg, uint8_t *buf, size_t n) {
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = (uint16_t)n, .buf = buf },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}

static int bus_lock_open(void) {
    /* Cross-process I2C bus coordination. mlc_poller may concurrently
     * switch the sensor to embedded bank for MLC0_SRC reads; without
     * mutual exclusion, our reads at OUTX_L_A would resolve in the
     * wrong bank. flock() on a shared lockfile is the minimum-scope
     * fix that keeps imu_logger's measurement behavior unchanged. */
    int fd = open(BUS_LOCK_PATH, O_CREAT | O_RDWR, 0666);
    if (fd < 0) {
        fprintf(stderr, "open(%s): %s\n", BUS_LOCK_PATH, strerror(errno));
    }
    return fd;
}
static int bus_lock_acquire(int fd) {
    while (flock(fd, LOCK_EX) < 0) {
        if (errno == EINTR) continue;
        return -1;
    }
    return 0;
}
static void bus_lock_release(int fd) {
    (void)flock(fd, LOCK_UN);
}

static int configure_streaming(int i2c_fd, int lock_fd, uint8_t ctrl1_xl_value) {
    uint8_t scratch;
    uint8_t reg;

    /* Hold the bus lock for the entire configure sequence. Without
     * this, a concurrent mlc_poller bank-switch can cause our writes
     * to CTRL3_C / CTRL1_XL / INT1_CTRL to land in the embedded bank,
     * surfacing as 'sw_reset failed' or 'WHO_AM_I check failed'. */
    if (bus_lock_acquire(lock_fd) < 0) {
        fprintf(stderr, "configure_streaming: bus_lock_acquire failed: %s\n",
                strerror(errno));
        return -1;
    }

    /* Drain any latched interrupt */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* SW_RESET */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed. Power-cycle sensor.\n");
        bus_lock_release(lock_fd);
        return -1;
    }
    struct timespec ts1 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    /* WHO_AM_I check */
    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1 || scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I check failed: 0x%02X\n", scratch);
        bus_lock_release(lock_fd);
        return -1;
    }

    /* Configure: BDU=1 IF_INC=1, ODR/range per ctrl1_xl_value, pulsed DRDY,
     * INT1=DRDY */
    struct { uint8_t reg, val; } cfg[] = {
        { REG_CTRL3_C,   0x44 },
        { REG_CTRL1_XL,  ctrl1_xl_value },
        { 0x0B,          0x80 },  /* COUNTER_BDR_REG1: dataready_pulsed=1 */
        { REG_INT1_CTRL, 0x01 },
    };
    for (size_t i = 0; i < sizeof(cfg)/sizeof(cfg[0]); ++i) {
        if (i2c_write_reg_retry(i2c_fd, cfg[i].reg, cfg[i].val, 2) < 0) {
            fprintf(stderr, "config write 0x%02X failed.\n", cfg[i].reg);
            bus_lock_release(lock_fd);
            return -1;
        }
    }
    struct timespec ts2 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    bus_lock_release(lock_fd);
    return 0;
}

static inline double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

static void usage(const char *prog) {
    fprintf(stderr, "Usage: %s [--odr HZ] [--fflush] <output_csv>\n", prog);
    fprintf(stderr, "  --odr HZ     Sample rate (default: %d).\n", DEFAULT_ODR_HZ);
    fprintf(stderr, "  --fflush     fflush after each sample (default: off).\n");
    print_supported_odrs(stderr);
}

int main(int argc, char **argv) {
    /* Defaults */
    int odr_hz = DEFAULT_ODR_HZ;
    int do_fflush = 0;
    const char *out_path = NULL;

    /* Argv parsing: flags then positional out_path */
    for (int i = 1; i < argc; ++i) {
        if (strcmp(argv[i], "--odr") == 0 && i + 1 < argc) {
            odr_hz = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--fflush") == 0) {
            do_fflush = 1;
        } else if (argv[i][0] == '-') {
            fprintf(stderr, "Unknown flag: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        } else if (!out_path) {
            out_path = argv[i];
        } else {
            fprintf(stderr, "Unexpected argument: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
    }

    if (!out_path) {
        usage(argv[0]);
        return 1;
    }

    uint8_t ctrl1_xl = odr_hz_to_ctrl1_xl(odr_hz);
    if (ctrl1_xl == 0) {
        fprintf(stderr, "Invalid --odr value: %d\n", odr_hz);
        print_supported_odrs(stderr);
        return 1;
    }

    int rc = 1;
    int i2c_fd = -1;
    int lock_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    FILE *fp = NULL;

    signal(SIGINT, on_sigint);
    signal(SIGTERM, on_sigint);  /* `timeout` sends SIGTERM; treat same as Ctrl+C */

    fp = fopen(out_path, "w");
    if (!fp) {
        fprintf(stderr, "fopen(%s): %s\n", out_path, strerror(errno));
        return 1;
    }
    /* Line-buffer the output so each \n flushes to the kernel. Defends
     * against truncated last row if the process is killed abruptly
     * (SIGTERM/SIGKILL from `timeout`, kill -9, power loss, etc).
     * Cost: one syscall per sample. At 208 Hz this is negligible on Orin Nano. */
    setvbuf(fp, NULL, _IOLBF, 0);
    fprintf(fp, "TIME [s], A_X [g], A_Y [g], A_Z [g]\n");

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) { fprintf(stderr, "i2c open: %s\n", strerror(errno)); goto cleanup; }
    lock_fd = bus_lock_open();
    if (lock_fd < 0) goto cleanup;

    if (configure_streaming(i2c_fd, lock_fd, ctrl1_xl) < 0) goto cleanup;
    fprintf(stderr, "Sensor configured at %d Hz (CTRL1_XL=0x%02X). Logging to %s. Ctrl+C to stop.\n",
            odr_hz, ctrl1_xl, out_path);
    if (do_fflush) fprintf(stderr, "fflush after each sample: enabled.\n");

    chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) { fprintf(stderr, "gpiod_chip_open: %s\n", strerror(errno)); goto cleanup; }
    int_line = gpiod_chip_get_line(chip, INT_LINE);
    if (!int_line) { fprintf(stderr, "get_line failed\n"); goto cleanup; }
    if (gpiod_line_request_rising_edge_events(int_line, CONSUMER_NAME) < 0) {
        fprintf(stderr, "request rising edge: %s\n", strerror(errno));
        goto cleanup;
    }

    double t0 = now_s();
    fprintf(stderr, "t0_monotonic_s = %.6f\n", t0);
    double t_next_progress = 2.0;  /* first progress print after 2 sec */
    uint64_t sample_count = 0;

    while (!stop_flag) {
        struct timespec timeout = { .tv_sec = 1, .tv_nsec = 0 };
        int ev = gpiod_line_event_wait(int_line, &timeout);
        if (ev < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, "event_wait: %s\n", strerror(errno));
            break;
        }
        if (ev == 0) continue;

        struct gpiod_line_event line_event;
        if (gpiod_line_event_read(int_line, &line_event) < 0) continue;

        uint8_t raw[6];
        if (bus_lock_acquire(lock_fd) < 0) {
            fprintf(stderr, "bus_lock_acquire failed: %s\n", strerror(errno));
            continue;
        }
        int read_rc = i2c_read_block(i2c_fd, REG_OUTX_L_A, raw, 6);
        bus_lock_release(lock_fd);
        if (read_rc < 0) continue;

        int16_t rx = (int16_t)((raw[1] << 8) | raw[0]);
        int16_t ry = (int16_t)((raw[3] << 8) | raw[2]);
        int16_t rz = (int16_t)((raw[5] << 8) | raw[4]);
        float x = rx * SENS_G_PER_LSB;
        float y = ry * SENS_G_PER_LSB;
        float z = rz * SENS_G_PER_LSB;

        double t = now_s() - t0;
        fprintf(fp, "%.6f, %.4f, %.4f, %.4f\n", t, x, y, z);
        if (do_fflush) fflush(fp);
        ++sample_count;

        /* Time-based progress print, regardless of ODR */
        if (t >= t_next_progress) {
            fprintf(stderr, "  %llu samples (%.1f s, %.1f Hz effective)\n",
                    (unsigned long long)sample_count, t,
                    (double)sample_count / t);
            t_next_progress = t + 2.0;
        }
    }

    fprintf(stderr, "Stopped. Wrote %llu samples to %s.\n",
            (unsigned long long)sample_count, out_path);
    rc = 0;

cleanup:
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    if (lock_fd >= 0) close(lock_fd);
    if (fp) fclose(fp);
    return rc;
}

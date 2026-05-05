/*
 * imu_logger.c
 *
 * Streams LSM6DSOX accelerometer at 416 Hz via DRDY interrupts on I1,
 * writes each sample to a CSV file with monotonic-clock timestamp.
 *
 * Output format (matches MEMS Studio Unico/Unicleo CSV expectation):
 *   TIME [s],   A_X [g],   A_Y [g],   A_Z [g]
 *   0.000000,   0.015,    -0.018,    1.020
 *   ...
 *
 * Usage: sudo ./imu_logger <output_csv>
 *
 * Build: gcc -O2 -Wall -o imu_logger imu_logger.c -lgpiod -lm
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

static int configure_streaming(int i2c_fd) {
    uint8_t scratch;
    uint8_t reg;

    /* Drain any latched interrupt */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* SW_RESET */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed. Power-cycle sensor.\n");
        return -1;
    }
    struct timespec ts1 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    /* WHO_AM_I check */
    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1 || scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I check failed: 0x%02X\n", scratch);
        return -1;
    }

    /* Configure: BDU=1 IF_INC=1, ODR 416Hz +/-2g, pulsed DRDY, INT1=DRDY */
    struct { uint8_t reg, val; } cfg[] = {
        { REG_CTRL3_C,   0x44 },
        { REG_CTRL1_XL,  0x60 },
        { 0x0B,          0x80 },  /* COUNTER_BDR_REG1: dataready_pulsed=1 */
        { REG_INT1_CTRL, 0x01 },
    };
    for (size_t i = 0; i < sizeof(cfg)/sizeof(cfg[0]); ++i) {
        if (i2c_write_reg_retry(i2c_fd, cfg[i].reg, cfg[i].val, 2) < 0) {
            fprintf(stderr, "config write 0x%02X failed.\n", cfg[i].reg);
            return -1;
        }
    }
    struct timespec ts2 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    return 0;
}

static inline double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <output_csv>\n", argv[0]);
        return 1;
    }
    const char *out_path = argv[1];

    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    FILE *fp = NULL;

    signal(SIGINT, on_sigint);

    fp = fopen(out_path, "w");
    if (!fp) {
        fprintf(stderr, "fopen(%s): %s\n", out_path, strerror(errno));
        return 1;
    }
    fprintf(fp, "TIME [s], A_X [g], A_Y [g], A_Z [g]\n");

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) { fprintf(stderr, "i2c open: %s\n", strerror(errno)); goto cleanup; }
    if (configure_streaming(i2c_fd) < 0) goto cleanup;
    fprintf(stderr, "Sensor configured at 416 Hz. Logging to %s. Ctrl+C to stop.\n", out_path);

    chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) { fprintf(stderr, "gpiod_chip_open: %s\n", strerror(errno)); goto cleanup; }
    int_line = gpiod_chip_get_line(chip, INT_LINE);
    if (!int_line) { fprintf(stderr, "get_line failed\n"); goto cleanup; }
    if (gpiod_line_request_rising_edge_events(int_line, CONSUMER_NAME) < 0) {
        fprintf(stderr, "request rising edge: %s\n", strerror(errno));
        goto cleanup;
    }

    double t0 = now_s();
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
        if (i2c_read_block(i2c_fd, REG_OUTX_L_A, raw, 6) < 0) continue;

        int16_t rx = (int16_t)((raw[1] << 8) | raw[0]);
        int16_t ry = (int16_t)((raw[3] << 8) | raw[2]);
        int16_t rz = (int16_t)((raw[5] << 8) | raw[4]);
        float x = rx * SENS_G_PER_LSB;
        float y = ry * SENS_G_PER_LSB;
        float z = rz * SENS_G_PER_LSB;

        double t = now_s() - t0;
        fprintf(fp, "%.6f, %.4f, %.4f, %.4f\n", t, x, y, z);
        ++sample_count;

        /* Print progress every ~2 sec */
        if (sample_count % 832 == 0) {
            fprintf(stderr, "  %llu samples (%.1f s)\n",
                    (unsigned long long)sample_count, t);
        }
    }

    fprintf(stderr, "Stopped. Wrote %llu samples to %s.\n",
            (unsigned long long)sample_count, out_path);
    rc = 0;

cleanup:
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    if (fp) fclose(fp);
    return rc;
}

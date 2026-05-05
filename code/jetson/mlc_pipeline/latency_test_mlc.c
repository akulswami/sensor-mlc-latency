/*
 * latency_test_mlc.c
 *
 * B6: Wire-level latency measurement of the on-sensor MLC pipeline.
 *
 * Loads an MLC configuration (header file generated from MEMS Studio JSON
 * via json_to_header.py), applies it to the LSM6DSOX, then waits for
 * INT1 rising edges (MLC0_SRC change), reads the MLC output, and toggles
 * the decision GPIO if the output indicates a tap.
 *
 * Compile-time selection of MLC config:
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_accuracy.h\" -o latency_test_mlc_acc latency_test_mlc.c -lgpiod
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_latency.h\"  -o latency_test_mlc_lat latency_test_mlc.c -lgpiod
 *
 * Saleae:
 *   D0 = Pin 15 (sensor INT1)    -- rising edge marks MLC fired
 *   D1 = Pin 11 (decision GPIO)  -- rising edge marks host detected tap
 *   A0 = piezo                   -- ground truth
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

#ifndef MLC_CONFIG_HEADER
#error "Define MLC_CONFIG_HEADER to a header path. Use -DMLC_CONFIG_HEADER=\\\"mlc_accuracy.h\\\""
#endif
#include MLC_CONFIG_HEADER

/* Hardware bindings (same as latency_test.c, host_pipeline.c) */
#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A
#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define INT_LINE        85    /* PN.01 = pin 15 (sensor I1) */
#define DECISION_LINE   112   /* PR.04 = pin 11 (decision GPIO) */
#define CONSUMER_NAME   "mlc-latency"

/* Registers we'll touch directly */
#define REG_FUNC_CFG_ACCESS  0x01
#define REG_CTRL3_C          0x12
#define REG_MLC0_SRC         0x70  /* in embedded bank */

/* FUNC_CFG_ACCESS bank values */
#define BANK_USER       0x00
#define BANK_EMBEDDED   0x80   /* bit 7 selects embedded func bank; 0x40 was sensor hub */

/* I2C primitives */
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
static int i2c_read_reg(int fd, uint8_t reg, uint8_t *val) {
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = 1, .buf = val },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}

/*
 * Read MLC0_SRC. The MLC source registers live in the embedded function
 * bank, so we must switch banks, read, then switch back.
 *
 * This adds ~3 I2C transactions of overhead per read (~100-200 us at
 * 400 kHz). That overhead is part of the on-sensor pipeline's measured
 * latency; we are not isolating it.
 */
static int read_mlc_src(int fd, uint8_t *val) {
    if (i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_EMBEDDED) < 0) return -1;
    if (i2c_read_reg(fd, REG_MLC0_SRC, val) < 0) {
        (void)i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_USER);
        return -1;
    }
    if (i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_USER) < 0) return -1;
    return 0;
}

/* Configure: SW reset, verify chip, then apply the .ucf-equivalent writes. */
static int configure_mlc(int i2c_fd) {
    uint8_t scratch;
    uint8_t reg;

    /* Drain any latched interrupt state from prior runs */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* SW_RESET */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed. Power-cycle the sensor.\n");
        return -1;
    }
    struct timespec ts1 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    /* Verify chip is alive after reset */
    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1 || scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I check failed: 0x%02X\n", scratch);
        return -1;
    }

    /* Apply the MLC configuration sequence (from generated header). */
    fprintf(stderr, "Loading %d MLC config writes...\n", MLC_CONFIG_LEN);
    for (size_t i = 0; i < MLC_CONFIG_LEN; ++i) {
        if (i2c_write_reg_retry(i2c_fd, MLC_CONFIG[i].reg, MLC_CONFIG[i].val, 2) < 0) {
            fprintf(stderr, "MLC config write %zu (reg 0x%02X val 0x%02X) failed\n",
                    i, MLC_CONFIG[i].reg, MLC_CONFIG[i].val);
            return -1;
        }
    }
    fprintf(stderr, "MLC config applied. Tap class = 0x%02X, nontap = 0x%02X\n",
            MLC_OUT_TAP, MLC_OUT_NONTAP);

    /* Force INT1_CTRL = 0 (user bank, register 0x0D).
     * Empirical observation: without this, INT1 fires at the accelerometer
     * ODR (~416 Hz), suggesting DRDY routing was implicitly enabled by the
     * .ucf or persisted from prior chip state. Explicitly disable so only
     * embedded function (MLC) interrupts reach INT1. */
    if (i2c_write_reg_retry(i2c_fd, 0x0D, 0x00, 2) < 0) {
        fprintf(stderr, "INT1_CTRL clear failed\n");
        return -1;
    }
    fprintf(stderr, "INT1_CTRL forced to 0x00 (DRDY routing disabled).\n");

    /* Enable EMB_FUNC_LIR (latched interrupt mode for embedded functions).
     * Per AN5273: "Latched mode can be enabled by setting the EMB_FUNC_LIR
     * bit of the PAGE_RW (17h) embedded functions register to 1."
     *
     * In default (pulsed) mode the MLC INT1 pulse is ~9.6ms wide, but
     * MLC0_SRC may revert to 0 before our bank-switch + read completes.
     * Latched mode keeps INT1 asserted and MLC0_SRC stable until we read
     * MLC0_SRC, which clears the latch.
     */
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x80, 2) < 0) {  /* bank -> embedded */
        fprintf(stderr, "bank switch to embedded failed\n");
        return -1;
    }
    if (i2c_write_reg_retry(i2c_fd, 0x17, 0x80, 2) < 0) {  /* PAGE_RW EMB_FUNC_LIR=1 */
        fprintf(stderr, "EMB_FUNC_LIR set failed\n");
        return -1;
    }
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x00, 2) < 0) {  /* bank -> user */
        fprintf(stderr, "bank switch back to user failed\n");
        return -1;
    }
    fprintf(stderr, "EMB_FUNC_LIR enabled (latched MLC interrupts).\n");

    /* Settling */
    struct timespec ts2 = { .tv_sec = 0, .tv_nsec = 100 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    return 0;
}

static inline uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

int main(void) {
    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    struct gpiod_line *dec_line = NULL;

    signal(SIGINT, on_sigint);

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_mlc(i2c_fd) < 0) goto cleanup;

    chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) { fprintf(stderr, "gpiod_chip_open: %s\n", strerror(errno)); goto cleanup; }
    int_line = gpiod_chip_get_line(chip, INT_LINE);
    dec_line = gpiod_chip_get_line(chip, DECISION_LINE);
    if (!int_line || !dec_line) {
        fprintf(stderr, "gpiod_chip_get_line failed\n");
        goto cleanup;
    }
    if (gpiod_line_request_output(dec_line, CONSUMER_NAME, 0) < 0) {
        fprintf(stderr, "request decision line as output failed: %s\n", strerror(errno));
        goto cleanup;
    }
    if (gpiod_line_request_rising_edge_events(int_line, CONSUMER_NAME) < 0) {
        fprintf(stderr, "request INT line rising-edge: %s\n", strerror(errno));
        goto cleanup;
    }

    fprintf(stderr, "Listening for MLC INT1 events. Tap. Ctrl+C to stop.\n");
    fprintf(stderr, "Saleae D0=Pin15(INT), D1=Pin11(decision), A0=piezo.\n");
    printf("\n%-6s %-12s %-8s\n", "EVENT#", "host_dt(us)", "mlc_src");

    int event_count = 0;
    int tap_count = 0;
    while (!stop_flag) {
        struct timespec timeout = { .tv_sec = 1, .tv_nsec = 0 };
        int ev = gpiod_line_event_wait(int_line, &timeout);
        if (ev < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, "event_wait error: %s\n", strerror(errno));
            break;
        }
        if (ev == 0) continue;

        uint64_t t_int_seen_ns = now_ns();

        struct gpiod_line_event line_event;
        if (gpiod_line_event_read(int_line, &line_event) < 0) continue;

        uint8_t mlc_src;
        if (read_mlc_src(i2c_fd, &mlc_src) < 0) continue;

        ++event_count;

        if (mlc_src == MLC_OUT_TAP) {
            /* Toggle decision GPIO immediately - this is the wire-level
             * "decision" edge that the Saleae captures on D1. */
            gpiod_line_set_value(dec_line, 1);
            gpiod_line_set_value(dec_line, 0);
            uint64_t t_decided_ns = now_ns();
            ++tap_count;

            uint64_t host_dt_us = (t_decided_ns - t_int_seen_ns) / 1000;
            printf("%-6d %-12llu %-8s\n",
                   tap_count, (unsigned long long)host_dt_us, "TAP");
            fflush(stdout);
        } else {
            /* Non-tap MLC interrupt - chip says state changed but to
             * non-tap class. Don't toggle decision GPIO. */
            printf("(%d) mlc_src=0x%02X (nontap state change, ignored)\n",
                   event_count, mlc_src);
            fflush(stdout);
        }
    }

    fprintf(stderr, "\nStopped after %d events, %d taps.\n", event_count, tap_count);
    rc = 0;

cleanup:
    if (int_line) gpiod_line_release(int_line);
    if (dec_line) gpiod_line_release(dec_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    return rc;
}

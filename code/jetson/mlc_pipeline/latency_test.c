/*
 * latency_test.c
 *
 * B4: First wire-level latency measurement of the on-sensor classification
 * pipeline (using LSM6DSOX hardware single-tap detector as a stand-in for
 * the MLC engine, which behaves identically from the host's perspective).
 *
 * Behavior:
 *   1. Configure LSM6DSOX single-tap detector via I2C, route INT to I1 pin.
 *   2. Open Pin 15 (gpiochip0 line 85, PN.01) as falling-edge interrupt.
 *      [Edge direction note: see RISING_INT_NOTE below.]
 *   3. Open Pin 11 (gpiochip0 line 112, PR.04) as output, decision edge.
 *   4. Loop:
 *        - Block on INT event
 *        - Read TAP_SRC register (the "classification result")
 *        - Drive decision GPIO high, then low (~1us pulse)
 *        - Log host-side timestamps for debugging
 *
 * Wire-level latency is measured externally by the Saleae:
 *   D0 = Pin 15 (sensor INT)    -- rising edge marks event start
 *   D1 = Pin 11 (decision GPIO) -- rising edge marks decision
 *   Latency = t(D1 rising) - t(D0 rising)
 *
 * RISING_INT_NOTE:
 * The LSM6DSOX I1 pin idles low and pulses high on a tap event (active-high
 * pulse). We register for RISING edges (not falling).
 *
 * Build: gcc -O2 -Wall -o latency_test latency_test.c -lgpiod -li2c
 *
 * If linking with -li2c fails (the kernel's i2c-dev does not need a separate
 * lib on most distros), drop -li2c and use SMBus ioctls via fd directly.
 * The simpler path here is to use the already-installed Python i2c stack
 * for register access -- but for fairness with the host pipeline we want
 * everything in C.  We use raw read()/write() on /dev/i2c-7 with
 * I2C_SLAVE ioctl, which needs no extra library.
 *
 * Run: sudo ./latency_test
 */

#define _POSIX_C_SOURCE 200809L
#include <gpiod.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>
#include <signal.h>

/* --- Hardware bindings --- */
#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A

#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define INT_LINE        85    /* PN.01 = pin 15  -- sensor I1 (input) */
#define DECISION_LINE   112   /* PR.04 = pin 11  -- decision (output) */

#define CONSUMER_NAME   "sensor-mlc-latency"

/* --- Sensor registers (subset; see B1 script for full context) --- */
#define REG_CTRL1_XL    0x10
#define REG_CTRL3_C     0x12
#define REG_TAP_CFG0    0x56
#define REG_TAP_CFG1    0x57
#define REG_TAP_CFG2    0x58
#define REG_TAP_THS_6D  0x59
#define REG_INT_DUR2    0x5A
#define REG_WAKE_UP_THS 0x5B
#define REG_MD1_CFG     0x5E
#define REG_TAP_SRC     0x1C

/* --- I2C helpers --- */
static int i2c_open_and_select(const char *dev, uint8_t addr) {
    int fd = open(dev, O_RDWR);
    if (fd < 0) return -1;
    if (ioctl(fd, I2C_SLAVE, addr) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

static int i2c_write_reg(int fd, uint8_t reg, uint8_t val) {
    uint8_t buf[2] = { reg, val };
    return (write(fd, buf, 2) == 2) ? 0 : -1;
}

static int i2c_read_reg(int fd, uint8_t reg, uint8_t *val) {
    if (write(fd, &reg, 1) != 1) return -1;
    if (read(fd, val, 1) != 1)  return -1;
    return 0;
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

static int configure_tap_detector(int i2c_fd) {
    uint8_t scratch;
    uint8_t reg;

    /* 1. Drain any latched interrupts. In latched DRDY mode the chip clears
     * INT1 only when the high byte of an enabled axis (0x29, 0x2B, 0x2D) is
     * read. In latched tap mode the chip clears INT1 when TAP_SRC (0x1C) is
     * read. Read both so we recover from whatever state the chip was in.
     * Failures here are non-fatal -- chip may be unresponsive until reset. */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* 2. Software reset to wipe any prior config (e.g. from host_pipeline
     * leaving DRDY routed to INT1). Retry up to 3 times because the very
     * first I2C write after a chip lock-up sometimes NAKs. */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed after retries. "
                "Power-cycle the sensor and rerun.\n");
        return -1;
    }

    /* Wait for reset (datasheet: ~50us; give 50ms to be safe) */
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

    /* 4. Now configure tap detection. */
    struct { uint8_t reg, val; } cfg[] = {
        { REG_CTRL1_XL,    0x60 },  /* ODR 416 Hz, +/-2g */
        { REG_TAP_CFG0,    0x0E },  /* enable tap on X,Y,Z; pulse mode (LIR=0) */
        { REG_TAP_CFG1,    0x88 },  /* X tap threshold ~500 mg, enable */
        { REG_TAP_CFG2,    0x88 },  /* Y tap threshold ~500 mg, enable */
        { REG_TAP_THS_6D,  0x88 },  /* Z tap threshold ~500 mg */
        { REG_INT_DUR2,    0x06 },  /* tap quiet/shock durations */
        { REG_WAKE_UP_THS, 0x00 },  /* single-tap mode */
        { REG_MD1_CFG,     0x40 },  /* route single-tap event to I1 */
    };
    for (size_t i = 0; i < sizeof(cfg)/sizeof(cfg[0]); ++i) {
        if (i2c_write_reg_retry(i2c_fd, cfg[i].reg, cfg[i].val, 2) < 0) {
            fprintf(stderr, "config write to reg 0x%02X failed.\n", cfg[i].reg);
            return -1;
        }
    }

    /* settling time after config */
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

/* --- Signal handling for clean Ctrl+C --- */
static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

int main(void) {
    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    struct gpiod_line *dec_line = NULL;

    signal(SIGINT, on_sigint);

    /* I2C: open and configure tap detector */
    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_tap_detector(i2c_fd) < 0) goto cleanup;
    printf("Tap detector configured (500mg threshold, single-tap, INT to I1).\n");

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

    /* Decision line: output, start low */
    if (gpiod_line_request_output(dec_line, CONSUMER_NAME, 0) < 0) {
        fprintf(stderr, "request decision line as output failed: %s\n",
                strerror(errno));
        goto cleanup;
    }

    /* INT line: input, listen for rising edges */
    if (gpiod_line_request_rising_edge_events(int_line, CONSUMER_NAME) < 0) {
        fprintf(stderr, "request INT line as rising-edge event failed: %s\n",
                strerror(errno));
        goto cleanup;
    }

    printf("Listening for taps. Tap the breadboard. Ctrl+C to stop.\n");
    printf("Saleae D0 should be on Pin 15 (INT), D1 on Pin 11 (decision).\n\n");
    printf("%-6s %-12s %-10s %-10s\n",
           "TAP#", "host_dt(us)", "axes", "raw");

    int tap_count = 0;
    while (!stop_flag) {
        /* Block until rising edge or signal. Timeout = 1 sec to allow Ctrl+C. */
        struct timespec timeout = { .tv_sec = 1, .tv_nsec = 0 };
        int ev = gpiod_line_event_wait(int_line, &timeout);
        if (ev < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, "event_wait error: %s\n", strerror(errno));
            break;
        }
        if (ev == 0) continue;  /* timeout, no event */

        /* Capture host's first-observable time as soon as event_wait returns. */
        uint64_t t_int_seen_ns = now_ns();

        /* Drain the event */
        struct gpiod_line_event line_event;
        if (gpiod_line_event_read(int_line, &line_event) < 0) {
            fprintf(stderr, "event_read error: %s\n", strerror(errno));
            continue;
        }

        /* Read TAP_SRC -- this is the "classification result" the host needs */
        uint8_t tap_src = 0;
        i2c_read_reg(i2c_fd, REG_TAP_SRC, &tap_src);

        /* Toggle decision edge: high then low (~brief pulse). The rising edge
         * is what the Saleae anchors on. */
        gpiod_line_set_value(dec_line, 1);
        uint64_t t_dec_high_ns = now_ns();
        gpiod_line_set_value(dec_line, 0);

        /* Decode for the log */
        char axes[8] = "";
        if (tap_src & 0x04) strcat(axes, "Z");
        if (tap_src & 0x02) strcat(axes, "Y");
        if (tap_src & 0x01) strcat(axes, "X");
        if (axes[0] == '\0') strcpy(axes, "?");

        uint64_t host_dt_us = (t_dec_high_ns - t_int_seen_ns) / 1000ULL;

        ++tap_count;
        printf("%-6d %-12llu %-10s 0x%02X\n",
               tap_count, (unsigned long long)host_dt_us, axes, tap_src);
        fflush(stdout);
    }

    printf("\nStopped after %d taps.\n", tap_count);
    rc = 0;

cleanup:
    if (dec_line) gpiod_line_release(dec_line);
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    return rc;
}

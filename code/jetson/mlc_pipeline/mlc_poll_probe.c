/*
 * mlc_poll_probe.c
 *
 * B6 DIAGNOSTIC (not for paper data). Goal: determine whether the MLC is
 * actually classifying live taps. Decoupled from INT1 routing entirely:
 * we POLL MLC0_SRC and print every non-zero observation with a timestamp.
 *
 * Two modes:
 *
 *   --pulsed   : EMB_FUNC_LIR=0 (default-pulsed). MLC0_SRC reflects the
 *                CURRENT class for ~9.6 ms after a state change, then
 *                may revert. Poll fast (default 2 ms) to catch pulses.
 *
 *   --latched  : EMB_FUNC_LIR=1 (matches latency_test_mlc.c). MLC0_SRC
 *                holds the latched value until read; reading clears the
 *                latch. Poll slower (default 50 ms) since holding is
 *                guaranteed.
 *
 * What each mode tells us:
 *
 *   pulsed mode is the decisive test. If we see 0x04 transiently while
 *   tapping, the model is running on-chip and the bug in latency_test_mlc.c
 *   is in the latched-read / interrupt-routing path. If we never see 0x04
 *   in pulsed mode despite real piezo-confirmed taps, the model is not
 *   classifying taps -- and THEN the question is whether it's a model
 *   issue (won't be fixed by INT plumbing) or a config-load issue (won't
 *   be fixed by retraining).
 *
 *   latched mode tells us only what latency_test_mlc.c already told us:
 *   what the latch holds at read time. If we see 0x04 once at startup
 *   and never again, that's consistent with a single-shot fire that was
 *   then masked by the latch -- not informative on its own.
 *
 * NOT for measurement runs. This binary deliberately does not toggle the
 * decision GPIO and does not pretend to be the on-sensor pipeline timing
 * harness. Keep it out of any paper data path.
 *
 * Compile:
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_latency.h\"  -o mlc_poll_probe_lat mlc_poll_probe.c
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_accuracy.h\" -o mlc_poll_probe_acc mlc_poll_probe.c
 *
 * Run:
 *   sudo ./mlc_poll_probe_lat --pulsed
 *   sudo ./mlc_poll_probe_lat --latched
 *   (Ctrl+C to stop. Tap when prompted.)
 */

#define _POSIX_C_SOURCE 200809L
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
#error "Define MLC_CONFIG_HEADER. Use -DMLC_CONFIG_HEADER=\\\"mlc_latency.h\\\""
#endif
#include MLC_CONFIG_HEADER

#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A

#define REG_FUNC_CFG_ACCESS  0x01
#define REG_CTRL3_C          0x12
#define REG_MLC0_SRC         0x70

#define BANK_USER       0x00
#define BANK_EMBEDDED   0x80   /* match the value the .ucf actually writes */

/* I2C primitives (minimal copy of latency_test_mlc.c style) */
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
    for (int a = 0; a <= retries; ++a) {
        if (i2c_write_reg(fd, reg, val) == 0) return 0;
        if (a < retries) {
            struct timespec ts = { 0, 100 * 1000 * 1000 };
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

static int read_mlc_src(int fd, uint8_t *val) {
    if (i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_EMBEDDED) < 0) return -1;
    if (i2c_read_reg(fd, REG_MLC0_SRC, val) < 0) {
        (void)i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_USER);
        return -1;
    }
    if (i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_USER) < 0) return -1;
    return 0;
}

static int configure_mlc(int i2c_fd, bool latched) {
    uint8_t scratch;
    uint8_t reg;

    /* Drain latched int state from prior runs. */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* SW_RESET */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed. Power-cycle the sensor.\n");
        return -1;
    }
    struct timespec ts1 = { 0, 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1 || scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I check failed: 0x%02X\n", scratch);
        return -1;
    }

    fprintf(stderr, "Loading %d MLC config writes...\n", MLC_CONFIG_LEN);
    for (size_t i = 0; i < MLC_CONFIG_LEN; ++i) {
        if (i2c_write_reg_retry(i2c_fd, MLC_CONFIG[i].reg, MLC_CONFIG[i].val, 2) < 0) {
            fprintf(stderr, "MLC config write %zu failed\n", i);
            return -1;
        }
    }
    fprintf(stderr, "MLC config applied. TAP=0x%02X NONTAP=0x%02X\n",
            MLC_OUT_TAP, MLC_OUT_NONTAP);

    /* INT1_CTRL=0 -- not strictly required for polling, but matches
     * latency_test_mlc.c chip state so this probe is comparing apples to
     * apples. */
    if (i2c_write_reg_retry(i2c_fd, 0x0D, 0x00, 2) < 0) {
        fprintf(stderr, "INT1_CTRL clear failed\n");
        return -1;
    }

    /* EMB_FUNC_LIR via PAGE_RW (0x17 in embedded bank). */
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x80, 2) < 0) return -1;
    if (i2c_write_reg_retry(i2c_fd, 0x17, latched ? 0x80 : 0x00, 2) < 0) return -1;
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x00, 2) < 0) return -1;

    fprintf(stderr, "EMB_FUNC_LIR = %s\n", latched ? "1 (latched)" : "0 (pulsed)");

    struct timespec ts2 = { 0, 100 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    return 0;
}

static inline uint64_t now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)ts.tv_nsec / 1000000ULL;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

int main(int argc, char **argv) {
    bool latched = false;          /* default pulsed (the decisive mode) */
    int poll_us = -1;              /* -1 = use mode default */

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--pulsed"))       latched = false;
        else if (!strcmp(argv[i], "--latched")) latched = true;
        else if (!strcmp(argv[i], "--poll-us") && i + 1 < argc) {
            poll_us = atoi(argv[++i]);
        } else {
            fprintf(stderr,
                "usage: %s [--pulsed | --latched] [--poll-us N]\n"
                "  --pulsed   : EMB_FUNC_LIR=0, default poll 2000 us\n"
                "  --latched  : EMB_FUNC_LIR=1, default poll 50000 us\n",
                argv[0]);
            return 2;
        }
    }
    if (poll_us < 0) poll_us = latched ? 50000 : 2000;

    signal(SIGINT, on_sigint);

    int i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open failed: %s\n", strerror(errno));
        return 1;
    }
    if (configure_mlc(i2c_fd, latched) < 0) {
        close(i2c_fd);
        return 1;
    }

    fprintf(stderr, "\n=== POLLING %s @ %d us ===\n",
            latched ? "LATCHED" : "PULSED", poll_us);
    fprintf(stderr, "Tap with piezo on Saleae A0. Ctrl+C to stop.\n");
    fprintf(stderr, "Will print every transition out of 0x00.\n\n");

    /* Print column header. We log:
     *   - run-time elapsed ms
     *   - new MLC0_SRC value
     *   - poll count since last transition (rough idea of how long it sat at 0)
     *
     * We deliberately do not print every poll -- only transitions -- to keep
     * output legible. Add --verbose later if you need full trace. */
    printf("%-12s %-8s %-12s\n", "elapsed_ms", "src", "polls_at_0");

    uint64_t t0 = now_ms();
    uint8_t prev = 0x00;
    uint64_t polls_at_zero = 0;
    uint64_t total_polls = 0;
    uint64_t total_nonzero_seen = 0;
    /* Track unique non-zero values for end-of-run summary. */
    uint8_t seen_values[256] = {0};

    /* Initial read to flush any startup state out of the latch in latched
     * mode, so we don't report the well-known boot artifact as a tap. */
    {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) == 0 && v != 0x00) {
            fprintf(stderr, "[startup] MLC0_SRC=0x%02X (cleared)\n", v);
        }
    }

    struct timespec poll_ts = { 0, (long)poll_us * 1000L };
    while (!stop_flag) {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) < 0) {
            fprintf(stderr, "read_mlc_src failed: %s\n", strerror(errno));
            break;
        }
        ++total_polls;
        if (v == 0x00) {
            ++polls_at_zero;
        } else {
            ++total_nonzero_seen;
            seen_values[v]++;
        }

        if (v != prev) {
            uint64_t dt = now_ms() - t0;
            const char *tag = "";
            if (v == MLC_OUT_TAP)        tag = " <-- TAP";
            else if (v == MLC_OUT_NONTAP && prev != 0x00) tag = " (back to non-tap)";
            printf("%-12llu 0x%02X     %-12llu%s\n",
                   (unsigned long long)dt, v,
                   (unsigned long long)polls_at_zero, tag);
            fflush(stdout);
            polls_at_zero = 0;
            prev = v;
        }
        nanosleep(&poll_ts, NULL);
    }

    fprintf(stderr, "\n=== SUMMARY ===\n");
    fprintf(stderr, "mode:               %s\n", latched ? "LATCHED" : "PULSED");
    fprintf(stderr, "poll interval:      %d us\n", poll_us);
    fprintf(stderr, "total polls:        %llu\n", (unsigned long long)total_polls);
    fprintf(stderr, "polls at 0x00:      %llu\n",
            (unsigned long long)(total_polls - total_nonzero_seen));
    fprintf(stderr, "polls non-zero:     %llu\n", (unsigned long long)total_nonzero_seen);
    fprintf(stderr, "unique src values seen (excluding 0x00):\n");
    bool any = false;
    for (int i = 1; i < 256; ++i) {
        if (seen_values[i]) {
            fprintf(stderr, "  0x%02X : %u polls", i, seen_values[i]);
            if (i == MLC_OUT_TAP) fprintf(stderr, "  (== MLC_OUT_TAP)");
            fprintf(stderr, "\n");
            any = true;
        }
    }
    if (!any) fprintf(stderr, "  (none)\n");

    close(i2c_fd);
    return 0;
}

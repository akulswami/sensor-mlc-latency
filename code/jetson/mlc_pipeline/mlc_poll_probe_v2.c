/*
 * mlc_poll_probe_v2.c
 *
 * B6 DIAGNOSTIC v2. Same as mlc_poll_probe.c but with corrected logging:
 * prints EVERY value transition (not just transitions from 0x00 to non-zero),
 * AND maintains a running histogram of all values seen.
 *
 * Why v2: the original probe's "polls_at_0" output undercounted what was
 * happening because it only logged transitions OUT of 0x00. If the chip
 * cycled through 0x00 -> 0x04 -> 0x00 -> 0x04 -> 0x00 within a tap window,
 * v1 logged it as a single TAP. v2 logs every change, so we can see the
 * actual oscillation pattern.
 *
 * Adds:
 *   - total time spent at each value (in milliseconds)
 *   - count of edges into AND out of each non-zero value
 *
 * Compile:
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_latency.h\"  -o mlc_poll_probe2_lat mlc_poll_probe_v2.c
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_accuracy.h\" -o mlc_poll_probe2_acc mlc_poll_probe_v2.c
 *
 * Run:
 *   sudo ./mlc_poll_probe2_lat --pulsed --duration 30
 *   (auto-stops after 30 sec to ensure summary always prints)
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
#error "Define MLC_CONFIG_HEADER"
#endif
#include MLC_CONFIG_HEADER

#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A
#define REG_FUNC_CFG_ACCESS  0x01
#define REG_CTRL3_C          0x12
#define REG_MLC0_SRC         0x70
#define BANK_USER       0x00
#define BANK_EMBEDDED   0x80

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
    uint8_t scratch, reg;
    reg = 0x1C; if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D; if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) return -1;
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
    if (i2c_write_reg_retry(i2c_fd, 0x0D, 0x00, 2) < 0) return -1;
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x80, 2) < 0) return -1;
    if (i2c_write_reg_retry(i2c_fd, 0x17, latched ? 0x80 : 0x00, 2) < 0) return -1;
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x00, 2) < 0) return -1;
    fprintf(stderr, "MLC ready. EMB_FUNC_LIR=%d. TAP=0x%02X NONTAP=0x%02X\n",
            latched ? 1 : 0, MLC_OUT_TAP, MLC_OUT_NONTAP);
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
static void on_alarm(int sig) { (void)sig; stop_flag = 1; }

int main(int argc, char **argv) {
    bool latched = false;
    int poll_us = -1;
    int duration_sec = 30;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--pulsed"))       latched = false;
        else if (!strcmp(argv[i], "--latched")) latched = true;
        else if (!strcmp(argv[i], "--poll-us") && i + 1 < argc) poll_us = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--duration") && i + 1 < argc) duration_sec = atoi(argv[++i]);
        else {
            fprintf(stderr, "usage: %s [--pulsed|--latched] [--poll-us N] [--duration SEC]\n", argv[0]);
            return 2;
        }
    }
    if (poll_us < 0) poll_us = latched ? 50000 : 2000;

    signal(SIGINT, on_sigint);
    signal(SIGALRM, on_alarm);
    alarm(duration_sec);

    int i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) { fprintf(stderr, "i2c open failed\n"); return 1; }
    if (configure_mlc(i2c_fd, latched) < 0) { close(i2c_fd); return 1; }

    fprintf(stderr, "\n=== %s @ %d us, max %d sec ===\n",
            latched ? "LATCHED" : "PULSED", poll_us, duration_sec);
    fprintf(stderr, "Tap with piezo on Saleae A0. Ctrl+C to stop early.\n\n");

    /* Histograms keyed by value 0x00..0xFF */
    uint64_t poll_count[256] = {0};      /* polls observed at each value */
    uint64_t edges_in[256]   = {0};      /* transitions INTO each value */

    /* Drain startup latch once */
    {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) == 0 && v != 0x00) {
            fprintf(stderr, "[startup] MLC0_SRC=0x%02X\n", v);
        }
    }

    printf("%-12s %-8s\n", "elapsed_ms", "src");

    uint64_t t0 = now_ms();
    uint8_t prev = 0xFF;  /* sentinel so first read counts as a transition */
    uint64_t total_polls = 0;
    struct timespec poll_ts = { 0, (long)poll_us * 1000L };

    while (!stop_flag) {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) < 0) {
            fprintf(stderr, "read failed: %s\n", strerror(errno));
            break;
        }
        ++total_polls;
        ++poll_count[v];
        if (v != prev) {
            ++edges_in[v];
            uint64_t dt = now_ms() - t0;
            printf("%-12llu 0x%02X\n", (unsigned long long)dt, v);
            fflush(stdout);
            prev = v;
        }
        nanosleep(&poll_ts, NULL);
    }

    /* SUMMARY */
    fprintf(stderr, "\n=== SUMMARY ===\n");
    fprintf(stderr, "mode:               %s\n", latched ? "LATCHED" : "PULSED");
    fprintf(stderr, "poll interval:      %d us\n", poll_us);
    fprintf(stderr, "total polls:        %llu\n", (unsigned long long)total_polls);
    double poll_sec = (double)poll_us / 1e6;
    fprintf(stderr, "approx wall time:   %.2f sec\n", total_polls * poll_sec);
    fprintf(stderr, "\nValue histogram (sorted by frequency):\n");
    fprintf(stderr, "  %-6s %-12s %-12s %-10s\n", "value", "polls", "approx_ms", "edges_in");
    /* Sort indices by poll_count desc */
    int idx[256]; for (int i=0;i<256;++i) idx[i]=i;
    for (int i=0;i<256;++i) for (int j=i+1;j<256;++j)
        if (poll_count[idx[j]] > poll_count[idx[i]]) { int t=idx[i]; idx[i]=idx[j]; idx[j]=t; }
    for (int i = 0; i < 256; ++i) {
        int v = idx[i];
        if (poll_count[v] == 0) break;
        fprintf(stderr, "  0x%02X   %-12llu %-12.1f %-10llu",
                v, (unsigned long long)poll_count[v],
                poll_count[v] * poll_sec * 1000.0,
                (unsigned long long)edges_in[v]);
        if (v == MLC_OUT_TAP) fprintf(stderr, "  <-- TAP class");
        else if (v == MLC_OUT_NONTAP) fprintf(stderr, "  <-- NONTAP class");
        fprintf(stderr, "\n");
    }

    close(i2c_fd);
    return 0;
}

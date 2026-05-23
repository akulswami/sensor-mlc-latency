/*
 * mlc_poll_probe_v3.c
 *
 * Demo-oriented extension of mlc_poll_probe_v2.c. Same poll loop and
 * MLC0_SRC reading, but ALSO reads raw accelerometer outputs
 * (OUTX_L_A..OUTZ_H_A, 6 bytes starting at 0x28) on every poll and
 * writes a combined CSV:
 *
 *     elapsed_ms,mlc_src,ax_g,ay_g,az_g
 *
 * The CSV is written to a file specified by --csv. If no --csv is
 * given, only the transition-tracking and histogram behavior of v2
 * is preserved (stdout shows transitions, stderr shows summary).
 *
 * Why a new file vs editing v2: keeps v2 stable for latency probes
 * (no behavioral change to the existing measurement tool) while
 * adding the demo capability cleanly. Both binaries can coexist.
 *
 * Accel reading details:
 *   - Same I2C connection as the MLC0_SRC reads.
 *   - User bank (no bank switching needed for OUTX_L_A).
 *   - Done AFTER read_mlc_src() restores user bank.
 *   - Block read of 6 bytes at 0x28 (BDU=1 on the chip is set by the
 *     MLC flash sequence, so output bytes won't tear).
 *   - Conversion: raw_int16 * 0.061e-3 g/LSB at +/-2g (per LSM6DSOX
 *     datasheet table 4, matches imu_logger.c convention).
 *
 * The accel is sampled at ~500 Hz (poll rate) — over-samples the
 * 208 Hz accelerometer ODR. Same sample appears 2x-3x in the CSV
 * across consecutive poll iterations until the next chip update.
 * That's fine for a demo visualization; do NOT use this CSV as a
 * primary measurement input (use imu_logger for that).
 *
 * Compile:
 *   gcc -O2 -Wall -I../../mlc_config \
 *       -DMLC_CONFIG_HEADER=\"mlc_motion_w75.h\" \
 *       -o mlc_poll_probe3_motion mlc_poll_probe_v3.c
 *
 * Run:
 *   sudo ./mlc_poll_probe3_motion --pulsed --duration 60 --csv /tmp/demo.csv
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
#define REG_OUTX_L_A         0x28
#define REG_MLC0_SRC         0x70
#define BANK_USER       0x00
#define BANK_EMBEDDED   0x80
#define SENS_G_PER_LSB  (0.061e-3f)  /* +/-2g range */

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
static int i2c_read_block(int fd, uint8_t reg, uint8_t *buf, size_t n) {
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = (uint16_t)n, .buf = buf },
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
static int read_accel_g(int fd, float *x, float *y, float *z) {
    uint8_t raw[6];
    if (i2c_read_block(fd, REG_OUTX_L_A, raw, 6) < 0) return -1;
    int16_t rx = (int16_t)((raw[1] << 8) | raw[0]);
    int16_t ry = (int16_t)((raw[3] << 8) | raw[2]);
    int16_t rz = (int16_t)((raw[5] << 8) | raw[4]);
    *x = rx * SENS_G_PER_LSB;
    *y = ry * SENS_G_PER_LSB;
    *z = rz * SENS_G_PER_LSB;
    return 0;
}

static int configure_mlc(int i2c_fd, bool latched) {
    uint8_t scratch, reg;
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t r = read(i2c_fd, &scratch, 1); (void)r;
    }
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t r = read(i2c_fd, &scratch, 1); (void)r;
    }

    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) return -1;
    struct timespec ts1 = { 0, 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1) return -1;
    if (read(i2c_fd, &scratch, 1) != 1 || scratch != 0x6C) {
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
    fprintf(stderr, "MLC ready. EMB_FUNC_LIR=%d. MLC_OUT_STILL=0x%02X MLC_OUT_MOTION=0x%02X\n",
            latched ? 1 : 0, MLC_OUT_NONTAP, MLC_OUT_TAP);
    struct timespec ts2 = { 0, 100 * 1000 * 1000 };
    nanosleep(&ts2, NULL);
    return 0;
}

static inline uint64_t now_us(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000ULL + (uint64_t)ts.tv_nsec / 1000ULL;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }
static void on_alarm(int sig) { (void)sig; stop_flag = 1; }

int main(int argc, char **argv) {
    bool latched = false;
    int poll_us = -1;
    int duration_sec = 30;
    const char *csv_path = NULL;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--pulsed"))       latched = false;
        else if (!strcmp(argv[i], "--latched")) latched = true;
        else if (!strcmp(argv[i], "--poll-us") && i + 1 < argc) poll_us = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--duration") && i + 1 < argc) duration_sec = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--csv") && i + 1 < argc) csv_path = argv[++i];
        else {
            fprintf(stderr, "usage: %s [--pulsed|--latched] [--poll-us N] "
                    "[--duration SEC] [--csv PATH]\n", argv[0]);
            return 2;
        }
    }
    if (poll_us < 0) poll_us = latched ? 50000 : 2000;

    signal(SIGINT, on_sigint);
    signal(SIGALRM, on_alarm);
    alarm(duration_sec);

    FILE *csv_fp = NULL;
    if (csv_path) {
        csv_fp = fopen(csv_path, "w");
        if (!csv_fp) {
            fprintf(stderr, "fopen(%s): %s\n", csv_path, strerror(errno));
            return 1;
        }
        setvbuf(csv_fp, NULL, _IOLBF, 0);  /* line-buffered for crash safety */
        fprintf(csv_fp, "elapsed_ms,mlc_src,ax_g,ay_g,az_g\n");
    }

    int i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) { fprintf(stderr, "i2c open failed\n"); return 1; }
    if (configure_mlc(i2c_fd, latched) < 0) { close(i2c_fd); return 1; }

    fprintf(stderr, "\n=== %s @ %d us, max %d sec ===\n",
            latched ? "LATCHED" : "PULSED", poll_us, duration_sec);
    if (csv_path) fprintf(stderr, "Logging combined CSV to %s\n", csv_path);
    fprintf(stderr, "Ctrl+C to stop early.\n\n");

    uint64_t poll_count[256] = {0};
    uint64_t edges_in[256]   = {0};

    /* Drain startup latch once */
    {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) == 0 && v != 0x00) {
            fprintf(stderr, "[startup] MLC0_SRC=0x%02X\n", v);
        }
    }

    printf("%-12s %-8s\n", "elapsed_ms", "src");

    uint64_t t0_us = now_us();
    uint8_t prev = 0xFF;
    uint64_t total_polls = 0;
    struct timespec poll_ts = { 0, (long)poll_us * 1000L };

    while (!stop_flag) {
        uint8_t v;
        if (read_mlc_src(i2c_fd, &v) < 0) {
            fprintf(stderr, "read mlc_src failed: %s\n", strerror(errno));
            break;
        }

        float ax = 0, ay = 0, az = 0;
        if (read_accel_g(i2c_fd, &ax, &ay, &az) < 0) {
            /* Accel read failure should not kill the run — keep going
             * with zeros so the CSV doesn't get truncated. */
            ax = ay = az = 0.0f;
        }

        ++total_polls;
        ++poll_count[v];
        uint64_t dt_ms = (now_us() - t0_us) / 1000ULL;

        if (csv_fp) {
            fprintf(csv_fp, "%llu,0x%02X,%.4f,%.4f,%.4f\n",
                    (unsigned long long)dt_ms, v, ax, ay, az);
        }

        if (v != prev) {
            ++edges_in[v];
            printf("%-12llu 0x%02X\n", (unsigned long long)dt_ms, v);
            fflush(stdout);
            prev = v;
        }
        nanosleep(&poll_ts, NULL);
    }

    if (csv_fp) fclose(csv_fp);

    /* SUMMARY */
    fprintf(stderr, "\n=== SUMMARY ===\n");
    fprintf(stderr, "mode:               %s\n", latched ? "LATCHED" : "PULSED");
    fprintf(stderr, "poll interval:      %d us\n", poll_us);
    fprintf(stderr, "total polls:        %llu\n", (unsigned long long)total_polls);
    double poll_sec = (double)poll_us / 1e6;
    fprintf(stderr, "approx wall time:   %.2f sec\n", total_polls * poll_sec);
    fprintf(stderr, "\nValue histogram (sorted by frequency):\n");
    fprintf(stderr, "  %-6s %-12s %-12s %-10s\n", "value", "polls", "approx_ms", "edges_in");
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
        if (v == MLC_OUT_TAP) fprintf(stderr, "  <-- motion");
        else if (v == MLC_OUT_NONTAP) fprintf(stderr, "  <-- still");
        fprintf(stderr, "\n");
    }

    close(i2c_fd);
    return 0;
}

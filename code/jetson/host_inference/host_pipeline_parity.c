/*
 * host_pipeline_parity.c
 *
 * Live host-side parity classifier. DRDY-driven sibling of
 * replay_parity.c. Both call into parity_core to guarantee identical
 * classification on identical input.
 *
 * Structure:
 *   - configure_streaming(): puts the LSM6DSOX into 208 Hz DRDY-on-INT1
 *     streaming mode (no MLC enabled — the host does the inference).
 *   - main loop: block on INT1 rising edge, read accel via I2C, call
 *     pc_step(). When pc_step() returns a decision, track binary state
 *     (class != still). On TRANSITIONS, pulse the decision GPIO.
 *
 * The decision GPIO is toggled only on transitions (not every window),
 * matching latency_test_mlc.c lines 340+ which compare against the
 * MLC's MLC_OUT_NONTAP semantics. Wire-level latency for a given run
 * is t(D1 rising) - t(D0 rising) for the DRDY edge that produced the
 * sample completing the window whose decision flipped binary state.
 *
 * STATUS (post-refactor 2026-05-21):
 *   Hardware I/O is final. Classifier behavior is determined entirely
 *   by the tree.json passed via --tree. Before training is complete,
 *   running this with a placeholder tree.json will produce non-real
 *   decisions; do not interpret latency from such runs as the paper's
 *   number until the parity gate is cleared.
 *
 * Build:
 *   gcc -O2 -Wall -o host_pipeline_parity host_pipeline_parity.c \
 *       parity_core.c -lgpiod -lm
 * Run:
 *   sudo ./host_pipeline_parity --tree path/to/tree.json
 *
 * Saleae (must match latency_test_mlc.c for cross-comparison):
 *   D0 = Pin 15 (sensor INT1)    -- DRDY edge
 *   D1 = Pin 11 (decision GPIO)  -- host binary-state transition
 *   D2 = PCA9685 OUT0 PWM        -- ground-truth label
 */

#define _POSIX_C_SOURCE 200809L
#include "parity_core.h"

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

/* --- Hardware bindings (must match latency_test_mlc.c) --- */
#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A
#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define INT_LINE        85    /* PN.01 = pin 15 (sensor I1) */
#define DECISION_LINE   112   /* PR.04 = pin 11 (decision GPIO) */
#define CONSUMER_NAME   "sensor-mlc-latency-parity"

/* --- LSM6DSOX registers --- */
#define REG_CTRL1_XL    0x10
#define REG_CTRL3_C     0x12
#define REG_INT1_CTRL   0x0D
#define REG_OUTX_L_A    0x28

/* --- I2C helpers (verbatim from host_pipeline.c; repeated-start matters) --- */
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
    /* Repeated-start; see host_pipeline.c for the why. */
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = (uint16_t)n, .buf = buf },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}
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

    /* Drain latched interrupts. Reads are best-effort; failure is OK
     * (chip may already be silent). We consume the return value to
     * silence glibc's warn_unused_result; the value itself is
     * intentionally discarded. */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t n = read(i2c_fd, &scratch, 1); (void)n;
    }
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t n = read(i2c_fd, &scratch, 1); (void)n;
    }

    /* Software reset, with retry for first-write NAK quirk. */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "sw_reset failed. Power-cycle the sensor.\n");
        return -1;
    }
    struct timespec ts1 = { .tv_sec = 0, .tv_nsec = 50 * 1000 * 1000 };
    nanosleep(&ts1, NULL);

    /* Verify WHO_AM_I. */
    reg = 0x0F;
    if (write(i2c_fd, &reg, 1) != 1 || read(i2c_fd, &scratch, 1) != 1) {
        fprintf(stderr, "WHO_AM_I read failed: %s\n", strerror(errno));
        return -1;
    }
    if (scratch != 0x6C) {
        fprintf(stderr, "WHO_AM_I=0x%02X (expected 0x6C)\n", scratch);
        return -1;
    }

    /* 208 Hz streaming, +/-2g, no LPF2 (HP done in software to match MLC).
     * CTRL1_XL = 0x50: ODR_XL=0b0101 (208 Hz), FS_XL=0b00 (+/-2g). */
    struct { uint8_t reg, val; } cfg[] = {
        { REG_CTRL3_C,   0x44 },  /* BDU=1, IF_INC=1 */
        { REG_CTRL1_XL,  0x50 },  /* ODR 208 Hz, +/-2g, no LPF2 */
        { 0x0B,          0x80 },  /* COUNTER_BDR_REG1: dataready_pulsed=1 */
        { REG_INT1_CTRL, 0x01 },  /* INT1_DRDY_XL */
    };
    for (size_t i = 0; i < sizeof(cfg)/sizeof(cfg[0]); ++i) {
        if (i2c_write_reg_retry(i2c_fd, cfg[i].reg, cfg[i].val, 2) < 0) {
            fprintf(stderr, "config write to reg 0x%02X failed.\n", cfg[i].reg);
            return -1;
        }
    }

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

/* --- Signal handling --- */
static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

static void usage(const char *prog) {
    fprintf(stderr, "usage: sudo %s --tree path/to/tree.json\n", prog);
}

int main(int argc, char **argv) {
    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    struct gpiod_line *dec_line = NULL;
    pc_state_t cfg;
    bool cfg_inited = false;

    const char *tree_path = NULL;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--tree") && i + 1 < argc) tree_path = argv[++i];
        else { usage(argv[0]); return 2; }
    }
    if (!tree_path) { usage(argv[0]); return 2; }

    signal(SIGINT, on_sigint);

    pc_init_defaults(&cfg);
    cfg_inited = true;
    if (!pc_load_config(tree_path, &cfg)) {
        fprintf(stderr, "failed to load tree config from %s\n", tree_path);
        goto cleanup;
    }

    /* AN5259 says MLC ODR caps at 104 Hz. If the tree.json claims
     * a higher MLC_ODR, that's a misconfiguration. Warn and continue. */
    if (cfg.mlc_odr_hz > 104) {
        fprintf(stderr,
            "WARNING: tree.json specifies mlc_odr_hz=%d > 104 Hz, AN5259 cap.\n"
            "         The on-sensor MLC cannot match this rate; parity is impossible.\n",
            cfg.mlc_odr_hz);
    }

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_streaming(i2c_fd) < 0) goto cleanup;
    printf("Sensor: %d Hz DRDY streaming.\n", cfg.sensor_odr_hz);
    printf("Tree:   window=%d  mlc_odr=%d  decim=%d  features=%d  nodes=%d\n",
           cfg.window_length, cfg.mlc_odr_hz, cfg.decimation_ratio,
           cfg.n_features, cfg.n_nodes);
    printf("Class codes: still=%d  motion=%d\n", cfg.class_still, cfg.class_motion);

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

    printf("\n%-8s %-12s %-10s %-12s\n",
           "trans#", "t_int_us", "new_class", "host_dt_us");

    int     prev_binary = 0;   /* binary state: 0 = still, 1 = anything else */
    int     transition_count = 0;
    bool    warmed_up_logged = false;

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
        if (gpiod_line_event_read(int_line, &line_event) < 0) {
            fprintf(stderr, "event_read error: %s\n", strerror(errno));
            continue;
        }

        uint8_t raw[6];
        if (i2c_read_block(i2c_fd, REG_OUTX_L_A, raw, 6) < 0) {
            fprintf(stderr, "i2c read accel failed: %s\n", strerror(errno));
            continue;
        }
        int16_t rx = (int16_t)((raw[1] << 8) | raw[0]);
        int16_t ry = (int16_t)((raw[3] << 8) | raw[2]);
        int16_t rz = (int16_t)((raw[5] << 8) | raw[4]);
        float ax = rx * PC_SENS_G_PER_LSB;
        float ay = ry * PC_SENS_G_PER_LSB;
        float az = rz * PC_SENS_G_PER_LSB;

        int cls = 0;
        bool decided = pc_step(&cfg, ax, ay, az, &cls, NULL);

        if (!warmed_up_logged && pc_is_warmed_up(&cfg)) {
            warmed_up_logged = true;
            printf("Warmup complete (%llu MLC samples, %.1f ms wall).\n",
                   (unsigned long long)pc_mlc_sample_count(&cfg),
                   (float)pc_mlc_sample_count(&cfg) * 1000.0f / cfg.mlc_odr_hz);
        }

        if (!decided) continue;

        int new_binary = (cls != cfg.class_still) ? 1 : 0;
        if (new_binary != prev_binary) {
            gpiod_line_set_value(dec_line, 1);
            uint64_t t_dec_high_ns = now_ns();
            gpiod_line_set_value(dec_line, 0);

            ++transition_count;
            uint64_t host_dt_us = (t_dec_high_ns - t_int_seen_ns) / 1000ULL;
            printf("%-8d %-12llu %-10d %-12llu\n",
                   transition_count,
                   (unsigned long long)(t_int_seen_ns / 1000ULL),
                   cls,
                   (unsigned long long)host_dt_us);
            fflush(stdout);
        }
        prev_binary = new_binary;
    }

    printf("\nStopped after %d binary-state transitions (%llu sensor / %llu MLC samples).\n",
           transition_count,
           (unsigned long long)pc_sensor_sample_count(&cfg),
           (unsigned long long)pc_mlc_sample_count(&cfg));
    rc = 0;

cleanup:
    if (dec_line) gpiod_line_release(dec_line);
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    if (cfg_inited)  pc_free(&cfg);
    return rc;
}

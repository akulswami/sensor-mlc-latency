/*
 * latency_test_mlc.c
 *
 * Wire-level latency measurement of the on-sensor MLC pipeline.
 *
 * Loads an MLC configuration (header file in the format produced by
 * json_to_header.py for MEMS Studio JSON, or by st_h_to_ours.py for
 * STMicroelectronics-published reference .h files), applies it to the
 * LSM6DSOX, then waits for INT1 rising edges (MLC0_SRC change), reads
 * the MLC output, and toggles the decision GPIO on every binary state
 * transition.
 *
 * Decision rule (binary classification):
 *   The header defines MLC_OUT_NONTAP as the "negative" class code.
 *   Any other value read from MLC0_SRC is treated as a "positive" class.
 *   The decision GPIO is toggled with a brief pulse on every transition
 *   between these two binary states (NONTAP <-> any non-NONTAP). Sub-class
 *   transitions within the non-NONTAP set (e.g. 0x01 -> 0x04 in the
 *   activity-recognition config: walking -> jogging) do NOT toggle the
 *   decision GPIO, because the binary state is unchanged.
 *
 *   For the legacy custom-trained tap configs, MLC_OUT_TAP is the only
 *   non-NONTAP class, so this rule reduces to the original "tap detected"
 *   behavior.
 *
 * Compile-time selection of MLC config:
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_accuracy.h\" -o latency_test_mlc_acc latency_test_mlc.c -lgpiod
 *   gcc -O2 -Wall -DMLC_CONFIG_HEADER=\"mlc_latency.h\"  -o latency_test_mlc_lat latency_test_mlc.c -lgpiod
 *   gcc -O2 -Wall -I../../mlc_config -DMLC_CONFIG_HEADER=\"mlc_activity.h\" \
 *       -o latency_test_mlc_activity latency_test_mlc.c -lgpiod
 *
 * Runtime flags:
 *   --pulsed    EMB_FUNC_LIR=0 (default). Use for configs with INT1 pulse
 *               widths >= ~10 ms.
 *   --latched   EMB_FUNC_LIR=1. INT1 stays high until MLC0_SRC is read.
 *               See configure_mlc() for the deadlock caveat. Use only when
 *               pulsed mode cannot reliably catch the pulse.
 *
 * Saleae:
 *   D0 = Pin 15 (sensor INT1)    -- rising edge marks MLC fired
 *   D1 = Pin 11 (decision GPIO)  -- rising edge marks host binary-state decision
 *   A0 = ground truth (piezo for tap configs; experimenter label for activity)
 *
 * Optional CSV logging:
 *   --decisions-csv PATH writes one row per binary-state transition to PATH,
 *   in the same schema as replay_parity.c (--emit-transitions-only mode):
 *     window_idx,t_window_end_s,var_norm,p2p_norm,class
 *   This lets compare_decisions.py diff the host pipeline against the MLC.
 *   window_idx is the cumulative count of INT1 events (not window cadence,
 *   which the MLC does not expose). t_window_end_s is seconds since
 *   program start. var_norm and p2p_norm are written as 0.0 because the
 *   MLC does not expose feature values to the host (AN5259 §1.3); they
 *   are placeholders to keep the schema consistent with replay_parity.
 *   compare_decisions.py compares only the class column.
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

/* Configure: SW reset, verify chip, then apply the .ucf-equivalent writes.
 *
 * use_latched: if true, set EMB_FUNC_LIR=1 (latched mode). If false (default),
 * set EMB_FUNC_LIR=0 (pulsed mode).
 *
 * Latched mode caveat: in latched mode, INT1 is held high until MLC0_SRC is
 * read, which clears the latch. If the chip fires INT1 between the LIR-enable
 * write and the gpiod edge subscription, the rising edge is "in the past"
 * from gpiod's perspective and gpiod_line_event_wait() will block forever
 * waiting for the next rising edge -- which can't occur because INT1 is
 * already high. This was observed empirically with the activity-recognition
 * config: latched mode produced zero INT1 events; pulsed mode worked.
 *
 * Use pulsed mode unless the .ucf produces such short INT1 pulses that the
 * bank-switch+read cycle cannot reliably catch them (the original concern
 * for the legacy tap configs at ~9.6 ms pulse width).
 */
static int configure_mlc(int i2c_fd, bool use_latched) {
    uint8_t scratch;
    uint8_t reg;

    /* Drain any latched interrupt state from prior runs. Reads are
     * best-effort; failure is OK (chip may already be silent). Consume
     * the return value to silence glibc's warn_unused_result; the value
     * itself is intentionally discarded. Same pattern as d6bd301 in
     * host_pipeline_parity.c. */
    reg = 0x1C;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t n = read(i2c_fd, &scratch, 1); (void)n;
    }
    reg = 0x2D;
    if (write(i2c_fd, &reg, 1) == 1) {
        ssize_t n = read(i2c_fd, &scratch, 1); (void)n;
    }

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

    /* Set EMB_FUNC_LIR per use_latched parameter.
     * Per AN5273: "Latched mode can be enabled by setting the EMB_FUNC_LIR
     * bit of the PAGE_RW (17h) embedded functions register to 1."
     *
     * Pulsed (LIR=0): INT1 pulses for the configured pulse width then
     *   de-asserts. MLC0_SRC reflects the most recent classification but
     *   may be overwritten before the host reads it. For configs with
     *   wide pulse widths (e.g. 38.5 ms in the activity config) the
     *   bank-switch+read cycle reliably catches the INT before it
     *   de-asserts, and pulsed is the correct choice.
     *
     * Latched (LIR=1): INT1 stays asserted until MLC0_SRC is read. Read
     *   clears the latch. See caveat in the configure_mlc header comment;
     *   latched mode can deadlock the host if INT1 latches before gpiod
     *   begins listening for rising edges. Use only when pulse widths are
     *   too short for pulsed mode to catch reliably.
     */
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x80, 2) < 0) {  /* bank -> embedded */
        fprintf(stderr, "bank switch to embedded failed\n");
        return -1;
    }
    if (i2c_write_reg_retry(i2c_fd, 0x17, use_latched ? 0x80 : 0x00, 2) < 0) {
        fprintf(stderr, "EMB_FUNC_LIR set failed\n");
        return -1;
    }
    if (i2c_write_reg_retry(i2c_fd, 0x01, 0x00, 2) < 0) {  /* bank -> user */
        fprintf(stderr, "bank switch back to user failed\n");
        return -1;
    }
    fprintf(stderr, "EMB_FUNC_LIR = %d (%s mode).\n",
            use_latched ? 1 : 0,
            use_latched ? "latched" : "pulsed");

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

int main(int argc, char **argv) {
    int rc = 1;
    int i2c_fd = -1;
    struct gpiod_chip *chip = NULL;
    struct gpiod_line *int_line = NULL;
    struct gpiod_line *dec_line = NULL;
    bool use_latched = false;  /* default = pulsed mode */
    const char *decisions_csv_path = NULL;
    FILE *decisions_fp = NULL;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--latched")) {
            use_latched = true;
        } else if (!strcmp(argv[i], "--pulsed")) {
            use_latched = false;
        } else if (!strcmp(argv[i], "--decisions-csv") && i + 1 < argc) {
            decisions_csv_path = argv[++i];
        } else {
            fprintf(stderr,
                "usage: %s [--pulsed | --latched] [--decisions-csv PATH]\n"
                "  --pulsed   : EMB_FUNC_LIR=0 (default). INT1 pulses for the\n"
                "               configured pulse width. Use for configs with\n"
                "               INT1 pulse widths >= ~10 ms.\n"
                "  --latched  : EMB_FUNC_LIR=1. INT1 stays high until host\n"
                "               reads MLC0_SRC. WARNING: can deadlock the host\n"
                "               if INT1 latches before gpiod begins listening.\n"
                "               Use only when pulse widths are too short for\n"
                "               pulsed mode to catch reliably.\n"
                "  --decisions-csv PATH\n"
                "               Write per-transition CSV in the replay_parity\n"
                "               schema for cross-pipeline comparison with\n"
                "               compare_decisions.py. See file-level comment.\n",
                argv[0]);
            return 2;
        }
    }

    signal(SIGINT, on_sigint);

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_mlc(i2c_fd, use_latched) < 0) goto cleanup;

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

    if (decisions_csv_path) {
        decisions_fp = fopen(decisions_csv_path, "w");
        if (!decisions_fp) {
            fprintf(stderr, "open(%s) for write: %s\n",
                    decisions_csv_path, strerror(errno));
            goto cleanup;
        }
        fprintf(decisions_fp, "window_idx,t_window_end_s,var_norm,p2p_norm,class\n");
        fflush(decisions_fp);
        fprintf(stderr, "Decisions CSV: %s (rows emitted on binary-state transitions only)\n",
                decisions_csv_path);
    }

    fprintf(stderr, "Listening for MLC INT1 events. Ctrl+C to stop.\n");
    fprintf(stderr, "Saleae D0=Pin15(INT), D1=Pin11(decision), A0=ground truth.\n");
    fprintf(stderr, "Decision rule: binary state transition (0x00 vs non-zero).\n");
    fprintf(stderr, "  GPIO toggles on every transition between MLC_OUT_NONTAP\n");
    fprintf(stderr, "  and any non-NONTAP class. Sub-class transitions within\n");
    fprintf(stderr, "  the non-NONTAP set (e.g. 0x01 -> 0x04) do NOT toggle.\n");
    printf("\n%-6s %-6s %-12s %-8s %-12s\n",
           "EVENT#", "TRIAL#", "host_dt(us)", "mlc_src", "transition");

    /* Program start time: t_event_s in the decisions CSV is measured from
     * here, so successive runs are comparable (and so the first row's
     * t value reflects how long after startup the first transition fired
     * rather than CLOCK_MONOTONIC's arbitrary epoch). */
    uint64_t t_start_ns = now_ns();

    int event_count = 0;
    int trial_count = 0;
    /* Initial state assumption: probe startup typically with sensor at rest,
     * so binary state == NONTAP. First INT1 from a chip already in NONTAP
     * will be a no-toggle event; first INT1 from a chip transitioning into
     * a non-NONTAP class will trigger trial #1.
     *
     * If the chip's first reported class is non-NONTAP at startup (e.g. a
     * boot artifact), trial #1 will fire near t=0 and analysts can choose
     * to exclude it per pre-reg §11. Document any such exclusion in the
     * exclusions log; do not silently filter here. */
    bool last_motion_state = false;
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

        bool current_motion_state = (mlc_src != MLC_OUT_NONTAP);

        if (current_motion_state != last_motion_state) {
            /* Binary state changed -- this is a trial. Toggle decision GPIO
             * immediately; the rising edge on D1 is the wire-level decision
             * timestamp captured by Saleae. */
            gpiod_line_set_value(dec_line, 1);
            gpiod_line_set_value(dec_line, 0);
            uint64_t t_decided_ns = now_ns();
            ++trial_count;

            uint64_t host_dt_us = (t_decided_ns - t_int_seen_ns) / 1000;
            const char *transition = current_motion_state
                                     ? "STILL->MOTION"
                                     : "MOTION->STILL";
            printf("%-6d %-6d %-12llu 0x%02X    %-12s\n",
                   event_count, trial_count,
                   (unsigned long long)host_dt_us, mlc_src, transition);
            fflush(stdout);

            /* CSV row for parity diff. Schema mirrors replay_parity.c
             * --emit-transitions-only: window_idx, t_window_end_s,
             * var_norm, p2p_norm, class. var/p2p are 0.0 because the MLC
             * does not expose feature values to the host. window_idx is
             * the trial number (counting from 1, matching the human log
             * above). t_window_end_s is seconds since program start at
             * the moment INT1 was observed. compare_decisions.py
             * compares only the class column. */
            if (decisions_fp) {
                double t_event_s = (double)(t_int_seen_ns - t_start_ns) / 1e9;
                fprintf(decisions_fp, "%d,%.6f,0.000000e+00,0.000000e+00,%u\n",
                        trial_count, t_event_s, (unsigned)mlc_src);
                fflush(decisions_fp);
            }
            last_motion_state = current_motion_state;
        } else {
            /* INT1 fired but binary state did not change. Two cases:
             *   1. Sub-class transition within non-NONTAP set
             *      (e.g. 0x0C -> 0x04: driving -> jogging). MLC reports
             *      a state change but binary state is unchanged.
             *   2. Re-affirmation of NONTAP. Binary state unchanged.
             * Neither toggles the decision GPIO. Logged for diagnostics. */
            printf("%-6d %-6s %-12s 0x%02X    %-12s\n",
                   event_count, "-", "-", mlc_src,
                   current_motion_state ? "(still motion)" : "(still still)");
            fflush(stdout);
        }
    }

    fprintf(stderr, "\nStopped after %d INT1 events, %d binary-state-change trials.\n",
            event_count, trial_count);
    rc = 0;

cleanup:
    if (decisions_fp) fclose(decisions_fp);
    if (int_line) gpiod_line_release(int_line);
    if (dec_line) gpiod_line_release(dec_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    return rc;
}

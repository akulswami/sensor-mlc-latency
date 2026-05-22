/*
 * host_pipeline_parity.c
 *
 * Host-side parity classifier for the on-sensor LSM6DSOX MLC.
 *
 * SCAFFOLD STATUS (2026-05-21):
 *   This is the parity port required by docs/training-data-spec.md and
 *   pre-registration amendment v3 (Zenodo DOI 10.5281/zenodo.20060848).
 *   The classifier internals (window length, HP filter constants, feature
 *   formulas, and decision tree) are STUBBED until MEMS Studio training
 *   on sessions 1-3 produces the .ucf and JSON exports. Search for
 *   "PARITY_TBD" to find every spot that must be filled in.
 *
 *   This file is a FORK of host_pipeline.c (the B5 tap detector that
 *   produced the ~6.49 ms preliminary number). The infrastructure
 *   (I2C repeated-start, gpiod, decision-toggle, cooldown idiom) is
 *   inherited. The classifier task is different:
 *     host_pipeline.c       : 416 Hz, 50 ms window, per-axis P2P > 1.0g  (tap)
 *     host_pipeline_parity  : 208 Hz, {25,75,200}-sample window, norm-based
 *                             VARIANCE + PEAK_TO_PEAK + decision tree   (motion-vs-still)
 *
 * Decision contract (must mirror latency_test_mlc.c):
 *   - On every DRDY (INT1) edge, advance the window by one sample.
 *   - At every WINDOW_LEN-th sample (window boundary), compute the
 *     HP-filtered acceleration norm features and run the decision tree.
 *   - Maintain a binary state: (class != STILL).
 *   - On every TRANSITION of that binary state, pulse the decision GPIO.
 *     This mirrors the MLC's "transition between MLC_OUT_NONTAP and any
 *     other class" rule in latency_test_mlc.c:340.
 *
 * Wire-level latency definition (must match MLC harness):
 *   t(D1 rising) - t(D0 rising) for the DRDY edge that produced the
 *   sample completing the window whose decision flipped the binary state.
 *
 * Saleae setup (identical to latency_test_mlc.c):
 *   D0 = Pin 15 (sensor INT1)    -- DRDY edge
 *   D1 = Pin 11 (decision GPIO)  -- host binary-state transition
 *   D2 = PCA9685 OUT0 PWM        -- ground-truth label
 *
 * Build:
 *   gcc -O2 -Wall -o host_pipeline_parity host_pipeline_parity.c -lgpiod -lm
 * Run:
 *   sudo ./host_pipeline_parity
 *
 * Hard parity gate (per pre-reg, before main measurement campaign):
 *   For every input sample stream replayed offline, host_pipeline_parity
 *   must produce the same sequence of (timestamp, class) decisions as
 *   the on-sensor MLC. See TODO at end of file for offline-parity harness.
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

/* --- Hardware bindings (identical to host_pipeline.c and latency_test_mlc.c) --- */
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

/* Sensitivity: +/-2g range -> 0.061 mg/LSB */
#define SENS_G_PER_LSB  (0.061e-3f)

/* --- Classifier parameters (per docs/training-data-spec.md) --- */
#define ODR_HZ              208

/* PARITY_TBD: select 25 / 75 / 200 after MEMS Studio training picks
 * the winner under the depth-5 cap and validation-accuracy rule.
 * Default 75 = 360 ms @ 208 Hz, middle of the spec's candidate set. */
#define WINDOW_LEN          75

/* PARITY_TBD: high-pass cutoff. Spec says "~1 Hz, no LP". The MLC's HP
 * filter is a single-pole IIR whose coefficient is configured per-tree.
 * Once the trained .ucf is exported, copy the exact HP_COEFF from the
 * embedded function configuration (FILTER_3_CONF / MLC_FILTER block in
 * the JSON export). Until then, use a placeholder so the structure
 * compiles and the sample path is exercised end-to-end. */
#define HP_COEFF_PLACEHOLDER  (0.97f)  /* PARITY_TBD: ~3 Hz cutoff at 208 Hz, NOT FINAL */

/* Pulse width for the decision GPIO. Kept short so latency is dominated
 * by the classifier path, not the GPIO write. host_pipeline.c uses an
 * implicit two-call high/low; we keep the same pattern. */

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
    /* Repeated-start; see host_pipeline.c lines 77-80 for the why. */
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

/* --- Sensor configuration --- */
static int configure_streaming(int i2c_fd) {
    uint8_t scratch;
    uint8_t reg;

    /* Drain latched interrupts. See host_pipeline.c configure_streaming(). */
    reg = 0x1C;  if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D;  if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

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

    /* Configure for 208 Hz streaming with DRDY on INT1.
     * CTRL1_XL = 0x50: ODR_XL=0b0101 (208 Hz), FS_XL=0b00 (+/-2g),
     *                  LPF2_XL_EN=0 (bypass; HP done in software to match MLC). */
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

/* --- Feature extraction (must mirror MLC exactly post-training) --- *
 *
 * Pipeline per spec:
 *   raw triaxial (g)  ->  L2 norm  ->  HP filter (single-pole IIR)
 *                         -> windowed VARIANCE_NORM and PEAK_TO_PEAK_NORM
 *
 * PARITY_TBD list (cannot be finalized until MEMS Studio export):
 *   (1) HP filter coefficient & topology (the MLC uses a specific
 *       single-pole structure; must mirror byte-for-byte).
 *   (2) Whether VARIANCE_NORM is biased (1/N) or unbiased (1/(N-1)).
 *       ST reference: confirm against AN5259 once tree is exported.
 *   (3) Whether NORM is sqrt(x^2+y^2+z^2) or NORM_2 = (x^2+y^2+z^2).
 *       The MLC NORM block has both; the .ucf will say which.
 *   (4) Fixed-point vs float: MLC computes in int16; for parity we
 *       must verify rounding matches. Start in float for clarity,
 *       add int16 mirroring step before parity gate. */

typedef struct {
    float norm_buf[WINDOW_LEN];  /* HP-filtered norm samples */
    int   idx;
    int   filled;
    float hp_prev_in;
    float hp_prev_out;
} feat_window_t;

static void feat_init(feat_window_t *w) {
    memset(w, 0, sizeof(*w));
}

/* PARITY_TBD: replace with the exact filter topology the MLC uses.
 * Single-pole high-pass placeholder: y[n] = a*(y[n-1] + x[n] - x[n-1]) */
static float hp_step(feat_window_t *w, float x_in) {
    float y = HP_COEFF_PLACEHOLDER * (w->hp_prev_out + x_in - w->hp_prev_in);
    w->hp_prev_in = x_in;
    w->hp_prev_out = y;
    return y;
}

static void feat_push(feat_window_t *w, float ax, float ay, float az) {
    /* PARITY_TBD(3): NORM vs NORM_2. Using NORM (sqrt) as placeholder. */
    float norm = sqrtf(ax*ax + ay*ay + az*az);
    float hp = hp_step(w, norm);
    w->norm_buf[w->idx] = hp;
    w->idx = (w->idx + 1) % WINDOW_LEN;
    if (w->filled < WINDOW_LEN) w->filled++;
}

/* True iff this push completed a non-overlapping window boundary.
 * Non-overlapping windows match the MLC's default block-output cadence. */
static bool feat_window_complete(const feat_window_t *w, uint64_t sample_count) {
    return w->filled >= WINDOW_LEN && (sample_count % WINDOW_LEN) == 0;
}

static float feat_variance_norm(const feat_window_t *w) {
    /* PARITY_TBD(2): biased estimator (1/N), matches AN5259 default.
     * Confirm against trained tree before parity gate. */
    float mean = 0.0f;
    for (int i = 0; i < WINDOW_LEN; ++i) mean += w->norm_buf[i];
    mean /= (float)WINDOW_LEN;
    float ss = 0.0f;
    for (int i = 0; i < WINDOW_LEN; ++i) {
        float d = w->norm_buf[i] - mean;
        ss += d * d;
    }
    return ss / (float)WINDOW_LEN;
}

static float feat_p2p_norm(const feat_window_t *w) {
    float mn = w->norm_buf[0], mx = w->norm_buf[0];
    for (int i = 1; i < WINDOW_LEN; ++i) {
        if (w->norm_buf[i] < mn) mn = w->norm_buf[i];
        if (w->norm_buf[i] > mx) mx = w->norm_buf[i];
    }
    return mx - mn;
}

/* --- Decision tree (PARITY_TBD: populated from trained .ucf export) ---
 *
 * Class codes must match the MLC's MLC0_SRC output values exactly.
 * Per spec, two classes:
 *   STILL  = 0  (matches MLC_OUT_NONTAP convention in mlc_pipeline/)
 *   MOTION = 4  (placeholder; the actual value comes from MEMS Studio's
 *                output_value field for the motion leaf. ST trees often
 *                use 4 for the first non-zero class; verify post-training.)
 *
 * Tree structure: post-training this becomes a sequence of
 * `if (feature OP threshold) goto left else goto right`. Bit-identical
 * to the .ucf's CONF_MLC0_DT bytes after decoding. */
#define CLASS_STILL   0
#define CLASS_MOTION  4   /* PARITY_TBD: confirm from MEMS Studio export */

static uint8_t classify_stub(float var_norm, float p2p_norm) {
    /* PARITY_TBD: replace with bit-identical decoded tree.
     * Placeholder rule: motion if either feature exceeds a coarse threshold.
     * These thresholds are NOT the trained ones; they exist only so the
     * end-to-end sample-path and GPIO toggling can be exercised on the
     * bench before the real tree is available. */
    const float VAR_THR_PLACEHOLDER = 0.01f;   /* (g)^2 */
    const float P2P_THR_PLACEHOLDER = 0.30f;   /* g */
    if (var_norm > VAR_THR_PLACEHOLDER) return CLASS_MOTION;
    if (p2p_norm > P2P_THR_PLACEHOLDER) return CLASS_MOTION;
    return CLASS_STILL;
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

    i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) failed: %s\n", I2C_DEVICE, strerror(errno));
        goto cleanup;
    }
    if (configure_streaming(i2c_fd) < 0) goto cleanup;
    printf("Sensor configured: %d Hz streaming, DRDY on INT1.\n", ODR_HZ);
    printf("Classifier: parity SCAFFOLD (placeholder tree, %d-sample window).\n",
           WINDOW_LEN);
    printf("WARNING: This binary uses placeholder thresholds. Do NOT use\n"
           "         its output for accuracy or latency claims. It exists\n"
           "         to exercise the sample path end-to-end before the\n"
           "         trained tree is available.\n\n");

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

    feat_window_t fw;
    feat_init(&fw);

    uint64_t sample_count = 0;
    uint8_t  prev_class = CLASS_STILL;
    int      transition_count = 0;
    bool     warmed_up = false;

    printf("%-8s %-12s %-10s %-12s %-12s %-12s\n",
           "win#", "t_int_us", "class", "var_norm", "p2p_norm", "host_dt_us");

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
        float ax = rx * SENS_G_PER_LSB;
        float ay = ry * SENS_G_PER_LSB;
        float az = rz * SENS_G_PER_LSB;

        feat_push(&fw, ax, ay, az);
        sample_count++;

        if (!warmed_up && fw.filled >= WINDOW_LEN) {
            warmed_up = true;
            printf("Warmup complete after %llu samples (%.1f ms).\n",
                   (unsigned long long)sample_count,
                   (float)sample_count * 1000.0f / ODR_HZ);
        }

        /* Decision is emitted only at window boundaries. This matches
         * the MLC's default non-overlapping block cadence. If MEMS Studio
         * training selects an overlapping window mode, revisit. */
        if (!feat_window_complete(&fw, sample_count)) continue;

        float vn = feat_variance_norm(&fw);
        float pn = feat_p2p_norm(&fw);
        uint8_t cls = classify_stub(vn, pn);

        bool transition = (cls != prev_class);
        if (transition) {
            gpiod_line_set_value(dec_line, 1);
            uint64_t t_dec_high_ns = now_ns();
            gpiod_line_set_value(dec_line, 0);

            ++transition_count;
            uint64_t host_dt_us = (t_dec_high_ns - t_int_seen_ns) / 1000ULL;
            printf("%-8llu %-12llu %-10u %-12.6f %-12.6f %-12llu\n",
                   (unsigned long long)(sample_count / WINDOW_LEN),
                   (unsigned long long)(t_int_seen_ns / 1000ULL),
                   (unsigned)cls, vn, pn,
                   (unsigned long long)host_dt_us);
            fflush(stdout);
        }
        prev_class = cls;
    }

    printf("\nStopped after %d binary-state transitions across %llu samples\n"
           "(%llu windows).\n",
           transition_count,
           (unsigned long long)sample_count,
           (unsigned long long)(sample_count / WINDOW_LEN));
    rc = 0;

cleanup:
    if (dec_line) gpiod_line_release(dec_line);
    if (int_line) gpiod_line_release(int_line);
    if (chip)     gpiod_chip_close(chip);
    if (i2c_fd >= 0) close(i2c_fd);
    return rc;
}

/* =========================================================================
 * TODO before parity gate (not implemented in this scaffold):
 *
 * [ ] Offline-parity harness: replay an accel.csv through this classifier
 *     and through the MLC simulator in MEMS Studio (or a Python decode of
 *     the same tree), confirm bit-identical per-window class labels.
 *     Lives outside this binary; suggested path:
 *       code/jetson/host_inference/replay_parity.c
 *       code/analysis/compare_decisions.py
 *
 * [ ] Replace HP_COEFF_PLACEHOLDER with the exact coefficient from the
 *     MEMS Studio JSON export (MLC_FILTER / FILTER_3_CONF section).
 *
 * [ ] Replace classify_stub() with decoded tree from CONF_MLC0_DT bytes.
 *     decode_mlc_header.py already parses these; extend it to emit a
 *     C if-else chain.
 *
 * [ ] Decide overlapping vs non-overlapping windows. Spec is silent;
 *     MLC default is non-overlapping per AN5259. If we use overlapping
 *     for latency reasons, that's a v4 amendment.
 *
 * [ ] Verify int16-vs-float feature parity. Float is fine for the
 *     classifier itself if the threshold decisions are stable across
 *     rounding; near-threshold inputs may need int16 mirroring.
 *
 * [ ] Cooldown: MLC does not cooldown; on parity port we likely shouldn't
 *     either. host_pipeline.c's COOLDOWN_MS was a tap-detector concern.
 *     For motion-vs-still binary states, transitions are inherently
 *     rate-limited by window length, so no cooldown is needed. Removed
 *     from this scaffold intentionally; flag if reviewers question it.
 * ========================================================================= */

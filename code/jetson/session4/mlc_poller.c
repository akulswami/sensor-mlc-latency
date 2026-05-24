/*
 * mlc_poller.c
 *
 * Polls LSM6DSOX MLC0_SRC at a configurable rate, writes a CSV with
 * absolute CLOCK_MONOTONIC timestamps and the polled value.
 *
 * Assumes the MLC has ALREADY been configured by mlc_setup (or
 * equivalent). This binary performs no chip configuration: it only
 * opens i2c, selects the slave, and reads MLC0_SRC in a loop.
 *
 * Output schema:
 *   # mlc_poller v1
 *   # poll_hz = <N>
 *   # duration_sec = <N>
 *   t_monotonic_s, mlc_src
 *   1234567.890123, 0
 *   1234567.910123, 0
 *   ...
 *
 * Timestamps are absolute CLOCK_MONOTONIC seconds (i.e. seconds since
 * kernel boot, with nanosecond resolution). Two cooperating processes
 * sharing this clock can be aligned by recording both processes' first
 * sample timestamp via an external orchestrator.
 *
 * MLC0_SRC reads require a bank switch to the embedded function bank
 * (FUNC_CFG_ACCESS = 0x80), then a 1-byte read at 0x70, then a switch
 * back to user bank. Each read is ~600us at 100kHz I2C.
 *
 * Concurrent I2C access note:
 *   This binary opens /dev/i2c-7 and uses I2C_RDWR ioctls. Linux's
 *   i2c-dev driver serializes individual transactions, but the
 *   sensor's "current bank" state is NOT serialized across processes.
 *   If imu_logger or another process is concurrently reading the
 *   sensor's user-bank registers, our embedded-bank switch could
 *   corrupt their reads (they'd read embedded-bank values at the
 *   same address). VERIFY EMPIRICALLY before relying on this design
 *   in a measurement session.
 *
 * Usage:
 *   sudo ./mlc_poller --hz 50 --duration 1200 <out.csv>
 *
 * Defaults: --hz 50, --duration 60.
 *
 * Compile:
 *   gcc -O2 -Wall -o mlc_poller mlc_poller.c
 *
 * Exit:
 *   0 on success (duration reached or SIGINT/SIGTERM).
 *   1 on I/O error.
 *   2 on argv error.
 */

#define _POSIX_C_SOURCE 200809L
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/stat.h>
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

#define I2C_DEVICE           "/dev/i2c-7"
#define LSM6DSOX_ADDR        0x6A
#define REG_FUNC_CFG_ACCESS  0x01
#define REG_MLC0_SRC         0x70
#define BANK_USER            0x00
#define BANK_EMBEDDED        0x80

#define BUS_LOCK_PATH        "/tmp/lsm6dsox-bus.lock"

#define DEFAULT_HZ        50
#define DEFAULT_DURATION  60

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
static int i2c_read_reg(int fd, uint8_t reg, uint8_t *val) {
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,        .len = 1, .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD, .len = 1, .buf = val },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}

/* Cross-process I2C bus lock. Both this binary and a concurrently-
 * running imu_logger must acquire LOCK_EX before any bank-sensitive
 * sequence of i2c transactions. Without this, mlc_poller's brief
 * bank-switch to BANK_EMBEDDED can race with imu_logger's read at
 * OUTX_L_A (0x28), causing imu_logger to read whatever the embedded
 * bank exposes at 0x28 instead of accel data. */
static int bus_lock_open(void) {
    int fd = open(BUS_LOCK_PATH, O_CREAT | O_RDWR, 0666);
    if (fd < 0) {
        fprintf(stderr, "open(%s): %s\n", BUS_LOCK_PATH, strerror(errno));
    }
    return fd;
}
static int bus_lock_acquire(int fd) {
    /* LOCK_EX blocks until acquired. EINTR-safe loop. */
    while (flock(fd, LOCK_EX) < 0) {
        if (errno == EINTR) continue;
        return -1;
    }
    return 0;
}
static void bus_lock_release(int fd) {
    (void)flock(fd, LOCK_UN);
}

/* Bank-switch read of MLC0_SRC. Best-effort restore of user bank
 * even on error path so a failed poll doesn't leave the chip in
 * embedded bank for the next caller.
 *
 * Caller MUST hold bus_lock across this entire function. */
static int read_mlc_src(int fd, uint8_t *val) {
    if (i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_EMBEDDED) < 0) return -1;
    int rc = i2c_read_reg(fd, REG_MLC0_SRC, val);
    (void)i2c_write_reg(fd, REG_FUNC_CFG_ACCESS, BANK_USER);
    return rc;
}

static inline double now_monotonic_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static volatile sig_atomic_t stop_flag = 0;
static void on_signal(int sig) { (void)sig; stop_flag = 1; }

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s [--hz HZ] [--duration SEC] <out.csv>\n"
        "  --hz HZ          Poll rate in Hz. Default: %d.\n"
        "  --duration SEC   Total run time. Default: %d.\n",
        prog, DEFAULT_HZ, DEFAULT_DURATION);
}

int main(int argc, char **argv) {
    int hz = DEFAULT_HZ;
    int duration_sec = DEFAULT_DURATION;
    const char *out_path = NULL;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--hz") && i + 1 < argc) {
            hz = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--duration") && i + 1 < argc) {
            duration_sec = atoi(argv[++i]);
        } else if (argv[i][0] == '-') {
            fprintf(stderr, "Unknown flag: %s\n", argv[i]);
            usage(argv[0]);
            return 2;
        } else if (!out_path) {
            out_path = argv[i];
        } else {
            fprintf(stderr, "Unexpected positional arg: %s\n", argv[i]);
            usage(argv[0]);
            return 2;
        }
    }
    if (!out_path) { usage(argv[0]); return 2; }
    if (hz < 1 || hz > 1000) {
        fprintf(stderr, "--hz must be in [1, 1000], got %d\n", hz);
        return 2;
    }
    if (duration_sec < 1) {
        fprintf(stderr, "--duration must be >= 1, got %d\n", duration_sec);
        return 2;
    }

    signal(SIGINT,  on_signal);
    signal(SIGTERM, on_signal);

    FILE *fp = fopen(out_path, "w");
    if (!fp) {
        fprintf(stderr, "fopen(%s): %s\n", out_path, strerror(errno));
        return 1;
    }
    /* Line-buffered so each row is flushed to kernel on \n. Protects
     * against truncated last row on signal-kill. */
    setvbuf(fp, NULL, _IOLBF, 0);

    int i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) addr 0x%02X: %s\n",
                I2C_DEVICE, LSM6DSOX_ADDR, strerror(errno));
        fclose(fp);
        return 1;
    }

    int lock_fd = bus_lock_open();
    if (lock_fd < 0) {
        close(i2c_fd);
        fclose(fp);
        return 1;
    }

    /* Emit header. The leading '#' lines are not strictly part of the
     * CSV but are useful for self-documenting the file. */
    fprintf(fp, "# mlc_poller v1\n");
    fprintf(fp, "# poll_hz = %d\n", hz);
    fprintf(fp, "# duration_sec = %d\n", duration_sec);
    fprintf(fp, "t_monotonic_s, mlc_src\n");

    /* Compute sleep interval. nanosleep is wall-clock based, so the
     * loop's actual rate will drift slightly with read latency. For
     * 50Hz polling that's well below the MLC's 1.4Hz update rate, so
     * drift is harmless. If we ever push to very high poll rates,
     * switch to clock_nanosleep with TIMER_ABSTIME for jitter-free
     * cadence. */
    long period_ns = 1000000000L / (long)hz;
    struct timespec poll_ts = { 0, period_ns };

    double t_start = now_monotonic_s();
    double t_end = t_start + (double)duration_sec;

    fprintf(stderr, "mlc_poller: hz=%d, duration=%ds, out=%s\n",
            hz, duration_sec, out_path);
    fprintf(stderr, "t_start_monotonic = %.6f\n", t_start);

    uint64_t poll_count = 0;
    uint64_t read_errors = 0;
    uint8_t last_seen = 0xFF;  /* sentinel; first read always counts as transition */
    uint64_t transitions = 0;

    while (!stop_flag) {
        double t = now_monotonic_s();
        if (t >= t_end) break;

        uint8_t v;
        if (bus_lock_acquire(lock_fd) < 0) {
            fprintf(stderr, "[%.6f] bus_lock_acquire failed: %s\n",
                    t, strerror(errno));
            ++read_errors;
            nanosleep(&poll_ts, NULL);
            continue;
        }
        int rc = read_mlc_src(i2c_fd, &v);
        bus_lock_release(lock_fd);
        if (rc < 0) {
            ++read_errors;
            /* Don't bail on transient read errors; log and continue.
             * I2C bus contention with another process could cause
             * occasional EAGAIN-style failures. */
            fprintf(stderr, "[%.6f] read_mlc_src failed: %s\n",
                    t, strerror(errno));
        } else {
            fprintf(fp, "%.6f, %u\n", t, (unsigned)v);
            ++poll_count;
            if (v != last_seen) {
                ++transitions;
                last_seen = v;
            }
        }
        nanosleep(&poll_ts, NULL);
    }

    double t_done = now_monotonic_s();
    fprintf(stderr,
            "mlc_poller: done. polls=%llu, errors=%llu, transitions=%llu, "
            "elapsed=%.3fs, effective_hz=%.2f\n",
            (unsigned long long)poll_count,
            (unsigned long long)read_errors,
            (unsigned long long)transitions,
            t_done - t_start,
            (double)poll_count / (t_done - t_start));

    close(i2c_fd);
    close(lock_fd);
    fclose(fp);
    return 0;
}

/*
 * mlc_setup.c
 *
 * One-shot binary: flashes the LSM6DSOX MLC config and exits.
 * Designed for session 4's parity-capture workflow, where:
 *   - mlc_setup runs once at session start to load the trained MLC tree.
 *   - imu_logger then runs in parallel with mlc_poller, neither of
 *     which (re)configures the chip.
 *
 * Deliberate divergence from mlc_poll_probe_v2.c::configure_mlc:
 *   - DOES NOT write INT1_CTRL = 0x00 after the MLC config. The MLC
 *     config itself writes { 0x0D, 0x01 } so DRDY remains routed to
 *     INT1 (this is what imu_logger relies on).
 *   - DOES NOT explicitly set EMB_FUNC_LIR. The chip default after
 *     SW_RESET is LIR=0 (pulsed). For session 4 we capture by polling
 *     MLC0_SRC, so pulsed-vs-latched does not affect the captured
 *     values, only the INT1 wire behavior. We leave the wire behavior
 *     at default to avoid one more state-machine variable.
 *   - Does the SW_RESET dance and WHO_AM_I check from the v2 probe.
 *   - Sleeps 100ms after MLC flash to let the chip's internal state
 *     stabilize (per v2's existing nanosleep).
 *
 * Usage:
 *   sudo ./mlc_setup
 *
 * Exit: 0 on success, 1 on I/O error, 2 on argv error.
 *
 * Compile:
 *   gcc -O2 -Wall -I../../mlc_config \
 *       -DMLC_CONFIG_HEADER=\"mlc_motion_w75.h\" \
 *       -o mlc_setup mlc_setup.c
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

#ifndef MLC_CONFIG_HEADER
#error "Define MLC_CONFIG_HEADER (e.g. mlc_motion_w75.h)"
#endif
#include MLC_CONFIG_HEADER

#define I2C_DEVICE      "/dev/i2c-7"
#define LSM6DSOX_ADDR   0x6A
#define REG_CTRL3_C     0x12
#define REG_WHO_AM_I    0x0F
#define WHO_AM_I_VALUE  0x6C

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

int main(int argc, char **argv) {
    if (argc != 1) {
        fprintf(stderr, "usage: %s   (takes no args)\n", argv[0]);
        return 2;
    }

    int i2c_fd = i2c_open_and_select(I2C_DEVICE, LSM6DSOX_ADDR);
    if (i2c_fd < 0) {
        fprintf(stderr, "i2c open(%s) addr 0x%02X: %s\n",
                I2C_DEVICE, LSM6DSOX_ADDR, strerror(errno));
        return 1;
    }

    /* Drain any stale latched interrupt by reading STATUS regs.
     * Matches v2's startup dance. */
    uint8_t scratch, reg;
    reg = 0x1C; if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);
    reg = 0x2D; if (write(i2c_fd, &reg, 1) == 1) (void)read(i2c_fd, &scratch, 1);

    /* SW_RESET via CTRL3_C bit 0. Resets all registers including any
     * MLC state left from a prior run. */
    if (i2c_write_reg_retry(i2c_fd, REG_CTRL3_C, 0x01, 2) < 0) {
        fprintf(stderr, "SW_RESET write failed. Power-cycle sensor.\n");
        close(i2c_fd);
        return 1;
    }
    struct timespec ts_reset = { 0, 50 * 1000 * 1000 };
    nanosleep(&ts_reset, NULL);

    /* WHO_AM_I verifies the chip is alive on the bus and is in fact
     * an LSM6DSOX. */
    reg = REG_WHO_AM_I;
    if (write(i2c_fd, &reg, 1) != 1 ||
        read(i2c_fd, &scratch, 1) != 1 ||
        scratch != WHO_AM_I_VALUE) {
        fprintf(stderr, "WHO_AM_I check failed: got 0x%02X, expected 0x%02X\n",
                scratch, WHO_AM_I_VALUE);
        close(i2c_fd);
        return 1;
    }
    fprintf(stderr, "WHO_AM_I OK (0x%02X). Flashing %d MLC config writes...\n",
            scratch, MLC_CONFIG_LEN);

    /* Flash the trained MLC tree. This sequence configures filter,
     * features, decision tree, INT1 routing (writes 0x0D = 0x01),
     * and MLC interrupt routing on MD1_CFG (writes 0x5E = 0x02).
     * After this, both DRDY and MLC1 are routed to INT1. */
    for (size_t i = 0; i < MLC_CONFIG_LEN; ++i) {
        if (i2c_write_reg_retry(i2c_fd, MLC_CONFIG[i].reg, MLC_CONFIG[i].val, 2) < 0) {
            fprintf(stderr, "MLC config write %zu (reg 0x%02X val 0x%02X) failed\n",
                    i, MLC_CONFIG[i].reg, MLC_CONFIG[i].val);
            close(i2c_fd);
            return 1;
        }
    }

    /* DELIBERATELY NOT touching INT1_CTRL (0x0D) here.
     * MLC_CONFIG already wrote it to 0x01 (DRDY routing on bit 0).
     * mlc_poll_probe_v2.c clobbers it to 0x00 because that binary
     * doesn't want DRDY-driven INT1 jitter; we DO want DRDY-driven
     * INT1 because imu_logger uses it. */

    /* DELIBERATELY NOT setting EMB_FUNC_LIR. Chip default after
     * SW_RESET is LIR=0 (pulsed). Polling is independent of LIR
     * because we read MLC0_SRC directly. */

    /* Let MLC internal state settle before exit. The v2 probe waits
     * 100ms here for the same reason. */
    struct timespec ts_settle = { 0, 100 * 1000 * 1000 };
    nanosleep(&ts_settle, NULL);

    fprintf(stderr, "MLC ready. Classes: still=0x%02X, motion=0x%02X.\n"
                    "DRDY remains routed to INT1 (INT1_CTRL=0x01 from MLC_CONFIG).\n"
                    "EMB_FUNC_LIR=0 (chip default, pulsed).\n",
            MLC_OUT_STILL, MLC_OUT_MOTION);

    close(i2c_fd);
    return 0;
}

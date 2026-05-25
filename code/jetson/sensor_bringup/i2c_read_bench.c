/*
 * i2c_read_bench.c - measure single accel-read latency
 * Build: gcc -O2 -Wall -o /tmp/i2c_read_bench /tmp/i2c_read_bench.c
 * Run:   sudo /tmp/i2c_read_bench
 */
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>

#define I2C_DEVICE     "/dev/i2c-7"
#define LSM6DSOX_ADDR  0x6A
#define REG_OUTX_L_A   0x28
#define N_ITER         1000

static int i2c_read_block(int fd, uint8_t reg, uint8_t *buf, size_t len) {
    struct i2c_msg msgs[2] = {
        { .addr = LSM6DSOX_ADDR, .flags = 0,         .len = 1,   .buf = &reg },
        { .addr = LSM6DSOX_ADDR, .flags = I2C_M_RD,  .len = (uint16_t)len, .buf = buf },
    };
    struct i2c_rdwr_ioctl_data xfer = { .msgs = msgs, .nmsgs = 2 };
    return (ioctl(fd, I2C_RDWR, &xfer) < 0) ? -1 : 0;
}

static int cmp_u64(const void *a, const void *b) {
    uint64_t aa = *(const uint64_t *)a;
    uint64_t bb = *(const uint64_t *)b;
    if (aa < bb) return -1;
    if (aa > bb) return 1;
    return 0;
}

int main(void) {
    int fd = open(I2C_DEVICE, O_RDWR);
    if (fd < 0) { perror("open"); return 1; }
    if (ioctl(fd, I2C_SLAVE, LSM6DSOX_ADDR) < 0) { perror("ioctl I2C_SLAVE"); return 1; }

    uint64_t times[N_ITER];
    uint8_t buf[6];

    /* Warm-up */
    for (int i = 0; i < 100; i++) {
        i2c_read_block(fd, REG_OUTX_L_A, buf, 6);
    }

    /* Measured */
    for (int i = 0; i < N_ITER; i++) {
        struct timespec t0, t1;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        if (i2c_read_block(fd, REG_OUTX_L_A, buf, 6) < 0) {
            fprintf(stderr, "i2c read failed at iter %d\n", i);
            return 1;
        }
        clock_gettime(CLOCK_MONOTONIC, &t1);
        uint64_t dt_ns = (uint64_t)(t1.tv_sec - t0.tv_sec) * 1000000000ULL
                       + (uint64_t)(t1.tv_nsec - t0.tv_nsec);
        times[i] = dt_ns;
    }

    qsort(times, N_ITER, sizeof(uint64_t), cmp_u64);

    uint64_t sum = 0;
    for (int i = 0; i < N_ITER; i++) sum += times[i];

    printf("n=%d 6-byte accel reads from /dev/i2c-7 at 400 kHz:\n", N_ITER);
    printf("  min:    %lu us\n", times[0] / 1000);
    printf("  p10:    %lu us\n", times[N_ITER/10] / 1000);
    printf("  median: %lu us\n", times[N_ITER/2] / 1000);
    printf("  p90:    %lu us\n", times[N_ITER*9/10] / 1000);
    printf("  p99:    %lu us\n", times[N_ITER*99/100] / 1000);
    printf("  max:    %lu us\n", times[N_ITER-1] / 1000);
    printf("  mean:   %lu us\n", sum / N_ITER / 1000);
    printf("\nRaw nanoseconds (median):  %lu ns\n", times[N_ITER/2]);

    close(fd);
    return 0;
}

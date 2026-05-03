/*
 * gpio_squarewave.c
 *
 * B3 bring-up: prove libgpiod can toggle Jetson Pin 11 (gpiochip0, line 112,
 * label PR.04) cleanly and that the Saleae sees the result.
 *
 * Drives the line as a 100 Hz square wave for 5 seconds. After this works
 * end-to-end, the same line will be the "decision edge" toggled by the host
 * pipeline on positive classification (per pre-registration §5).
 *
 * Saleae setup:
 *   - D1 clip on Jetson Pin 11
 *   - GND clip on Jetson Pin 6 (or any GND)
 *   - Trigger: rising edge on D1
 *   - Sample rate: 25 MS/s is plenty for a 100 Hz signal
 *   - Capture window: 6 seconds
 *
 * Build:  gcc -O2 -Wall -o gpio_squarewave gpio_squarewave.c -lgpiod
 * Run:    sudo ./gpio_squarewave
 */

#include <gpiod.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>

#define GPIOCHIP_PATH "/dev/gpiochip0"
#define LINE_OFFSET   112          /* PR.04 = physical pin 11 */
#define CONSUMER_NAME "sensor-mlc-latency-squarewave"

#define HALF_PERIOD_NS (5L * 1000L * 1000L)   /* 5 ms half-period -> 100 Hz */
#define DURATION_S     5

static void sleep_ns(long ns) {
    struct timespec ts = { .tv_sec = 0, .tv_nsec = ns };
    /* nanosleep can be interrupted; ignore that for this bring-up test. */
    nanosleep(&ts, NULL);
}

int main(void) {
    struct gpiod_chip *chip;
    struct gpiod_line *line;
    int rc;

    chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) {
        fprintf(stderr, "gpiod_chip_open(%s) failed: %s\n",
                GPIOCHIP_PATH, strerror(errno));
        return 1;
    }

    line = gpiod_chip_get_line(chip, LINE_OFFSET);
    if (!line) {
        fprintf(stderr, "gpiod_chip_get_line(%d) failed: %s\n",
                LINE_OFFSET, strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }

    rc = gpiod_line_request_output(line, CONSUMER_NAME, 0);
    if (rc < 0) {
        fprintf(stderr, "gpiod_line_request_output failed: %s\n",
                strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }

    printf("Driving gpiochip0 line %d (PR.04 / pin 11) at 100 Hz for %d seconds.\n",
           LINE_OFFSET, DURATION_S);
    fflush(stdout);

    long total_half_periods = (long)DURATION_S * 2L * (1000000000L / (HALF_PERIOD_NS * 2L));
    int level = 1;
    for (long i = 0; i < total_half_periods; ++i) {
        gpiod_line_set_value(line, level);
        sleep_ns(HALF_PERIOD_NS);
        level ^= 1;
    }

    /* Leave the line low on exit. */
    gpiod_line_set_value(line, 0);
    gpiod_line_release(line);
    gpiod_chip_close(chip);

    printf("Done.\n");
    return 0;
}

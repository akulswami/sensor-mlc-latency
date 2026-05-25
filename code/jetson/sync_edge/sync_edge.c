/*
 * sync_edge.c - fire a single rising edge on Pin 11 (gpiochip0 line 112)
 * and print the CLOCK_MONOTONIC timestamp at which it was fired.
 *
 * Purpose: align the Saleae capture clock to the Jetson monotonic
 * clock for the v7 latency experiment. The orchestrator captures
 * this binary's stdout timestamp; post-capture analysis finds the
 * matching D1 rising edge in the Saleae trace and computes the
 * offset between the two clocks.
 *
 * Per pre-reg v7 Change 6 item 1 (Saleae sync-edge implementation).
 * The sync edge fires on the DECISION_LINE (Pin 11, line 112) which
 * is the same physical pin used by host_pipeline_parity.c and
 * latency_test_mlc_w75 for their decision-edge output. The sync
 * fires BEFORE either measurement binary starts, so there is no
 * GPIO ownership conflict. Post-capture analysis identifies the
 * first D1 rising edge as the sync edge and ignores it for the
 * latency analysis.
 *
 * Earlier attempts to use Pin 16 (gpiochip1 line 9 per Jetson.GPIO
 * table, friendly name PBB.01) for the sync edge failed: toggling
 * the line via gpioset and gpiod did not produce a visible edge on
 * Saleae D3 wired to physical Pin 16. The root cause was not
 * identified; the chosen workaround is to use the known-working
 * Pin 11 / line 112 / Saleae D1 path for the sync edge. See
 * docs/lab-notebook/2026-05-25.md for the discussion.
 *
 * Build:
 *   gcc -O2 -Wall -o sync_edge sync_edge.c -lgpiod
 *
 * Run (must have permission for gpiochip0; typically via sudo):
 *   sudo ./sync_edge
 *
 * Output (stdout):
 *   <monotonic_ns>
 *   where <monotonic_ns> is the CLOCK_MONOTONIC timestamp (uint64
 *   nanoseconds since some unspecified epoch) at the moment the
 *   GPIO was driven high.
 *
 * Exit code 0 on success, non-zero on any error (with stderr message).
 */

#define _POSIX_C_SOURCE 200809L
#include <gpiod.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <time.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>

#define GPIOCHIP_PATH    "/dev/gpiochip0"
#define SYNC_LINE        112       /* Pin 11 = decision GPIO, friendly name PR.04 */
#define CONSUMER_NAME    "sensor-mlc-latency-sync"

int main(void) {
    struct gpiod_chip *chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) {
        fprintf(stderr, "gpiod_chip_open failed: %s\n", strerror(errno));
        return 1;
    }

    struct gpiod_line *line = gpiod_chip_get_line(chip, SYNC_LINE);
    if (!line) {
        fprintf(stderr, "gpiod_chip_get_line(%d) failed: %s\n",
                SYNC_LINE, strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }

    /* Request as output, initial value 0 (low). */
    if (gpiod_line_request_output(line, CONSUMER_NAME, 0) < 0) {
        fprintf(stderr, "gpiod_line_request_output failed: %s\n",
                strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }

    /* Brief settle so the line is unambiguously at 0 before the edge. */
    struct timespec settle = { 0, 1 * 1000 * 1000 };  /* 1 ms */
    nanosleep(&settle, NULL);

    /* Take timestamp, then fire the rising edge as immediately as possible. */
    struct timespec t0;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    if (gpiod_line_set_value(line, 1) < 0) {
        fprintf(stderr, "gpiod_line_set_value(1) failed: %s\n",
                strerror(errno));
        gpiod_line_release(line);
        gpiod_chip_close(chip);
        return 1;
    }

    /* Print the monotonic timestamp in nanoseconds. */
    uint64_t t0_ns = (uint64_t)t0.tv_sec * 1000000000ULL
                   + (uint64_t)t0.tv_nsec;
    printf("%lu\n", t0_ns);

    /* Hold the high state briefly so the rising edge is unambiguous,
     * then bring back low to leave the line in a known state. */
    struct timespec hold = { 0, 10 * 1000 * 1000 };  /* 10 ms */
    nanosleep(&hold, NULL);
    gpiod_line_set_value(line, 0);

    gpiod_line_release(line);
    gpiod_chip_close(chip);
    return 0;
}

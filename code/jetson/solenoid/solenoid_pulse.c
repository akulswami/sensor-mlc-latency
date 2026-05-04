/*
 * solenoid_pulse.c
 *
 * Drives the solenoid trigger pin (Pin 29 = gpiochip0 line 105 = PQ.05)
 * to fire the solenoid via MOSFET gate. Saleae D2 captures the same edge.
 *
 * Usage: sudo ./solenoid_pulse [--count N] [--gap-ms M] [--pulse-width-ms W]
 *
 * Defaults: count=1, gap-ms=500, pulse-width-ms=30.
 *
 * Build: gcc -O2 -Wall -o solenoid_pulse solenoid_pulse.c -lgpiod
 */

#define _POSIX_C_SOURCE 200809L
#include <gpiod.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>
#include <signal.h>
#include <getopt.h>

#define GPIOCHIP_PATH   "/dev/gpiochip0"
#define SOLENOID_LINE   105   /* PQ.05 = Pin 29 */
#define CONSUMER_NAME   "sensor-mlc-latency-solenoid"

static volatile sig_atomic_t stop_flag = 0;
static void on_sigint(int sig) { (void)sig; stop_flag = 1; }

static void msleep(unsigned ms) {
    struct timespec ts = {
        .tv_sec  = ms / 1000,
        .tv_nsec = (long)(ms % 1000) * 1000000L,
    };
    nanosleep(&ts, NULL);
}

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: sudo %s [--count N] [--gap-ms M] [--pulse-width-ms W]\n"
        "  --count N             Number of pulses (default 1)\n"
        "  --gap-ms M            Milliseconds between pulse falling edge and next rise (default 500)\n"
        "  --pulse-width-ms W    Milliseconds the gate is held high (default 30)\n",
        prog);
}

int main(int argc, char **argv) {
    int    count       = 1;
    int    gap_ms      = 500;
    int    pulse_ms    = 30;

    static struct option long_opts[] = {
        { "count",          required_argument, 0, 'c' },
        { "gap-ms",         required_argument, 0, 'g' },
        { "pulse-width-ms", required_argument, 0, 'w' },
        { "help",           no_argument,       0, 'h' },
        { 0, 0, 0, 0 }
    };

    int opt, idx;
    while ((opt = getopt_long(argc, argv, "c:g:w:h", long_opts, &idx)) != -1) {
        switch (opt) {
            case 'c': count    = atoi(optarg); break;
            case 'g': gap_ms   = atoi(optarg); break;
            case 'w': pulse_ms = atoi(optarg); break;
            case 'h': usage(argv[0]); return 0;
            default:  usage(argv[0]); return 1;
        }
    }

    if (count < 1 || gap_ms < 0 || pulse_ms < 1) {
        fprintf(stderr, "Invalid parameter values.\n");
        usage(argv[0]);
        return 1;
    }
    if (pulse_ms > 100) {
        fprintf(stderr,
            "Refusing pulse_ms=%d > 100. Solenoid coils overheat with sustained drive.\n"
            "If you really need this, edit the source and rebuild.\n", pulse_ms);
        return 1;
    }

    signal(SIGINT, on_sigint);

    struct gpiod_chip *chip = gpiod_chip_open(GPIOCHIP_PATH);
    if (!chip) {
        fprintf(stderr, "gpiod_chip_open failed: %s\n", strerror(errno));
        return 1;
    }
    struct gpiod_line *line = gpiod_chip_get_line(chip, SOLENOID_LINE);
    if (!line) {
        fprintf(stderr, "get_line %d failed: %s\n", SOLENOID_LINE, strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }
    if (gpiod_line_request_output(line, CONSUMER_NAME, 0) < 0) {
        fprintf(stderr, "request_output failed: %s\n", strerror(errno));
        gpiod_chip_close(chip);
        return 1;
    }

    fprintf(stderr,
        "Solenoid: count=%d, pulse=%d ms, gap=%d ms. "
        "Saleae trigger: rising edge on D2.\n",
        count, pulse_ms, gap_ms);

    /* Brief settle so the user can re-arm Saleae before the first pulse. */
    msleep(500);

    int fired = 0;
    for (int i = 0; i < count && !stop_flag; ++i) {
        gpiod_line_set_value(line, 1);
        msleep(pulse_ms);
        gpiod_line_set_value(line, 0);
        ++fired;
        if (i + 1 < count) msleep(gap_ms);
    }

    gpiod_line_release(line);
    gpiod_chip_close(chip);

    fprintf(stderr, "Done. Fired %d/%d pulses.\n", fired, count);
    return 0;
}

/*
 * replay_parity.c
 *
 * Offline parity-classifier replay harness.
 *
 * Reads an accelerometer CSV (the MEMS Studio HSDataLog format used in
 * data/training/<date>/{still,motion}/accel.csv), feeds each sample
 * into the shared parity_core, and emits per-window decisions to
 * stdout.
 *
 * No I2C, no GPIO, no hardware. Pure replay. Used to clear the
 * pre-registration parity gate without needing the sensor in the loop.
 *
 * Decision tree is loaded at runtime from a small JSON file, NOT
 * compiled in. This lets one binary serve every training iteration:
 * train in MEMS Studio -> extract tree.json -> replay_parity --tree
 * tree.json --csv accel.csv. No recompile per iteration.
 *
 * Build:
 *   gcc -O2 -Wall -Wextra -o replay_parity replay_parity.c parity_core.c -lm
 *
 * Run:
 *   ./replay_parity --tree path/to/tree.json --csv path/to/accel.csv
 *                   [--window 75] [--quiet] [--header]
 *
 * Output (stdout, CSV):
 *   window_idx,t_window_end_s,var_norm,p2p_norm,class
 *
 * The companion script code/analysis/compare_decisions.py diffs two
 * output streams (e.g. replay_parity vs the on-sensor MLC log) and
 * reports first divergence and overall agreement rate.
 *
 * STATUS (2026-05-21, post-refactor): Feature math, filter math, tree
 * walk, and JSON schema live in parity_core.{c,h}, shared with
 * host_pipeline_parity.c. This file only contains CSV ingestion,
 * argument parsing, and the main loop.
 */

#define _POSIX_C_SOURCE 200809L
#include "parity_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <errno.h>

#define MAX_LINE 4096

/* ===================================================================
 * CSV ingestion.
 *
 * MEMS Studio HSDataLog format: one row per sample, columns:
 *   timestamp, ax, ay, az
 * Header line present (skipped via best-effort number-parse check on
 * the first column). Units are inferred from the first valid sample's
 * magnitude (gravity ~1000 mg if recorded in mg, ~1.0 if in g).
 * =================================================================== */

typedef struct {
    bool   units_inferred;
    bool   units_are_mg;
} csv_state_t;

static bool parse_sample_line(const char *line, csv_state_t *st,
                              double *t_s, float *ax, float *ay, float *az) {
    char buf[MAX_LINE];
    strncpy(buf, line, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';

    char *tokens[8] = {0};
    int n = 0;
    char *p = buf;
    while (*p && n < 8) {
        while (*p == ' ' || *p == '\t' || *p == ',') *p++ = '\0';
        if (!*p) break;
        tokens[n++] = p;
        while (*p && *p != ' ' && *p != '\t' && *p != ',' && *p != '\n' && *p != '\r') p++;
        if (*p) *p++ = '\0';
    }
    if (n < 4) return false;

    char *end;
    double t = strtod(tokens[0], &end); if (end == tokens[0]) return false;
    double x = strtod(tokens[1], &end); if (end == tokens[1]) return false;
    double y = strtod(tokens[2], &end); if (end == tokens[2]) return false;
    double z = strtod(tokens[3], &end); if (end == tokens[3]) return false;

    if (!st->units_inferred) {
        double mag = sqrt(x*x + y*y + z*z);
        st->units_are_mg = (mag > 5.0);
        st->units_inferred = true;
        fprintf(stderr, "inferred units: %s (first sample |a|=%.3f)\n",
                st->units_are_mg ? "mg" : "g", mag);
    }
    float scale = st->units_are_mg ? 1.0e-3f : 1.0f;

    *t_s = t;
    *ax = (float)(x * scale);
    *ay = (float)(y * scale);
    *az = (float)(z * scale);
    return true;
}

/* ===================================================================
 * Main.
 * =================================================================== */

static void usage(const char *prog) {
    fprintf(stderr,
        "usage: %s --tree path/to/tree.json --csv path/to/accel.csv\n"
        "          [--quiet] [--window N (override)]\n"
        "          [--header  (emit CSV header row)]\n"
        "          [--emit-transitions-only]\n"
        "\n"
        "Output modes (mutually exclusive in effect):\n"
        "  default                  : one row per window. Use when you want\n"
        "                             every classification decision, e.g. for\n"
        "                             feature-distribution analysis.\n"
        "  --emit-transitions-only  : one row per binary-state transition.\n"
        "                             Matches latency_test_mlc.c --decisions-csv\n"
        "                             output (the MLC only fires INT1 on output\n"
        "                             changes in pulsed mode), so this is the\n"
        "                             mode to use when feeding output to\n"
        "                             compare_decisions.py against an MLC CSV.\n"
        "                             Initial binary-state baseline is 'still'\n"
        "                             (matches latency_test_mlc.c's initial\n"
        "                             last_motion_state=false); the first\n"
        "                             motion classification emits a transition,\n"
        "                             the first still does not.\n",
        prog);
}

int main(int argc, char **argv) {
    const char *tree_path = NULL;
    const char *csv_path = NULL;
    int  window_override = 0;
    bool emit_header = false;
    bool quiet = false;
    bool transitions_only = false;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--tree") && i + 1 < argc) tree_path = argv[++i];
        else if (!strcmp(argv[i], "--csv")  && i + 1 < argc) csv_path = argv[++i];
        else if (!strcmp(argv[i], "--window") && i + 1 < argc) window_override = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--header")) emit_header = true;
        else if (!strcmp(argv[i], "--emit-transitions-only")) transitions_only = true;
        else if (!strcmp(argv[i], "--quiet"))  quiet = true;
        else { usage(argv[0]); return 2; }
    }
    if (!tree_path || !csv_path) { usage(argv[0]); return 2; }

    pc_state_t cfg;
    pc_init_defaults(&cfg);  /* allocates default window buffer */
    if (!pc_load_config(tree_path, &cfg)) {
        fprintf(stderr, "failed to load tree config from %s\n", tree_path);
        pc_free(&cfg);
        return 1;
    }

    /* Window override: reload-the-buffer path to keep this binary's
     * --window flag functional after the refactor. */
    if (window_override > 0 && window_override != cfg.window_length) {
        cfg.window_length = window_override;
        free(cfg.win_buf);
        cfg.win_buf = calloc((size_t)cfg.window_length, sizeof(float));
        if (!cfg.win_buf) {
            fprintf(stderr, "OOM on window override\n");
            return 1;
        }
    }

    if (!quiet) {
        fprintf(stderr,
            "Loaded: window=%d  sensor_odr=%d  mlc_odr=%d  decim=%d  "
            "filters=%d  features=%d  nodes=%d  still=%d  motion=%d\n",
            cfg.window_length, cfg.sensor_odr_hz, cfg.mlc_odr_hz,
            cfg.decimation_ratio, cfg.n_filters, cfg.n_features,
            cfg.n_nodes, cfg.class_still, cfg.class_motion);
    }

    FILE *fp = fopen(csv_path, "r");
    if (!fp) {
        fprintf(stderr, "open(%s): %s\n", csv_path, strerror(errno));
        pc_free(&cfg);
        return 1;
    }

    if (emit_header) {
        printf("window_idx,t_window_end_s,var_norm,p2p_norm,class\n");
    }

    csv_state_t cst = { .units_inferred = false, .units_are_mg = false };
    char line[MAX_LINE];
    uint64_t window_idx = 0;
    uint64_t emitted_rows = 0;  /* may differ from window_idx in transitions mode */
    double   last_t_s = 0.0;

    /* Transition tracking: initial baseline matches latency_test_mlc.c's
     * last_motion_state=false (binary state = still). First motion
     * classification emits a transition row; first still does not. */
    int prev_class = cfg.class_still;
    bool first_decision = true;

    /* Diagnostics: pull var_norm and p2p_norm out of the feature output
     * by their kind, since their IDs are tree-config-dependent. */
    int var_id = -1, p2p_id = -1;
    for (int i = 0; i < cfg.n_features; ++i) {
        if (cfg.features[i].kind == PC_FEAT_VARIANCE)     var_id = cfg.features[i].id;
        if (cfg.features[i].kind == PC_FEAT_PEAK_TO_PEAK) p2p_id = cfg.features[i].id;
    }

    while (fgets(line, sizeof(line), fp)) {
        double t_s; float ax, ay, az;
        if (!parse_sample_line(line, &cst, &t_s, &ax, &ay, &az)) continue;
        last_t_s = t_s;

        int cls = 0;
        float feat_out[PC_MAX_FEATURES];
        bool decided = pc_step(&cfg, ax, ay, az, &cls, feat_out);
        if (!decided) continue;

        /* Decide whether to emit this row. */
        bool emit_this = true;
        if (transitions_only) {
            /* Emit only when the class differs from the previous baseline.
             * On the very first decision, baseline is class_still — so a
             * first-decision of still does NOT emit (it confirms the
             * baseline) while first-decision of motion DOES emit. This
             * matches the MLC's behavior: latency_test_mlc.c starts with
             * last_motion_state=false and only logs a trial when the
             * binary state flips. */
            emit_this = (cls != prev_class);
            (void)first_decision;  /* reserved for future "always emit first" mode */
        }
        prev_class = cls;
        first_decision = false;

        if (emit_this) {
            float var_norm = (var_id >= 0) ? feat_out[var_id] : 0.0f;
            float p2p_norm = (p2p_id >= 0) ? feat_out[p2p_id] : 0.0f;

            printf("%llu,%.6f,%.6e,%.6e,%d\n",
                   (unsigned long long)window_idx, t_s,
                   var_norm, p2p_norm, cls);
            emitted_rows++;
        }
        window_idx++;
    }

    if (!quiet) {
        fprintf(stderr,
            "Done: %llu raw samples, %llu MLC samples (decim %d), "
            "%llu windows, %llu rows emitted, last_t=%.3fs\n",
            (unsigned long long)pc_sensor_sample_count(&cfg),
            (unsigned long long)pc_mlc_sample_count(&cfg),
            cfg.decimation_ratio,
            (unsigned long long)window_idx,
            (unsigned long long)emitted_rows,
            last_t_s);
    }

    pc_free(&cfg);
    fclose(fp);
    return 0;
}

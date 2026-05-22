/*
 * parity_core.c
 *
 * Implementation of the shared MLC parity classifier core. See
 * parity_core.h for the contract and rationale.
 *
 * This file is the result of extracting common code from
 * replay_parity.c (offline harness) and host_pipeline_parity.c (live
 * DRDY-driven binary). It is the SINGLE source of truth for: JSON
 * config schema, filter math, feature math, decimation policy, window
 * cadence, and tree-walk semantics. Both binaries link this and call
 * pc_step() per sample.
 *
 * Rationale for the pc_step() interface: the natural sample-by-sample
 * stream model matches both the CSV reader (read line, call pc_step)
 * and the DRDY interrupt handler (wake on edge, read I2C, call
 * pc_step). The caller doesn't need to know about decimation or
 * windowing — pc_step returns true only when a decision exists.
 */

#define _POSIX_C_SOURCE 200809L
#include "parity_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <ctype.h>
#include <errno.h>

/* ===================================================================
 * Lightweight JSON-ish parser.
 *
 * Same parser as replay_parity.c had inline. Strict-enough subset of
 * JSON for our stable schema (see docs/mems-studio-json-parity-
 * extraction.md). Trusted input; the upstream Python script does the
 * schema validation.
 * =================================================================== */

typedef struct {
    const char *src;
    size_t      pos;
    size_t      len;
} jp_t;

static void jp_skip_ws(jp_t *j) {
    while (j->pos < j->len) {
        char c = j->src[j->pos];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') j->pos++;
        else break;
    }
}

static bool jp_expect(jp_t *j, char c) {
    jp_skip_ws(j);
    if (j->pos < j->len && j->src[j->pos] == c) { j->pos++; return true; }
    return false;
}

static bool jp_peek(jp_t *j, char c) {
    jp_skip_ws(j);
    return j->pos < j->len && j->src[j->pos] == c;
}

static bool jp_string(jp_t *j, char *out, size_t outsz) {
    jp_skip_ws(j);
    if (j->pos >= j->len || j->src[j->pos] != '"') return false;
    j->pos++;
    size_t k = 0;
    while (j->pos < j->len && j->src[j->pos] != '"') {
        if (k + 1 < outsz) out[k++] = j->src[j->pos];
        j->pos++;
    }
    if (j->pos >= j->len) return false;
    j->pos++;
    if (outsz > 0) out[(k < outsz) ? k : outsz - 1] = '\0';
    return true;
}

static bool jp_number(jp_t *j, double *out) {
    jp_skip_ws(j);
    char *end = NULL;
    errno = 0;
    double v = strtod(j->src + j->pos, &end);
    if (end == j->src + j->pos) return false;
    j->pos = (size_t)(end - j->src);
    *out = v;
    return true;
}

static const char *jp_ident(jp_t *j, char *out, size_t outsz) {
    jp_skip_ws(j);
    size_t k = 0;
    while (j->pos < j->len && isalpha((unsigned char)j->src[j->pos])) {
        if (k + 1 < outsz) out[k++] = j->src[j->pos];
        j->pos++;
    }
    if (k == 0) return NULL;
    if (outsz > 0) out[(k < outsz) ? k : outsz - 1] = '\0';
    return out;
}

static bool jp_skip_value(jp_t *j) {
    jp_skip_ws(j);
    if (j->pos >= j->len) return false;
    char c = j->src[j->pos];
    if (c == '"') {
        char buf[8]; return jp_string(j, buf, sizeof(buf));
    } else if (c == '{' || c == '[') {
        char open = c, close = (c == '{') ? '}' : ']';
        j->pos++;
        int depth = 1;
        while (j->pos < j->len && depth > 0) {
            char ch = j->src[j->pos];
            if (ch == '"') {
                j->pos++;
                while (j->pos < j->len && j->src[j->pos] != '"') j->pos++;
                if (j->pos < j->len) j->pos++;
            } else if (ch == open) { depth++; j->pos++; }
            else if (ch == close) { depth--; j->pos++; }
            else j->pos++;
        }
        return depth == 0;
    } else if (c == '-' || (c >= '0' && c <= '9')) {
        double d; return jp_number(j, &d);
    } else if (isalpha((unsigned char)c)) {
        char buf[8]; return jp_ident(j, buf, sizeof(buf)) != NULL;
    }
    return false;
}

/* ===================================================================
 * Sub-structure parsers.
 * =================================================================== */

static bool parse_filter_obj(jp_t *j, pc_filter_t *f) {
    if (!jp_expect(j, '{')) return false;
    f->gain = 1.0f;
    f->kind = PC_FILT_NONE;
    while (!jp_peek(j, '}')) {
        char key[64];
        if (!jp_string(j, key, sizeof(key))) return false;
        if (!jp_expect(j, ':')) return false;
        if (!strcmp(key, "id")) {
            double d; if (!jp_number(j, &d)) return false; f->id = (int)d;
        } else if (!strcmp(key, "type")) {
            char val[32];
            if (!jp_string(j, val, sizeof(val))) return false;
            if (!strcmp(val, "iir1_hp")) f->kind = PC_FILT_IIR1_HP;
            else f->kind = PC_FILT_NONE;
        } else if (!strcmp(key, "b1")) { double d; if (!jp_number(j,&d)) return false; f->b1=(float)d; }
        else if (!strcmp(key, "b2"))   { double d; if (!jp_number(j,&d)) return false; f->b2=(float)d; }
        else if (!strcmp(key, "b3"))   { double d; if (!jp_number(j,&d)) return false; f->b3=(float)d; }
        else if (!strcmp(key, "a2"))   { double d; if (!jp_number(j,&d)) return false; f->a2=(float)d; }
        else if (!strcmp(key, "a3"))   { double d; if (!jp_number(j,&d)) return false; f->a3=(float)d; }
        else if (!strcmp(key, "gain")) { double d; if (!jp_number(j,&d)) return false; f->gain=(float)d; }
        else { if (!jp_skip_value(j)) return false; }
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_feature_obj(jp_t *j, pc_feature_t *fd) {
    if (!jp_expect(j, '{')) return false;
    fd->input_filter_id = -1;
    strcpy(fd->estimator, "biased");
    while (!jp_peek(j, '}')) {
        char key[64];
        if (!jp_string(j, key, sizeof(key))) return false;
        if (!jp_expect(j, ':')) return false;
        if (!strcmp(key, "id")) {
            double d; if (!jp_number(j, &d)) return false; fd->id = (int)d;
        } else if (!strcmp(key, "type")) {
            char val[32];
            if (!jp_string(j, val, sizeof(val))) return false;
            if (!strcmp(val, "variance"))      fd->kind = PC_FEAT_VARIANCE;
            else if (!strcmp(val, "peak_to_peak")) fd->kind = PC_FEAT_PEAK_TO_PEAK;
            else { fprintf(stderr, "unknown feature type: %s\n", val); return false; }
        } else if (!strcmp(key, "input_filter_id")) {
            double d; if (!jp_number(j, &d)) return false; fd->input_filter_id = (int)d;
        } else if (!strcmp(key, "estimator")) {
            if (!jp_string(j, fd->estimator, sizeof(fd->estimator))) return false;
        } else { if (!jp_skip_value(j)) return false; }
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_tree_node(jp_t *j, pc_tree_node_t *n) {
    if (!jp_expect(j, '{')) return false;
    n->is_leaf = false;
    strcpy(n->comparison, "lte");
    while (!jp_peek(j, '}')) {
        char key[64];
        if (!jp_string(j, key, sizeof(key))) return false;
        if (!jp_expect(j, ':')) return false;
        if (!strcmp(key, "node_id")) {
            double d; if (!jp_number(j,&d)) return false; n->node_id = (int)d;
        } else if (!strcmp(key, "leaf")) {
            char buf[8];
            if (jp_peek(j, 't') || jp_peek(j, 'f')) {
                jp_ident(j, buf, sizeof(buf));
                n->is_leaf = (!strcmp(buf, "true"));
            } else if (!jp_skip_value(j)) return false;
        } else if (!strcmp(key, "class")) {
            double d; if (!jp_number(j,&d)) return false; n->leaf_class = (int)d;
        } else if (!strcmp(key, "feature_id")) {
            double d; if (!jp_number(j,&d)) return false; n->feature_id = (int)d;
        } else if (!strcmp(key, "threshold")) {
            double d; if (!jp_number(j,&d)) return false; n->threshold = (float)d;
        } else if (!strcmp(key, "comparison")) {
            if (!jp_string(j, n->comparison, sizeof(n->comparison))) return false;
        } else if (!strcmp(key, "left")) {
            double d; if (!jp_number(j,&d)) return false; n->left = (int)d;
        } else if (!strcmp(key, "right")) {
            double d; if (!jp_number(j,&d)) return false; n->right = (int)d;
        } else { if (!jp_skip_value(j)) return false; }
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_class_codes(jp_t *j, pc_state_t *cfg) {
    if (!jp_expect(j, '{')) return false;
    while (!jp_peek(j, '}')) {
        char key[32];
        if (!jp_string(j, key, sizeof(key))) return false;
        if (!jp_expect(j, ':')) return false;
        double d;
        if (!jp_number(j, &d)) return false;
        if (!strcmp(key, "still"))  cfg->class_still  = (int)d;
        if (!strcmp(key, "motion")) cfg->class_motion = (int)d;
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

/* ===================================================================
 * Lifecycle.
 * =================================================================== */

void pc_init_defaults(pc_state_t *cfg) {
    memset(cfg, 0, sizeof(*cfg));
    cfg->window_length = 75;
    cfg->sensor_odr_hz = 208;
    cfg->mlc_odr_hz = 104;
    cfg->decimation_ratio = 2;
    cfg->class_still = 0;
    cfg->class_motion = 4;
    cfg->chain_filter_id = -1;
    cfg->win_buf = calloc((size_t)cfg->window_length, sizeof(float));
}

void pc_free(pc_state_t *cfg) {
    if (cfg && cfg->win_buf) {
        free(cfg->win_buf);
        cfg->win_buf = NULL;
    }
}

bool pc_load_config(const char *path, pc_state_t *cfg) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "open(%s): %s\n", path, strerror(errno)); return false; }
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (sz <= 0 || sz > 1<<20) {
        fclose(f); fprintf(stderr, "%s: bad size %ld\n", path, sz); return false;
    }
    char *buf = malloc((size_t)sz + 1);
    if (!buf) { fclose(f); return false; }
    if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
        fclose(f); free(buf); return false;
    }
    buf[sz] = '\0';
    fclose(f);

    jp_t j = { .src = buf, .pos = 0, .len = (size_t)sz };

    /* Fresh init, but defer window buffer allocation until we know
     * window_length from the JSON. */
    if (cfg->win_buf) { free(cfg->win_buf); cfg->win_buf = NULL; }
    memset(cfg, 0, sizeof(*cfg));
    cfg->window_length = 75;
    cfg->sensor_odr_hz = 208;
    cfg->mlc_odr_hz = 104;
    cfg->decimation_ratio = 2;
    cfg->class_still = 0;
    cfg->class_motion = 4;
    cfg->chain_filter_id = -1;

    if (!jp_expect(&j, '{')) { fprintf(stderr, "expected '{' at top level\n"); free(buf); return false; }
    while (!jp_peek(&j, '}')) {
        char key[64];
        if (!jp_string(&j, key, sizeof(key))) { fprintf(stderr, "expected key\n"); free(buf); return false; }
        if (!jp_expect(&j, ':')) { free(buf); return false; }

        if (!strcmp(key, "window_length")) {
            double d; if (!jp_number(&j, &d)) { free(buf); return false; }
            cfg->window_length = (int)d;
        } else if (!strcmp(key, "sensor_odr_hz")) {
            double d; if (!jp_number(&j, &d)) { free(buf); return false; }
            cfg->sensor_odr_hz = (int)d;
        } else if (!strcmp(key, "mlc_odr_hz")) {
            double d; if (!jp_number(&j, &d)) { free(buf); return false; }
            cfg->mlc_odr_hz = (int)d;
        } else if (!strcmp(key, "decimation_ratio")) {
            double d; if (!jp_number(&j, &d)) { free(buf); return false; }
            cfg->decimation_ratio = (int)d;
        } else if (!strcmp(key, "filters")) {
            if (!jp_expect(&j, '[')) { free(buf); return false; }
            while (!jp_peek(&j, ']')) {
                if (cfg->n_filters >= PC_MAX_FILTERS) {
                    fprintf(stderr, "too many filters\n"); free(buf); return false;
                }
                if (!parse_filter_obj(&j, &cfg->filters[cfg->n_filters++])) {
                    free(buf); return false;
                }
                if (jp_peek(&j, ',')) jp_expect(&j, ',');
            }
            jp_expect(&j, ']');
        } else if (!strcmp(key, "features")) {
            if (!jp_expect(&j, '[')) { free(buf); return false; }
            while (!jp_peek(&j, ']')) {
                if (cfg->n_features >= PC_MAX_FEATURES) {
                    fprintf(stderr, "too many features\n"); free(buf); return false;
                }
                if (!parse_feature_obj(&j, &cfg->features[cfg->n_features++])) {
                    free(buf); return false;
                }
                if (jp_peek(&j, ',')) jp_expect(&j, ',');
            }
            jp_expect(&j, ']');
        } else if (!strcmp(key, "tree")) {
            if (!jp_expect(&j, '[')) { free(buf); return false; }
            while (!jp_peek(&j, ']')) {
                if (cfg->n_nodes >= PC_MAX_TREE_NODES) {
                    fprintf(stderr, "too many tree nodes\n"); free(buf); return false;
                }
                if (!parse_tree_node(&j, &cfg->nodes[cfg->n_nodes++])) {
                    free(buf); return false;
                }
                if (jp_peek(&j, ',')) jp_expect(&j, ',');
            }
            jp_expect(&j, ']');
        } else if (!strcmp(key, "class_codes")) {
            if (!parse_class_codes(&j, cfg)) { free(buf); return false; }
        } else {
            if (!jp_skip_value(&j)) { free(buf); return false; }
        }
        if (jp_peek(&j, ',')) jp_expect(&j, ',');
    }
    free(buf);

    /* Allocate window buffer now that we know the size. */
    cfg->win_buf = calloc((size_t)cfg->window_length, sizeof(float));
    if (!cfg->win_buf) {
        fprintf(stderr, "out of memory for window buffer (%d samples)\n",
                cfg->window_length);
        return false;
    }

    /* Determine the filter chain anchor: features all share one filter
     * per spec; we take the first feature's input as the chain. */
    cfg->chain_filter_id = -1;
    if (cfg->n_features > 0) cfg->chain_filter_id = cfg->features[0].input_filter_id;

    return true;
}

/* ===================================================================
 * Filter and feature math.
 * =================================================================== */

static float filter_iir1_hp_step(pc_filter_t *f, float x) {
    /* AN5259 Section 1.2 transfer function convention:
     *   H(z) = (b1 + b2 z^-1) / (1 + a2 z^-1)
     * => y[n] = b1*x[n] + b2*x[n-1] - a2*y[n-1]
     * If parity fails against silicon, flip the sign of the a2 term. */
    float y = f->b1 * x + f->b2 * f->x1 - f->a2 * f->y1;
    f->x1 = x;
    f->y1 = y;
    return y * f->gain;
}

static float apply_filters(pc_state_t *cfg, int filter_id, float x) {
    if (filter_id < 0) return x;
    for (int i = 0; i < cfg->n_filters; ++i) {
        if (cfg->filters[i].id == filter_id) {
            switch (cfg->filters[i].kind) {
                case PC_FILT_IIR1_HP: return filter_iir1_hp_step(&cfg->filters[i], x);
                default: return x;
            }
        }
    }
    fprintf(stderr, "warning: filter id %d not found, passing through\n", filter_id);
    return x;
}

static void win_push(pc_state_t *cfg, float v) {
    cfg->win_buf[cfg->win_idx] = v;
    cfg->win_idx = (cfg->win_idx + 1) % cfg->window_length;
    if (cfg->win_filled < cfg->window_length) cfg->win_filled++;
}

static float feat_variance(const pc_state_t *cfg, const char *estimator) {
    if (cfg->win_filled < cfg->window_length) return 0.0f;
    double mean = 0.0;
    for (int i = 0; i < cfg->window_length; ++i) mean += cfg->win_buf[i];
    mean /= (double)cfg->window_length;
    double ss = 0.0;
    for (int i = 0; i < cfg->window_length; ++i) {
        double d = (double)cfg->win_buf[i] - mean;
        ss += d * d;
    }
    double denom = (!strcmp(estimator, "unbiased"))
                   ? (double)(cfg->window_length - 1)
                   : (double)cfg->window_length;
    return (float)(ss / denom);
}

static float feat_p2p(const pc_state_t *cfg) {
    if (cfg->win_filled < cfg->window_length) return 0.0f;
    float mn = cfg->win_buf[0], mx = cfg->win_buf[0];
    for (int i = 1; i < cfg->window_length; ++i) {
        if (cfg->win_buf[i] < mn) mn = cfg->win_buf[i];
        if (cfg->win_buf[i] > mx) mx = cfg->win_buf[i];
    }
    return mx - mn;
}

static void compute_features(pc_state_t *cfg) {
    for (int i = 0; i < cfg->n_features; ++i) {
        pc_feature_t *fd = &cfg->features[i];
        float v = 0.0f;
        switch (fd->kind) {
            case PC_FEAT_VARIANCE:     v = feat_variance(cfg, fd->estimator); break;
            case PC_FEAT_PEAK_TO_PEAK: v = feat_p2p(cfg); break;
        }
        if (fd->id >= 0 && fd->id < PC_MAX_FEATURES) cfg->feat_values[fd->id] = v;
    }
}

static int evaluate_tree(pc_state_t *cfg) {
    int current_id = 0;
    int safety = PC_MAX_TREE_NODES + 4;
    while (safety-- > 0) {
        pc_tree_node_t *n = NULL;
        for (int i = 0; i < cfg->n_nodes; ++i) {
            if (cfg->nodes[i].node_id == current_id) { n = &cfg->nodes[i]; break; }
        }
        if (!n) {
            fprintf(stderr, "tree walk: node %d not found\n", current_id);
            return -1;
        }
        if (n->is_leaf) return n->leaf_class;
        float feat_v = (n->feature_id >= 0 && n->feature_id < PC_MAX_FEATURES)
                       ? cfg->feat_values[n->feature_id] : 0.0f;
        bool go_left;
        if      (!strcmp(n->comparison, "lt"))  go_left = (feat_v <  n->threshold);
        else if (!strcmp(n->comparison, "lte")) go_left = (feat_v <= n->threshold);
        else if (!strcmp(n->comparison, "gt"))  go_left = (feat_v >  n->threshold);
        else if (!strcmp(n->comparison, "gte")) go_left = (feat_v >= n->threshold);
        else {
            fprintf(stderr, "unknown comparison: %s\n", n->comparison);
            return -1;
        }
        current_id = go_left ? n->left : n->right;
    }
    fprintf(stderr, "tree walk exceeded depth limit\n");
    return -1;
}

/* ===================================================================
 * Sample-driven main entry point.
 * =================================================================== */

bool pc_step(pc_state_t *cfg, float ax_g, float ay_g, float az_g,
             int *out_class, float *feat_out) {
    cfg->sensor_sample_count++;

    /* Decimation: drop (decim_ratio - 1) out of every decim_ratio
     * samples. Phase counter uses sensor_sample_count modulo, so the
     * MLC sees samples at indices 0, R, 2R, 3R, ... in sensor time. */
    if (cfg->decimation_ratio > 1) {
        if ((cfg->sensor_sample_count % (uint64_t)cfg->decimation_ratio) != 0) {
            return false;
        }
    }
    cfg->mlc_sample_count++;

    float norm = sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
    float filtered = apply_filters(cfg, cfg->chain_filter_id, norm);
    win_push(cfg, filtered);

    if (cfg->win_filled < cfg->window_length) return false;
    if ((cfg->mlc_sample_count % (uint64_t)cfg->window_length) != 0) return false;

    compute_features(cfg);
    int cls = evaluate_tree(cfg);
    if (out_class) *out_class = cls;
    if (feat_out) {
        for (int i = 0; i < PC_MAX_FEATURES; ++i) feat_out[i] = cfg->feat_values[i];
    }
    return true;
}

bool pc_is_warmed_up(const pc_state_t *cfg) {
    return cfg->win_filled >= cfg->window_length;
}

uint64_t pc_sensor_sample_count(const pc_state_t *cfg) {
    return cfg->sensor_sample_count;
}

uint64_t pc_mlc_sample_count(const pc_state_t *cfg) {
    return cfg->mlc_sample_count;
}

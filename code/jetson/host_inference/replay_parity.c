/*
 * replay_parity.c
 *
 * Offline parity-classifier replay harness.
 *
 * Reads an accelerometer CSV (the MEMS Studio HSDataLog format used in
 * data/training/<date>/{still,motion}/accel.csv), runs it through the
 * same feature pipeline + decision tree as host_pipeline_parity.c, and
 * emits per-window decisions to stdout (CSV).
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
 *   gcc -O2 -Wall -Wextra -o replay_parity replay_parity.c -lm
 *
 * Run:
 *   ./replay_parity --tree path/to/tree.json --csv path/to/accel.csv
 *                   [--window 75] [--quiet]
 *
 * Output (stdout, CSV):
 *   window_idx,t_window_end_s,var_norm,p2p_norm,class
 *
 * The companion script code/analysis/compare_decisions.py diffs two
 * output streams (e.g. replay_parity vs the on-sensor MLC log) and
 * reports first divergence and overall agreement rate.
 *
 * STATUS (2026-05-21): scaffold. The JSON parser supports the stable
 * schema documented in docs/mems-studio-json-parity-extraction.md
 * section "Extraction script". A minimal hand-written tree can be
 * fed in for testing before MEMS Studio training completes.
 */

#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <errno.h>
#include <ctype.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* --- Limits (generous; the LSM6DSOX itself caps trees at 256 nodes total) --- */
#define MAX_TREE_NODES   512
#define MAX_FILTERS      16
#define MAX_FEATURES     32
#define MAX_LINE         4096

/* --- Sensitivity (must match host_pipeline_parity.c) --- */
#define SENS_G_PER_LSB   (0.061e-3f)

/* ===================================================================
 * Lightweight JSON-ish parser.
 *
 * Why not a real JSON library: this binary needs to compile with only
 * libc + libm on the Jetson, no external deps. The "tree.json" schema
 * we control is small and regular; a hand-rolled scanner suffices.
 *
 * Supported grammar (subset of JSON):
 *   - whitespace: anywhere
 *   - strings: "..."   (no escapes inside; keep schema simple)
 *   - numbers: int or float, scientific notation OK
 *   - objects: { "key": value, ... }
 *   - arrays:  [ value, ... ]
 *   - true / false / null
 *
 * We do not build a full AST; we walk by callback per top-level field.
 * For the tree array we walk node by node.
 *
 * This parser does NOT validate the schema beyond what we read. Schema
 * validation lives in the Python extraction step; this binary trusts
 * the file it's given.
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

/* Read a quoted string into out, capped at outsz. */
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
    j->pos++;  /* closing quote */
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

/* Match a bareword (true/false/null). Returns the word or NULL. */
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

/* Skip a JSON value of unknown shape (for fields we don't care about). */
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
                /* skip string contents */
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

/* =================================================================== */

typedef enum {
    FEAT_VARIANCE = 1,
    FEAT_PEAK_TO_PEAK = 2,
    /* extend as needed; spec uses only these two */
} feat_kind_t;

typedef struct {
    int   id;
    feat_kind_t kind;
    int   input_filter_id;  /* -1 = raw norm; otherwise filter chain index */
    /* AN5259 leaves estimator unspecified; we record what the JSON says. */
    char  estimator[16];    /* "biased" or "unbiased" for variance */
} feature_def_t;

typedef enum {
    FILT_NONE = 0,
    FILT_IIR1_HP = 1,
    /* IIR2 / band-pass extensible later */
} filt_kind_t;

typedef struct {
    int    id;
    filt_kind_t kind;
    /* IIR1: y[n] = b1*x[n] + b2*x[n-1] - a2*y[n-1] (AN5259 sign convention) */
    float  b1, b2, b3;
    float  a2, a3;
    float  gain;
    /* state */
    float  x1, x2;
    float  y1, y2;
} filter_state_t;

typedef struct {
    int   node_id;
    bool  is_leaf;
    /* internal node */
    int   feature_id;
    float threshold;
    char  comparison[8];   /* "lt", "lte", "gt", "gte" */
    int   left;
    int   right;
    /* leaf */
    int   leaf_class;
} tree_node_t;

typedef struct {
    int             window_length;
    int             sensor_odr_hz;
    int             mlc_odr_hz;
    int             decimation_ratio;
    int             n_filters;
    filter_state_t  filters[MAX_FILTERS];
    int             n_features;
    feature_def_t   features[MAX_FEATURES];
    int             n_nodes;
    tree_node_t     nodes[MAX_TREE_NODES];
    int             class_still;
    int             class_motion;
} tree_config_t;

static void config_init(tree_config_t *cfg) {
    memset(cfg, 0, sizeof(*cfg));
    cfg->window_length = 75;     /* default if JSON omits */
    cfg->sensor_odr_hz = 208;
    cfg->mlc_odr_hz = 104;
    cfg->decimation_ratio = 2;
    cfg->class_still = 0;
    cfg->class_motion = 4;
}

/* --- JSON loaders for each sub-structure --- */

static bool parse_filter_obj(jp_t *j, filter_state_t *f) {
    if (!jp_expect(j, '{')) return false;
    f->gain = 1.0f;  /* default */
    f->kind = FILT_NONE;
    while (!jp_peek(j, '}')) {
        char key[64];
        if (!jp_string(j, key, sizeof(key))) return false;
        if (!jp_expect(j, ':')) return false;

        if (!strcmp(key, "id")) {
            double d; if (!jp_number(j, &d)) return false; f->id = (int)d;
        } else if (!strcmp(key, "type")) {
            char val[32];
            if (!jp_string(j, val, sizeof(val))) return false;
            if (!strcmp(val, "iir1_hp")) f->kind = FILT_IIR1_HP;
            else f->kind = FILT_NONE;
        } else if (!strcmp(key, "b1")) { double d; if (!jp_number(j,&d)) return false; f->b1=(float)d; }
        else if (!strcmp(key, "b2"))   { double d; if (!jp_number(j,&d)) return false; f->b2=(float)d; }
        else if (!strcmp(key, "b3"))   { double d; if (!jp_number(j,&d)) return false; f->b3=(float)d; }
        else if (!strcmp(key, "a2"))   { double d; if (!jp_number(j,&d)) return false; f->a2=(float)d; }
        else if (!strcmp(key, "a3"))   { double d; if (!jp_number(j,&d)) return false; f->a3=(float)d; }
        else if (!strcmp(key, "gain")) { double d; if (!jp_number(j,&d)) return false; f->gain=(float)d; }
        else {
            if (!jp_skip_value(j)) return false;
        }

        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_feature_obj(jp_t *j, feature_def_t *fd) {
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
            if (!strcmp(val, "variance"))      fd->kind = FEAT_VARIANCE;
            else if (!strcmp(val, "peak_to_peak")) fd->kind = FEAT_PEAK_TO_PEAK;
            else { fprintf(stderr, "unknown feature type: %s\n", val); return false; }
        } else if (!strcmp(key, "input_filter_id")) {
            double d; if (!jp_number(j, &d)) return false; fd->input_filter_id = (int)d;
        } else if (!strcmp(key, "estimator")) {
            if (!jp_string(j, fd->estimator, sizeof(fd->estimator))) return false;
        } else {
            if (!jp_skip_value(j)) return false;
        }
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_tree_node(jp_t *j, tree_node_t *n) {
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
        } else {
            if (!jp_skip_value(j)) return false;
        }
        if (jp_peek(j, ',')) jp_expect(j, ',');
    }
    return jp_expect(j, '}');
}

static bool parse_class_codes(jp_t *j, tree_config_t *cfg) {
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

static bool load_config(const char *path, tree_config_t *cfg) {
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
    config_init(cfg);

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
                if (cfg->n_filters >= MAX_FILTERS) {
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
                if (cfg->n_features >= MAX_FEATURES) {
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
                if (cfg->n_nodes >= MAX_TREE_NODES) {
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
    return true;
}

/* ===================================================================
 * Filter and feature evaluation. Must mirror host_pipeline_parity.c
 * (which currently uses a placeholder filter; this file uses the
 * actual coefficients from the JSON, so behavior may differ until
 * host_pipeline_parity.c is updated post-training).
 * =================================================================== */

static float filter_iir1_hp_step(filter_state_t *f, float x) {
    /* AN5259 IIR1 HP: y[n] = b1*x[n] + b2*x[n-1] + (-a2)*y[n-1]
     * Sign convention per AN5259 Section 1.2 transfer function:
     *   H(z) = (b1 + b2 z^-1) / (1 + a2 z^-1)
     * so y[n] = b1*x[n] + b2*x[n-1] - a2*y[n-1]. Confirm against real
     * MLC output once available; if signs disagree, flip a2 here. */
    float y = f->b1 * x + f->b2 * f->x1 - f->a2 * f->y1;
    f->x1 = x;
    f->y1 = y;
    return y * f->gain;
}

/* Apply a filter chain to a single norm sample. */
static float apply_filters(tree_config_t *cfg, int filter_id, float x) {
    if (filter_id < 0) return x;  /* raw */
    for (int i = 0; i < cfg->n_filters; ++i) {
        if (cfg->filters[i].id == filter_id) {
            switch (cfg->filters[i].kind) {
                case FILT_IIR1_HP: return filter_iir1_hp_step(&cfg->filters[i], x);
                default: return x;
            }
        }
    }
    fprintf(stderr, "warning: filter id %d not found, passing through\n", filter_id);
    return x;
}

/* Window buffer for the (filtered) norm signal. */
typedef struct {
    float *buf;
    int    cap;     /* equals window_length */
    int    idx;
    int    filled;
} norm_window_t;

static void win_init(norm_window_t *w, int cap) {
    w->buf = calloc((size_t)cap, sizeof(float));
    w->cap = cap;
    w->idx = 0;
    w->filled = 0;
}
static void win_free(norm_window_t *w) { free(w->buf); w->buf = NULL; }

static void win_push(norm_window_t *w, float v) {
    w->buf[w->idx] = v;
    w->idx = (w->idx + 1) % w->cap;
    if (w->filled < w->cap) w->filled++;
}

static float feat_variance(const norm_window_t *w, const char *estimator) {
    if (w->filled < w->cap) return 0.0f;
    double mean = 0.0;
    for (int i = 0; i < w->cap; ++i) mean += w->buf[i];
    mean /= (double)w->cap;
    double ss = 0.0;
    for (int i = 0; i < w->cap; ++i) {
        double d = (double)w->buf[i] - mean;
        ss += d * d;
    }
    double denom = (!strcmp(estimator, "unbiased")) ? (double)(w->cap - 1) : (double)w->cap;
    return (float)(ss / denom);
}

static float feat_p2p(const norm_window_t *w) {
    if (w->filled < w->cap) return 0.0f;
    float mn = w->buf[0], mx = w->buf[0];
    for (int i = 1; i < w->cap; ++i) {
        if (w->buf[i] < mn) mn = w->buf[i];
        if (w->buf[i] > mx) mx = w->buf[i];
    }
    return mx - mn;
}

/* Compute all configured features on the current window. Writes into
 * out[] indexed by feature.id. Assumes feature ids are small (< 32). */
static void compute_features(tree_config_t *cfg, norm_window_t *w, float *out) {
    /* For now, all features operate on the same filtered norm window.
     * If features need different filter chains in the future, the
     * window structure must become per-feature. Flag if needed. */
    for (int i = 0; i < cfg->n_features; ++i) {
        feature_def_t *fd = &cfg->features[i];
        float v = 0.0f;
        switch (fd->kind) {
            case FEAT_VARIANCE:     v = feat_variance(w, fd->estimator); break;
            case FEAT_PEAK_TO_PEAK: v = feat_p2p(w); break;
        }
        if (fd->id >= 0 && fd->id < 32) out[fd->id] = v;
    }
}

/* Walk the tree using the computed feature values. Returns class code. */
static int evaluate_tree(tree_config_t *cfg, const float *feat_values) {
    /* Tree assumed to start at node_id 0. Internal nodes encode child
     * pointers by node_id, not array index, so we look up. With small
     * trees (<32 nodes) linear search is fine; for bigger trees, build
     * an id->index map once after load. */
    int current_id = 0;
    int safety = MAX_TREE_NODES + 4;
    while (safety-- > 0) {
        tree_node_t *n = NULL;
        for (int i = 0; i < cfg->n_nodes; ++i) {
            if (cfg->nodes[i].node_id == current_id) { n = &cfg->nodes[i]; break; }
        }
        if (!n) {
            fprintf(stderr, "tree walk: node %d not found\n", current_id);
            return -1;
        }
        if (n->is_leaf) return n->leaf_class;
        float feat_v = (n->feature_id >= 0 && n->feature_id < 32)
                       ? feat_values[n->feature_id] : 0.0f;
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
 * CSV ingestion.
 *
 * MEMS Studio HSDataLog format (per training-data-spec.md): one row per
 * sample, columns: timestamp, ax, ay, az. Header line present. Units
 * for accel are typically [mg] in MEMS Studio output but the imu_logger
 * in this repo writes raw or [g] — we sniff this by checking magnitude.
 *
 * Robustness: skip blank lines and obvious header rows (any row whose
 * first column is not a parseable number).
 * =================================================================== */

typedef struct {
    bool   units_inferred;
    bool   units_are_mg;
} csv_state_t;

static bool parse_sample_line(const char *line, csv_state_t *st,
                              double *t_s, float *ax, float *ay, float *az) {
    /* Try comma or whitespace separated. */
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

    /* Unit inference: if first valid sample has |a| > ~5, units are mg
     * (gravity ≈ 1000 mg). If |a| < ~2, units are g. */
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
 * Main loop: read CSV, push through filter+window+tree, emit per-window
 * decisions to stdout. Non-overlapping windows match the MLC's default.
 * =================================================================== */

static void usage(const char *prog) {
    fprintf(stderr,
        "usage: %s --tree path/to/tree.json --csv path/to/accel.csv\n"
        "          [--quiet] [--window N (override)]\n"
        "          [--header  (emit CSV header row)]\n",
        prog);
}

int main(int argc, char **argv) {
    const char *tree_path = NULL;
    const char *csv_path = NULL;
    int  window_override = 0;
    bool emit_header = false;
    bool quiet = false;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--tree") && i + 1 < argc) tree_path = argv[++i];
        else if (!strcmp(argv[i], "--csv")  && i + 1 < argc) csv_path = argv[++i];
        else if (!strcmp(argv[i], "--window") && i + 1 < argc) window_override = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--header")) emit_header = true;
        else if (!strcmp(argv[i], "--quiet"))  quiet = true;
        else { usage(argv[0]); return 2; }
    }
    if (!tree_path || !csv_path) { usage(argv[0]); return 2; }

    tree_config_t cfg;
    if (!load_config(tree_path, &cfg)) {
        fprintf(stderr, "failed to load tree config from %s\n", tree_path);
        return 1;
    }
    if (window_override > 0) cfg.window_length = window_override;

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
        return 1;
    }

    norm_window_t w;
    win_init(&w, cfg.window_length);

    /* Find which filter id feeds the features. Spec: all features share
     * the same single HP filter. Take the first feature's input filter
     * as the chain anchor. */
    int chain_filter_id = -1;
    if (cfg.n_features > 0) chain_filter_id = cfg.features[0].input_filter_id;

    if (emit_header) {
        printf("window_idx,t_window_end_s,var_norm,p2p_norm,class\n");
    }

    csv_state_t cst = { .units_inferred = false, .units_are_mg = false };
    char line[MAX_LINE];
    uint64_t sample_count = 0;
    uint64_t decim_phase = 0;  /* count toward decimation */
    uint64_t mlc_sample_count = 0;
    uint64_t window_idx = 0;
    double   last_t_s = 0.0;
    float    feat_values[32];
    memset(feat_values, 0, sizeof(feat_values));

    while (fgets(line, sizeof(line), fp)) {
        double t_s; float ax, ay, az;
        if (!parse_sample_line(line, &cst, &t_s, &ax, &ay, &az)) continue;
        sample_count++;
        last_t_s = t_s;

        /* Decimate sensor -> MLC. AN5259: MLC decimates without filtering. */
        if (cfg.decimation_ratio > 1) {
            decim_phase++;
            if ((decim_phase % cfg.decimation_ratio) != 0) continue;
        }
        mlc_sample_count++;

        float norm = sqrtf(ax*ax + ay*ay + az*az);
        float filtered = apply_filters(&cfg, chain_filter_id, norm);
        win_push(&w, filtered);

        if (w.filled < w.cap) continue;
        if ((mlc_sample_count % (uint64_t)cfg.window_length) != 0) continue;

        compute_features(&cfg, &w, feat_values);
        int cls = evaluate_tree(&cfg, feat_values);

        /* Lookup the two well-known feature ids for diagnostic columns.
         * If absent (0), the column reads 0; the class is still correct. */
        float var_norm = 0.0f, p2p_norm = 0.0f;
        for (int i = 0; i < cfg.n_features; ++i) {
            if (cfg.features[i].kind == FEAT_VARIANCE)
                var_norm = feat_values[cfg.features[i].id];
            if (cfg.features[i].kind == FEAT_PEAK_TO_PEAK)
                p2p_norm = feat_values[cfg.features[i].id];
        }
        printf("%llu,%.6f,%.6e,%.6e,%d\n",
               (unsigned long long)window_idx, t_s,
               var_norm, p2p_norm, cls);
        window_idx++;
    }

    if (!quiet) {
        fprintf(stderr,
            "Done: %llu raw samples, %llu MLC samples (decim %d), %llu windows, "
            "last_t=%.3fs\n",
            (unsigned long long)sample_count,
            (unsigned long long)mlc_sample_count,
            cfg.decimation_ratio,
            (unsigned long long)window_idx, last_t_s);
    }

    win_free(&w);
    fclose(fp);
    return 0;
}

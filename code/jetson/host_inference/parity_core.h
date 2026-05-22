/*
 * parity_core.h
 *
 * Shared classifier core for the on-sensor MLC parity port.
 *
 * Owns the contract that host_pipeline_parity.c (live, DRDY-driven) and
 * replay_parity.c (offline, CSV-driven) must implement identically:
 *
 *   raw triaxial (g) -> L2 norm -> filter chain -> windowed features
 *   -> decision tree -> class code
 *
 * Both binaries call into this core; neither reimplements feature math
 * or tree-walk. That guarantees identical decisions on identical input,
 * which is the foundation of the pre-registration parity gate.
 *
 * Decimation policy:
 *   The MLC decimates sensor ODR -> MLC ODR internally (AN5259 §1.1).
 *   pc_step() implements that decimation. Callers feed every sensor
 *   sample; pc_step() returns true only when a window boundary at MLC
 *   sample cadence has been reached, with the decision in *out_class.
 *
 * Build: see binary-level Makefiles. This is a single TU, no deps
 * beyond libc + libm.
 */

#ifndef PARITY_CORE_H
#define PARITY_CORE_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Sensitivity for +/-2g range. Both binaries must use this; baking it
 * here removes the chance of one binary using a slightly different
 * conversion factor than the other. */
#define PC_SENS_G_PER_LSB  (0.061e-3f)

/* Generous limits. AN5259 caps trees at 256 nodes total across all
 * trees; we host a single tree per config, well inside the cap. */
#define PC_MAX_TREE_NODES   512
#define PC_MAX_FILTERS      16
#define PC_MAX_FEATURES     32

typedef enum {
    PC_FEAT_VARIANCE = 1,
    PC_FEAT_PEAK_TO_PEAK = 2,
    /* AN5259 lists more (mean, energy, zero-crossing, peak-detector,
     * min, max). Add as the spec demands; do not pre-implement. */
} pc_feat_kind_t;

typedef enum {
    PC_FILT_NONE = 0,
    PC_FILT_IIR1_HP = 1,
    /* IIR2 / band-pass extensible later */
} pc_filt_kind_t;

typedef struct {
    int            id;
    pc_filt_kind_t kind;
    /* AN5259 §1.2 transfer function:
     *   H(z) = (b1 + b2 z^-1 + b3 z^-2) / (1 + a2 z^-1 + a3 z^-2)
     * IIR1 uses b1, b2, a2 only (b3=a3=0). */
    float          b1, b2, b3;
    float          a2, a3;
    float          gain;
    /* state */
    float          x1, x2;
    float          y1, y2;
} pc_filter_t;

typedef struct {
    int             id;
    pc_feat_kind_t  kind;
    int             input_filter_id;  /* -1 = raw norm */
    char            estimator[16];    /* "biased" or "unbiased" (variance) */
} pc_feature_t;

typedef struct {
    int    node_id;
    bool   is_leaf;
    /* internal node */
    int    feature_id;
    float  threshold;
    char   comparison[8];   /* "lt", "lte", "gt", "gte" */
    int    left;
    int    right;
    /* leaf */
    int    leaf_class;
} pc_tree_node_t;

typedef struct {
    /* schema fields from tree.json */
    int             window_length;
    int             sensor_odr_hz;
    int             mlc_odr_hz;
    int             decimation_ratio;
    int             n_filters;
    pc_filter_t     filters[PC_MAX_FILTERS];
    int             n_features;
    pc_feature_t    features[PC_MAX_FEATURES];
    int             n_nodes;
    pc_tree_node_t  nodes[PC_MAX_TREE_NODES];
    int             class_still;
    int             class_motion;

    /* runtime state owned by core */
    float          *win_buf;       /* size == window_length */
    int             win_idx;
    int             win_filled;
    uint64_t        sensor_sample_count;  /* raw samples fed in */
    uint64_t        mlc_sample_count;     /* post-decimation samples */
    int             chain_filter_id;      /* anchor filter id for features */
    float           feat_values[PC_MAX_FEATURES];
} pc_state_t;

/* ---------- Lifecycle ---------- */

/* Initialize a config to safe defaults (window=75, sensor=208,
 * mlc=104, decim=2, classes still=0 motion=4, no filters, no features,
 * no tree). Allocates the window buffer of size window_length. Must
 * call pc_free() to release. */
void pc_init_defaults(pc_state_t *cfg);

/* Load config from a tree.json file. Allocates the window buffer.
 * Returns true on success, false with stderr message on parse error.
 * If cfg already has a window buffer, it is freed and reallocated. */
bool pc_load_config(const char *path, pc_state_t *cfg);

/* Free any resources owned by the state (currently the window buffer).
 * Safe to call multiple times. */
void pc_free(pc_state_t *cfg);

/* ---------- Sample-driven evaluation ---------- */

/* Feed one raw triaxial sample (units: g). Internally:
 *   1. Compute L2 norm.
 *   2. Apply decimation policy. Non-MLC-phase samples return false.
 *   3. Filter the norm through the configured chain.
 *   4. Push into the window buffer.
 *   5. If the window is full AND the current MLC sample is at a window
 *      boundary, compute features and evaluate the tree, write the
 *      class code into *out_class, and return true.
 *
 * Returns true if a decision was emitted this call, false otherwise.
 * If out_class is non-NULL on a true return, it receives the class.
 * If feat_out is non-NULL on a true return, the configured features
 * are copied into feat_out[] indexed by feature.id (for diagnostics). */
bool pc_step(pc_state_t *cfg, float ax_g, float ay_g, float az_g,
             int *out_class, float *feat_out);

/* ---------- Convenience accessors ---------- */

/* True if the window buffer has been filled at least once. Useful for
 * suppressing warmup-period output. */
bool pc_is_warmed_up(const pc_state_t *cfg);

/* Counters since pc_init_defaults / pc_load_config. */
uint64_t pc_sensor_sample_count(const pc_state_t *cfg);
uint64_t pc_mlc_sample_count(const pc_state_t *cfg);

#ifdef __cplusplus
}
#endif

#endif /* PARITY_CORE_H */

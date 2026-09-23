# Provenance: affinity-investigation analysis branches (2026-09-21)

Preserves the working-log record of the outcome-interpretation branches for
the R1 pt.2 scheduler-affinity investigation, quoted verbatim from the
experimenter's AI-assisted working session (chat transcript, timestamps PDT).

## The two branches, as written at 13:41 PDT, 2026-09-21

> "**The pre-registered interpretation, written down before any results
> exist** (this protects you from post-hoc rationalizing): the experiment
> now controls the *only* variable the platform permits — process placement.
> If the tri-modality collapses → scheduler placement confirmed as the
> cause. If it persists → 'process placement excluded; IRQ steering is
> unavailable on this platform (smp_affinity writes return EIO, consistent
> with chained Tegra GPIO interrupts), so IRQ placement could not be
> controlled.' That is still a systematic, honest answer to R1 pt.2 — write
> both branches in the notebook *now*."

Context at time of writing: the session's first measurement attempt
(smoke block, ~13:20 PDT) had produced zero valid trials (12/12 excluded,
`no_d1_in_window`; later traced to a pinmux fault on pin 11). No valid
latency data existed. First valid result: smoke3, ~20:47 PDT. Pinned blocks
b001-b003: 20:50-21:10. Unpinned same-session control ctrl001: later that
evening. Verdict analyzed after all blocks completed.

## What was fixed when

| Element | Fixed | Relative to data |
|---|---|---|
| Qualitative two-branch interpretation (quoted above) | 13:41 PDT | Before ALL valid data (at least 7 h) |
| Quantitative mode-collapse criterion | evening 2026-09-21 | After pinned blocks captured; before control result and before final analysis |
| Same-session unpinned control (ctrl001) | evening 2026-09-21 | Captured blind; its result selected Branch B |
| Formalization into this chain (v7.12, commit 97fb629) | ~21:37 PDT | After data collection — post-hoc formalization of pre-specified working-log criteria |

## Status

The branches are *pre-specified analysis criteria from dated working
notes*, not externally pre-registered hypotheses. Amendment v7.13 restates
this precisely and supersedes any stronger characterization in v7.12.

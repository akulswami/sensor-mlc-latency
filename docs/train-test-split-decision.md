# Train/test split decision

**Decision made:** 2026-05-22
**Held-out test session:** Session 3 (2026-05-22)
**Training sessions:** Session 1 (2026-05-20) + Session 2 (2026-05-21)

This file pre-declares the train/test split before any MEMS Studio
training has been run. The commit timestamp is the pre-registration
proof: any subsequent training results cannot have influenced this
decision because the split was committed before training began.

## Spec basis

Per `training-data-spec.md §Sessions and train/test split`:
- "Hold out one full session as the test set. The decision tree is
  trained only on the remaining sessions."
- "Random window-level splits are forbidden because windows from a
  single servo burst correlate, leaking train-into-test."

The spec does not mandate which session is held out. The rationale
below justifies the choice but is not spec-binding.

## Rationale

Session 3 was selected as held-out for three reasons, in order of
importance:

1. **Temporal-extrapolation realism.** Training on sessions 1+2 and
   testing on session 3 most closely mimics the deployment scenario:
   train on what's available, evaluate on what comes later in
   wall-clock time. Sessions 1, 2, 3 fall in calendar order.

2. **Stress test on the marginal re-mount.** Session 3's re-mount
   produced thinner orientation variance vs session 2 than session
   2's did vs session 1 (Y mean nearly unchanged; only X mean
   shifted by 12 mg; see `data/training/2026-05-22/notes.md`).
   Using session 3 as test asks: does the classifier generalize to
   a mount geometry that is close-but-not-identical to one seen in
   training? A pass is a robust positive result. A failure is also
   informative — it would suggest the classifier overfits to
   specific mount geometries rather than learning the
   motion-vs-still distinction.

3. **Putting the noisy real data in training.** Session 1's notes
   document a bench-warmup outlier pattern in the first 60 seconds
   of still data (7.1% outlier rate vs 0.06% steady-state). Keeping
   session 1 in training means the classifier learns to handle that
   noise. If session 1 were held out, the trained tree would never
   see the warmup outliers and might thus look artificially clean
   on test data that lacks them.

## What this commits us to

- Session 3 data must NOT be loaded into MEMS Studio for training.
- Validation accuracy during training is computed on a per-window
  hold-out from sessions 1+2 (MEMS Studio's internal split, not
  session 3).
- Final accuracy and the parity gate (≥90%, ≤2pp gap between host
  and on-sensor pipelines) are reported on session 3 data only.
- The trained tree is locked once training completes — no
  re-training to fit session 3 better.

## What this does NOT decide

- Window length: still to be determined empirically from MEMS
  Studio's validation accuracy across {25, 75, 200}. The window
  size is a hyperparameter, not a methodology decision; selecting
  it via held-out validation accuracy is standard practice.
- MLC_ODR: still pending; AN5259 caps at 104 Hz, spec specifies
  sensor at 208 Hz. May trigger a v4 amendment.
- Class output codes: assigned by MEMS Studio during training,
  not predetermined.

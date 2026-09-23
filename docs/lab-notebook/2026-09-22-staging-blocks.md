# Staging blocks — 2026-09-22

Standalone text blocks drafted at IEEE Sensors Letters register (tight,
technical, no filler) for manual integration into `paper/letters/` on
Friday. **No files under `paper/letters/` were touched to produce this
document.** Facts used are exactly those supplied in the drafting
request; nothing was re-derived, re-verified, or newly introduced.

---

## 1. Decimation sentence — for §III.B

> Host window and MLC window are both 721.2 ms: parity_core's pc_step
> implements a 2:1 decimation of the host sample stream, equalizing the
> two windows to a common period.

**Word count: 28**

---

## 2. Energy paragraph — CI-first framing

> Jetson platform power (VDD_CPU_GPU_CV, INA3221) differs between host
> and MLC pipelines by +31.1 mW [27.8, 34.4] at idle (p ≈ 8.4×10⁻⁹²) and
> +7.3 mW under I²C contention (p ≈ 5.5×10⁻⁸). This comparison was added
> post-hoc in response to review; per the pre-registration's standing
> rule (v7.13), it is labeled as such rather than presented as part of
> the original confirmatory design. Under CPU stress, the 95% CI spans
> [−28.8, 14.6] mW and includes zero despite p ≈ 1.4×10⁻⁸ — expected at
> this sample size, where MWU is sensitive to distributional differences
> beyond central tendency; the CI, not the p-value, is the practically
> relevant statistic here. VDD_IN replicates the idle effect at +37.3 mW
> [33.2, 41.4]. These are whole-platform measurements, not an isolated
> host-classifier-vs-MLC comparison — the sensor's own power draw is not
> separately instrumented.

**Word count: 133**

---

## 3. Graphical abstract qualifier — rewritten headline

Current title (`paper/letters/make_graphical_abstract.py`, lines 30–32):
> "Host inference is 2.1–2.3× faster than the on-sensor MLC; the I²C
> bank-switch read protocol, not classification, dominates"

Rewritten, scoped:

> On the LSM6DSOX (I²C, Jetson Orin Nano), host inference is 2.1–2.3×
> faster than the on-sensor MLC; the I²C bank-switch read protocol, not
> classification, dominates.

**Word count: 24**

---

## 4. INT1 disclosure paragraph — factual, not corrective

> The three pipelines configure INT1 differently by design. The host
> pipeline sets INT1_CTRL = 0x01 (accelerometer DRDY, 208 Hz),
> interrupting on every sample. The mlc and mlc-binary pipelines set
> INT1_CTRL = 0x00 and instead route the MLC's decision-ready signal to
> INT1 via MD1_CFG = 0x02. This asymmetry is intrinsic to each
> pipeline's decision source (raw sample vs. embedded classifier
> output).

**Word count: 60**

---

## 5. mlc-binary/i2c second-mode sentence

> The mlc-binary/i2c-contention distribution has a hidden second mode:
> median latency is 49.4 µs, but p95 reaches 246.7 µs, indicating a
> secondary high-latency population not captured by the median alone.

**Word count: 29**

---

## 6. Compressed decomposition-caveat paragraph

Source (`paper/journal/08-section-VI-discussion.md`, the "We do not
present a confirmed mechanism..." paragraph): 99 words.

Compressed:

> No mechanism is confirmed. Candidates: (a) idle-state I²C
> bus-arbitration variability, (b) gpiod write-path differences by
> chardev poll state, or (c) interaction between the 706.5 ms MLC
> cadence and interrupt-arrival timing. Confirming this needs
> kernel-level ftrace instrumentation, outside this study's scope.

**Word count: 40** (≈40% of the 99-word source — close to, slightly
above, the "roughly a third" target; tightening further started
dropping one of the three candidate explanations, which the brief
asked to keep, so this was the floor while preserving all three plus
the scope boundary.)

---

## Total combined word count

28 + 81 + 24 + 60 + 29 + 40 = **262 words**

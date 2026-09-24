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

## 7. I²C-transaction-necessity expansion — for §VI.D (Limitations), R2

Addresses R2: "Clarify whether the three I²C operations are necessarily
required for every application or whether software architecture,
cached bank state, SPI access, interrupt configuration, or different
LSM6DSOX-family devices can change this overhead."

This **expands** the existing Letters §VI.D sentence rather than adding
new material from scratch — the current sentence already says: "Results
are specific to one platform, sensor IC family, bus protocol (I²C, not
SPI), ODR, and MLC configuration...SPI access in particular could
reduce the per-transaction overhead that drives our result"
(`paper/letters/08-section-VI-discussion.md:23`). The draft below is
written as a continuation of that sentence, addressing each of R2's
five named variables in turn.

Sourcing checked before drafting (per instructions, no new technical
claims beyond what these sources establish):
- **Software architecture / cached bank state:** grounded in
  `code/jetson/mlc_pipeline/latency_test_mlc.c:124-127`, the
  `read_mlc_src()` comment: *"The MLC source registers live in the
  embedded function bank, so we must switch banks, read, then switch
  back. This adds ~3 I2C transactions of overhead per read (~100-200 us
  at 400 kHz)."* This is our implementation's own choice to restore the
  user bank on every read — a software-architecture fact already in the
  codebase, not invented for this draft.
- **SPI access:** the manuscript's existing sentence already asserts
  the qualitative direction (SPI reduces per-transaction overhead). I
  found one additional grounded, dated source: `docs/pre-registration.md`
  Amendment 2026-05-01 ("Switch from SPI to I2C for sensor-host bus"),
  pre-registered *before any data collection*, which records that SPI
  was attempted on this platform and abandoned for a hardware
  bring-up failure (WHO_AM_I misreads), unrelated to performance, and
  states qualitatively that "I2C is slower than SPI for multi-byte
  reads" without a measured number. **No quantified SPI speedup exists
  anywhere in the repo — none is asserted below.**
- **Different LSM6DSOX-family devices:** grounded in the manuscript's
  own §II.A: "Successor parts (LSM6DSV16X, LSM6DSO32X) retain this
  architecture" (`paper/letters/09-section-II-background.md:5`;
  equivalent text in `paper/journal/09-section-II-background.md:5`) —
  i.e., the manuscript already states these parts share the same
  MLC + bank-switched register architecture.
- **Interrupt configuration:** **no grounded basis found.** Checked
  AN5259/datasheet mentions across `docs/` and `code/`
  (`docs/mems-studio-json-parity-extraction.md`, `docs/pre-registration.md`,
  `docs/lab-notebook/2026-05-2*.md`) and the INT1_CTRL/MD1_CFG register
  discussion already in the manuscript — nothing in the repo connects
  interrupt configuration to the bank-switch read's transaction count.
  Per instructions, this sub-point is **flagged as unaddressed**, not
  guessed at, in the draft below.

> The three-transaction bank-switch cost reflects this implementation's
> choice to restore the user bank after every MLC0_SRC read (write
> FUNC_CFG_ACCESS, read MLC0_SRC, write FUNC_CFG_ACCESS back), not an
> unconditional silicon requirement. An application that tolerates
> remaining in the embedded-function bank between reads, or that caches
> bank state and defers the switch-back until a user-bank register is
> actually needed, could avoid at least one of the three transactions;
> we did not implement or measure this variant. SPI access — attempted
> on this platform before an unrelated hardware bring-up failure led us
> to adopt I²C (pre-registration amendment, 2026-05-01) — would reduce
> the fixed per-transaction protocol overhead of I²C register reads
> generally, but we did not measure this pipeline over SPI and report
> no quantified speedup. Successor LSM6DSOX-family parts (LSM6DSV16X,
> LSM6DSO32X) retain the same MLC and bank-switched register
> architecture (§II.A), so the overhead is not specific to this part
> and should recur on those as well. We find no basis in AN5259, the
> datasheet, or our measurements for a claim that interrupt
> configuration changes this overhead, and make none.

**Word count: 174**

---

## Total combined word count

28 + 81 + 24 + 60 + 29 + 40 = **262 words** (blocks 1–6; see note on
block 2 above — this sum uses block 2's superseded 81-word count, not
its corrected 133, and was left as-is per standing instruction not to
touch other blocks). Adding block 7 (174 words): running total across
all seven staged blocks = **436 words** using the stale block-2 count,
or **488 words** using block 2's corrected 133-word count.

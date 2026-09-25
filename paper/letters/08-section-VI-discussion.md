# §VI. Discussion

## VI.A The I²C read protocol dominates wire-level latency

The headline finding, that host classification is 2.1–2.3× faster than the on-sensor MLC at idle and under I²C contention, is explained by **FIGLATENCYREF(c)**: the mlc-binary pipeline, which performs zero I²C transactions on the decision path (toggling D1 unconditionally on every INT1 edge), reaches a median of 49.4 µs under contention. The mlc-minus-mlc-binary difference under identical conditions isolates the I²C read overhead at roughly 1,276 µs under contention (1,325.4 − 49.4) and 476 µs under stress. Under CPU stress, where the I²C bus itself is uncontended, the host-MLC gap narrows to 1.6× (345.0 vs 546.1 µs): the read protocol still costs 476 µs, but without concurrent bus traffic to amplify it. This cost is not the silicon's classification time; it is the bank-switch read protocol's three-transaction sequence (write FUNC_CFG_ACCESS, read MLC0_SRC, write it back) competing for bus arbitration. A measured SDA/SCL capture of this sequence for one representative trial (confirmatory block b005) is provided in the supplementary material (S4).

## VI.B Implications for safety-critical edge ML

A naive reading of "on-sensor inference is faster" would favor the MLC for low-latency safety-critical loops such as exoskeleton control [3]. Our results invert that on the wire-level latency axis: the host reaches its decision 359 µs earlier at idle, 753 µs earlier under contention, and is equivalence-null against CPU stress (H5').

The control results sharpen the practical lesson: **"stress" is not a single thing.** CPU stress is significant on energy but not latency; I²C contention is significant on latency but not classifier reliability. Bundling both into one "stress margin" mis-budgets for each.

## VI.C Multimodal distributions and decision cadence

First, the MLC pipelines are multimodal at idle (§V.B): the mlc/idle p95 of 1,780 µs is 2.6× its median, a factor that vanishes under a unimodal-Gaussian assumption. For a "worst latency observed with probability 1 − ε" specification, the upper mode, not the median, is the relevant quantity.

Second, for unsynchronized external stimuli, the observed 706.5 ms cadence (§V.C) can dominate full *stimulus-to-decision* latency at the system level. Because the MLC fires only on its internal clock boundary, an unsynchronized real-world stimulus waits a uniformly-distributed 0–706.5 ms (mean 353 ms) before the silicon can respond. This is invisible on the D0-to-D1 wire-level axis we measured but is a structural floor; the 1–2 ms wire-level differences this paper characterizes are second-order against it.

## VI.D Limitations

Results are specific to one platform, sensor IC family, bus protocol (I²C, not SPI), ODR, and MLC configuration; the structural findings should transfer to similar ARM-edge + ST-MEMS combinations — successor parts (LSM6DSV16X, LSM6DSO32X) retain the same bank-switched architecture — but require confirmation. The three-transaction bank-switch cost reflects this implementation's choice to restore the user bank after every MLC0_SRC read, not an unconditional silicon requirement: an application that caches bank state and defers the switch-back could avoid at least one transaction (not measured here). SPI access would reduce this per-transaction overhead but was not measured, so no speedup is quantified.

A pre-registered RT-scheduling (chrt+taskset) ablation was specified but not activated; pilot data suggest it could roughly halve MLC contention latency, making it the most concrete next step.

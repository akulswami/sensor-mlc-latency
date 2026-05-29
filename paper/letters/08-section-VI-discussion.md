# §VI. Discussion

## VI.A The I²C read protocol dominates wire-level latency

The headline finding, that host classification is 2.1–2.3× faster than the on-sensor MLC under every tested condition, is explained by **Fig. 1(c)**: the mlc-binary pipeline, which performs zero I²C transactions on the decision path (toggling D1 unconditionally on every INT1 edge), reaches a median of 49.4 µs under contention. The mlc-minus-mlc-binary difference under identical conditions isolates the I²C read overhead at roughly 1,276 µs under contention (1,325.4 − 49.4) and 476 µs under stress. This cost is not the silicon's classification time; it is the bank-switch read protocol's three-transaction sequence (write FUNC_CFG_ACCESS, read MLC0_SRC, write it back) competing for bus arbitration.

Two consequences follow. Any platform using the LSM6DSOX MLC over I²C inherits this overhead by construction: the bank-switch protocol is neither optional nor bypassable on the standard read path. And the overhead scales with bus contention, not classifier complexity: a deeper decision tree would not change the per-decision I²C cost, but a busier bus would. The host-MLC gap is overwhelmingly a bus-protocol artifact, not a classifier-architecture one.

## VI.B Implications for safety-critical edge ML

A naive reading of "on-sensor inference is faster" would favor the MLC for low-latency safety-critical loops such as exoskeleton control [3]. Our results invert that on the wire-level latency axis: the host reaches its decision 359 µs earlier at idle, 753 µs earlier under contention, and is equivalence-null against CPU stress (H5').

The control results sharpen the practical lesson: **"stress" is not a single thing.** CPU stress is significant on energy (H6', +3,420 mW) but null on host latency (H5') and on classifier reliability; I²C bus contention is significant on latency (H2', H3') but null on classifier reliability (H7' falsified; the stable-trial rate is, if anything, slightly higher under contention). A specification bundling both into one "stress margin" over-provisions one axis while under-provisioning the other.

## VI.C Multimodal distributions and intrinsic cadence

Two secondary findings carry safety-critical weight. First, the MLC pipelines are multimodal at idle (§V.B): the mlc/idle p95 of 1,781 µs is 2.6× its median, a factor that vanishes under a unimodal-Gaussian assumption. For a "worst latency observed with probability 1 − ε" specification, the upper mode, not the median, is the relevant quantity.

Second, the 706.5 ms decision cadence (§V.C) is the dominant contributor to *stimulus-to-decision* latency at the system level. Because the MLC fires only on its internal clock boundary, an unsynchronized real-world stimulus waits a uniformly-distributed 0–706.5 ms (mean 353 ms) before the silicon can respond. This is invisible on the D0-to-D1 wire-level axis we measured but is a structural floor; the 1–2 ms wire-level differences this paper characterizes are second-order against it.

## VI.D Limitations

Results are specific to one platform, sensor IC family, bus protocol (I²C, not SPI), ODR, and MLC configuration; the structural findings should transfer to similar ARM-edge + ST-MEMS combinations but require confirmation. SPI access in particular could reduce the per-transaction overhead that drives our result. A pre-registered RT-scheduling (chrt+taskset) ablation was specified but not activated; pilot data suggest it could roughly halve MLC contention latency, making it the most concrete next step.

# Measurement protocol

*Authoritative reference for the operational parameters of the
sensor-mlc-latency experiment. This document consolidates values
that were previously scattered across binaries, headers, and lab
notebooks. The fields recorded here override any conflicting value
found elsewhere in the codebase.*

*This document fulfills Gate 2 of v7 Change 6 (pre-reg amendment
2026-05-24, Zenodo DOI 10.5281/zenodo.20371440). Every fact in
this document is cited against the source file from which it is
drawn; if a source file's value diverges from this document, the
divergence is either documented in §9 ("Known divergences") or
should be filed as a bug.*

## 1. Sensor configuration

The LSM6DSOX accelerometer is configured at fixed sample rate, range,
and filter settings across both pipelines (host and silicon). The
configuration values below are pre-registered (v4 amendment) and apply
to every v7 latency-experiment capture.

| Parameter | Value | Pre-reg source | Code source |
|---|---|---|---|
| Sensor ODR | 208 Hz | v4 amendment (pre-reg line 649) | `host_pipeline_parity.c:145` (`CTRL1_XL = 0x50`) |
| MLC ODR | 104 Hz | v4 amendment (pre-reg line 650) | `parity_core.c:245-246` (default) |
| Decimation ratio | 2:1 (sensor → MLC) | v4 amendment (pre-reg line 650) | `parity_core.c` (computed from ODRs) |
| Full-scale range | ±2g | original §5 + v4 amendment | `CTRL1_XL = 0x50` has FS_XL=0b00 |
| LPF2 | disabled | implicit in `CTRL1_XL = 0x50` | LPF2_XL_EN bit not set |
| Sensitivity | 0.061 mg/LSB | datasheet for ±2g range | `parity_core.h:38` (`PC_SENS_G_PER_LSB`) |
| DRDY routing | INT1 (Pin 15) | original §6 | `host_pipeline_parity.c:150` (`INT1_CTRL = 0x01`) |
| Bus | I²C-7 (Jetson pins 3/5) | docs/pin-assignment.md | `host_pipeline_parity.c:62` (`/dev/i2c-7`) |
| Address | 0x6A | docs/pin-assignment.md | `host_pipeline_parity.c:63` |

The `CTRL1_XL` register value `0x50` decomposes as:
- Bits 7:4 (ODR_XL) = 0b0101 = 208 Hz
- Bits 3:2 (FS_XL) = 0b00 = ±2g
- Bit 1 (LPF2_XL_EN) = 0 (LPF2 disabled)
- Bit 0 (reserved) = 0

This is the only `CTRL1_XL` value that should be written by any
binary participating in v7 latency captures. Legacy values (`0x60` =
416 Hz, used in pre-v4 binaries) are not used by v7 captures; see
§9 below.

## 2. MLC configuration

The MLC tree is selected at compile time via the
`-DMLC_CONFIG_HEADER` flag against the `mlc_setup` source file. The
header file contains the register-byte sequence that programs the
MLC tree; it is generated from a MEMS Studio JSON export by
`code/jetson/mlc_pipeline/json_to_header.py`.

| Parameter | Value | Source |
|---|---|---|
| Window length | 75 samples (720 ms at 104 Hz) | v7.2 amendment (Zenodo DOI 10.5281/zenodo.20371440) |
| Active tree | `code/mlc_config/mlc_motion_w75.h` (header) | v7.2 amendment |
| Equivalent JSON | `code/mlc_config/tree_w75.json` (for host pipeline) | v7 Change 6 item 7 |
| Setup binary | `code/jetson/session4/mlc_setup_w75` | Commit `8c48e19` |
| Classes | still = 0x00, motion = 0x04 | `mlc_motion_w75.h` |
| Feature | peak-to-peak of L2-norm of accel | `parity_core.c:feat_p2p` |
| Filter | IIR1 high-pass on L2-norm of accel | `parity_core.c:filter_iir1_hp_step` |
| Threshold | 0.049 g (peak-to-peak) | From `tree_w75.json`, leaf threshold |

### Flash protocol

The MLC is flashed at the start of every capture by invoking the
appropriate `mlc_setup_wN` binary. The flash sequence is documented
in `code/jetson/session4/mlc_setup.c` and includes:

1. SW_RESET (`CTRL3_C = 0x01`), 50 ms settle
2. WHO_AM_I check (`0x0F = 0x6C`)
3. Apply 93 MLC config register writes from the embedded header
4. Settle (100 ms)
5. Print "MLC ready" on stderr

After flash, the orchestrator performs a liveness check by reading
MLC0_SRC from the embedded register bank; see §6 for the bank-switch
protocol.

## 3. Host pipeline configuration

The host pipeline implements the same classifier as the on-sensor MLC,
bit-exact, so that decisions on identical accel data are identical.
This is the foundation of the §9 accuracy parity gate (cleared at
0.47 pp gap for w=75 in S7-prime; see lab notebook 2026-05-24).

| Parameter | Value | Source |
|---|---|---|
| Classifier core | `code/jetson/host_inference/parity_core.c` | Single-translation-unit, no deps beyond libc + libm |
| Tree config | `code/mlc_config/tree_w75.json` (loaded at runtime) | `parity_core.c:pc_load_config` |
| Window length | 75 samples (matches MLC) | `tree_w75.json:window_length` |
| Filter | IIR1 high-pass (b1, b2, a2 from tree.json) | `parity_core.c:filter_iir1_hp_step` |
| Feature | peak-to-peak of L2-norm | `parity_core.c:feat_p2p` |
| Real-time binary | `code/jetson/host_inference/host_pipeline_parity` | Built via `gcc -O2 -Wall -o host_pipeline_parity host_pipeline_parity.c parity_core.c -lgpiod -lm` |
| Offline replay binary | `code/jetson/host_inference/replay_parity` | For §9 evaluation against captured CSVs |

The host pipeline runs in real time during latency captures via
`host_pipeline_parity`:

1. Configure LSM6DSOX with `CTRL1_XL = 0x50` (208 Hz, ±2g, LPF2 off)
2. Route DRDY to INT1
3. Open gpiod handles for Pin 15 (INT1, input) and Pin 11 (decision, output)
4. Block on Pin 15 rising edges
5. On each edge: read accel via I²C, call `pc_step()`
6. Track binary state (class != still); on transition, pulse Pin 11 high then low

The pulse on Pin 11 is brief (back-to-back `gpiod_line_set_value`
calls). The rising edge of D1 (Pin 11) marks the host's binary-state
decision; the latency measurement is `t(D1 rising) − t(D0 rising)`
where D0 is the INT1 edge that triggered the sample completing the
window whose class decision flipped the binary state.

## 4. Silicon pipeline configuration

The on-sensor MLC pipeline is configured by the flash protocol in §2.
At runtime, the silicon-arm latency-measurement binary is:

| Parameter | Value | Source |
|---|---|---|
| Real-time binary | `code/jetson/mlc_pipeline/latency_test_mlc_w75` | Built via `gcc -O2 -Wall -I../../mlc_config -DMLC_CONFIG_HEADER=\"mlc_motion_w75.h\" -o latency_test_mlc_w75 latency_test_mlc.c -lgpiod` |
| Source | `code/jetson/mlc_pipeline/latency_test_mlc.c` | |
| Modes | `--pulsed` (default, EMB_FUNC_LIR=0) or `--latched` (EMB_FUNC_LIR=1) | `latency_test_mlc.c` runtime flags |
| Decision rule | binary state = (MLC0_SRC != 0x00); pulse Pin 11 on transitions | `latency_test_mlc.c:393-394` |

The silicon pipeline does not run the host classifier; it only
flashes the MLC and waits for INT1 rising edges (which fire when the
MLC's binary state changes per EMB_FUNC_LIR semantics). On each INT1
edge, the binary reads MLC0_SRC, determines the new binary state, and
pulses Pin 11 if it has changed. Wire-level latency for a given
trial is `t(D1 rising) − t(D0 rising)` where D0 is the INT1 edge of
the relevant binary-state transition.

The default `--pulsed` mode is appropriate for the v7 protocol's
servo-driven burst stimulus, where INT1 pulse widths are far longer
than the gpiod event-read latency.

## 5. I²C bus configuration

The Jetson exposes two I²C buses to the experiment, each configured
via the device tree at boot. Bus speeds are read from
`/sys/bus/i2c/devices/i2c-N/of_node/clock-frequency`.

| Bus | Speed | Device | Address |
|---|---|---|---|
| `/dev/i2c-7` | 400 kHz (Fast Mode) | LSM6DSOX | 0x6A |
| `/dev/i2c-1` | 100 kHz (Standard Mode) | PCA9685 | 0x60 |

The sensor bus at 400 kHz minimizes the I²C-read overhead per accel
sample. The PCA9685 bus at 100 kHz is sufficient for low-rate servo
commands (~10 Hz max in v7's burst protocol).

### Measured accel-read latency

A single 6-byte accel-data read (six consecutive registers OUTX_L_A
through OUTZ_H_A at 0x28-0x2D) takes the following time over the
Linux I²C subsystem:

| Statistic | Value |
|---|---|
| Minimum | 292 µs |
| 10th percentile | 293 µs |
| **Median** | **305 µs** |
| 90th percentile | 317 µs |
| 99th percentile | 360 µs |
| Maximum | 448 µs |
| Mean | 305 µs |

Measured 2026-05-25 on the rig (n=1000 reads, /dev/i2c-7 at 400 kHz,
LSM6DSOX at 0x6A). The benchmark source is at
`code/jetson/sensor_bringup/i2c_read_bench.c`; reproducible by:

```bash
cd code/jetson/sensor_bringup
gcc -O2 -Wall -o /tmp/i2c_read_bench i2c_read_bench.c
sudo /tmp/i2c_read_bench
```

The bit-level protocol time at 400 kHz is approximately:
- 1 START + 1 address byte (write, register pointer): ~22.5 µs
- 1 repeated START + 1 address byte (read) + 6 data bytes: ~175 µs
- Protocol-time floor: ~200 µs

The measured median of 305 µs reflects the kernel-overhead component
on top of the protocol-time floor (`ioctl(I2C_RDWR)` syscall, two
i2c_msg structure setup, kernel-userspace boundary crossings). The
overhead is roughly 50% above the protocol floor; this is consistent
with Linux I²C subsystem overhead on this Jetson Orin Nano.

This 305 µs is part of the on-sensor pipeline's measured latency
budget: the silicon's INT1 fires when the MLC's binary state changes,
the host then incurs ~305 µs to read the trigger sample's accel data
before doing classification math. This overhead is built into the
wire-level D0→D1 measurement; it does not need to be subtracted out.

## 6. Register-read sequences

### Bank switching for embedded-function registers

The LSM6DSOX exposes MLC outputs (MLC0_SRC and friends) in an
**embedded function bank** that is not directly addressable through
the default user register space. To read MLC0_SRC, the bank must be
switched via FUNC_CFG_ACCESS, then switched back to leave the device
in a known state for subsequent operations.

The three-step sequence:

Write FUNC_CFG_ACCESS (0x01) = BANK_EMBEDDED (0x80)
Read MLC0_SRC (0x70) from embedded bank
Write FUNC_CFG_ACCESS (0x01) = BANK_USER (0x00) to restore


This is implemented in `code/jetson/mlc_pipeline/mlc_poll_probe.c`
(`read_mlc_src` function) and used by `mlc_poller` for runtime polling
and by the orchestrator's `verify_silicon_alive()` for post-flash
liveness checks.

The bank-switch sequence is also accessible via shell:

```bash
sudo i2cset -y 7 0x6a 0x01 0x80   # bank to embedded
sudo i2cget -y 7 0x6a 0x70        # read MLC0_SRC
sudo i2cset -y 7 0x6a 0x01 0x00   # bank back to user
```

This shell pattern is documented in `docs/pin-assignment.md` and
exercised in the orchestrator's `verify_silicon_alive()` function.

### MLC tree page register access

The MLC tree itself (including the window-length parameter at
internal page address 0xF2) is in a different register space again,
accessed through page-indirection registers 0x02 (PAGE_SEL), 0x08
(PAGE_ADDRESS), 0x09 (PAGE_VALUE), and 0x17 (PAGE_RW). The flash
protocol in `mlc_setup.c` writes 93 register bytes through this
indirection. Read-back from this address space is not currently
implemented in this project; see lab notebook 2026-05-25 for the
discussion of why a register-readback verification was abandoned in
favor of behavioral verification.

### Sensor data read

Triaxial accelerometer data lives in registers 0x28-0x2D (six bytes,
little-endian per axis: OUTX_L, OUTX_H, OUTY_L, OUTY_H, OUTZ_L,
OUTZ_H). The read is a single I²C transaction with auto-increment:

```c
i2c_read_block(fd, 0x28, buf, 6);   // reads 0x28 through 0x2D
```

Conversion to g uses the sensitivity from §1:
```c
int16_t raw_x = (buf[1] << 8) | buf[0];   // little-endian
float x_g = raw_x * 0.061e-3f;            // mg/LSB for ±2g
```

This is implemented identically in `host_pipeline_parity.c` and
`replay_parity.c` (via `parity_core.c`).

## 7. Saleae configuration

The Saleae Logic Pro 8 captures digital edges from three channels.
All three are required for the v7 latency-experiment protocol.

| Channel | Source | Direction | Purpose |
|---|---|---|---|
| D0 | LSM6DSOX INT1 (Pin 15) | input | DRDY or MLC-INT rising edge |
| D1 | Decision GPIO (Pin 11) | input | Host or silicon binary-state transition |
| D2 | PCA9685 channel 0 PWM | input | Ground-truth label / training reference |

The decision-GPIO mapping (Pin 11 → D1) was corrected by v7.1
amendment after v7's text incorrectly claimed D3; the wiring has been
D1 throughout the project per `docs/pin-assignment.md`. Any reference
in the pre-reg to "D3" for the decision GPIO is stale text from v7
predating v7.1.

| Parameter | Value | Source |
|---|---|---|
| Digital sample rate | 50 MS/s | v7 Change 4 (pre-reg line 1223) |
| Channels enabled | [D0, D1, D2] | `code/orchestrator/run_session.py:63` |
| Analog channels | none | `code/orchestrator/run_session.py:64` |
| Device ID | 6F657C15C3EEE446 (Logic Pro 8) | `run_session.py:46` |
| Port | 10430 | `run_session.py:47` |
| Capture margin | 5 seconds beyond logger duration | `run_session.py:48` |

The 50 MS/s rate provides 20 ns timing resolution, far below the 10
µs / 50 µs effect-size thresholds of §6.3. Captures from before v7
(at 12.5 MS/s) are retained for §9 window-length analysis but do not
enter the latency analysis.

## 8. Binary inventory for v7 latency captures

The following binaries are part of the v7 latency-experiment protocol.
Each binary's commit-pinned sha256 should be recorded in
`session.json` for audit (Gate 1 will add this field).

Hashes below are a point-in-time snapshot from 2026-05-25; rebuilding
any of these binaries will produce a different hash, requiring this
table to be refreshed.

| Binary | Source | Sha256 (2026-05-25) | Role |
|---|---|---|---|
| `code/jetson/session4/mlc_setup_w75` | `mlc_setup.c` + `mlc_motion_w75.h` | `59f9b3c0...` | Flash MLC tree at session start |
| `code/jetson/session4/mlc_poller` | `mlc_poller.c` | (see Jetson; built 2026-05-23) | Poll MLC0_SRC at 50 Hz for §9 captures |
| `code/jetson/host_inference/host_pipeline_parity` | `host_pipeline_parity.c` + `parity_core.c` | `48b848ae...` | Host real-time classifier (latency-experiment host arm) |
| `code/jetson/host_inference/replay_parity` | `replay_parity.c` + `parity_core.c` | (see Jetson; built 2026-05-23) | Offline host pipeline replay for §9 evaluation |
| `code/jetson/mlc_pipeline/latency_test_mlc_w75` | `latency_test_mlc.c` + `mlc_motion_w75.h` | `da41aa95...` | Silicon-arm latency measurement (latency-experiment silicon arm) |
| `code/jetson/imu_logger/imu_logger` | `imu_logger.c` | (see Jetson; built earlier) | Log accel CSV at 208 Hz for §9 captures |
| `code/jetson/servo/servo_sweep` | `servo_sweep.c` | (see Jetson; built 2026-05-24) | Drive PCA9685 servo for motion stimulus |

### Build commands (canonical)

These commands rebuild from source. Run on the Jetson; see
`docs/session-runbook.md` for the broader build sequence.

```bash
# Host real-time classifier (v7 latency-experiment host arm)
cd ~/sensor-mlc-latency/code/jetson/host_inference
gcc -O2 -Wall -o host_pipeline_parity host_pipeline_parity.c parity_core.c -lgpiod -lm

# Silicon latency measurement (v7 latency-experiment silicon arm)
cd ~/sensor-mlc-latency/code/jetson/mlc_pipeline
gcc -O2 -Wall -I../../mlc_config \
    -DMLC_CONFIG_HEADER=\"mlc_motion_w75.h\" \
    -o latency_test_mlc_w75 latency_test_mlc.c -lgpiod

# MLC flash binary (already built; one per supported window length)
cd ~/sensor-mlc-latency/code/jetson/session4
gcc -Wall -O2 -I../../mlc_config \
    -DMLC_CONFIG_HEADER='"mlc_motion_w75.h"' \
    -o mlc_setup_w75 mlc_setup.c
```

## 9. Known divergences and legacy files

The codebase contains several files that use parameter values
divergent from this document. These files are not part of the v7
latency-experiment data path and their values are not authoritative;
they are documented here so a future reader can identify them as
not-current.

### Pre-v3 / pre-v4 binaries (tap-detection era)

These binaries implement the original tap-detection task (later
superseded by the motion-vs-still task per v3 amendment). They use
ODR = 416 Hz (`CTRL1_XL = 0x60`) and a peak-to-peak tap classifier.
They are retained in the repo for historical reference and bring-up
diagnostics, NOT for the v7 latency experiment.

| File | Task | ODR |
|---|---|---|
| `code/jetson/host_inference/host_pipeline.c` | Tap-detection host pipeline (B5 era) | 416 Hz |
| `code/jetson/host_inference/accel_read.py` | Bring-up accel reader | 416 Hz |
| `code/jetson/sensor_bringup/tap_int_test.py` | Tap-interrupt bring-up | 416 Hz |
| `code/jetson/sensor_bringup/drdy_diagnose.py` | DRDY diagnostic | 416 Hz |
| `code/jetson/mlc_pipeline/latency_test.c` | Pre-MLC latency probe | 416 Hz |
| `code/jetson/mlc_pipeline/mlc_accuracy.h`, `mlc_latency.h` | Pre-motion-vs-still MLC trees | 416 Hz |
| `code/jetson/mlc_pipeline/latency_test_mlc_acc`, `_lat`, `_activity` (binaries) | Pre-v7 MLC latency variants | 416 Hz |

A reviewer or future reader who finds `CTRL1_XL = 0x60` in any of
these files should understand: this is intentional historical
preservation, not a value that v7 captures use.

### Pre-v7 MLC trees

| File | Status |
|---|---|
| `code/jetson/mlc_pipeline/mlc_accuracy.h` | Tap-detection MLC tree (pre-v3) |
| `code/jetson/mlc_pipeline/mlc_latency.h` | Tap-detection MLC tree variant |
| `code/mlc_config/lsm6dsox_activity_recognition_for_mobile.h` | ST activity recognition (deemed unsuitable in v3 amendment) |
| `code/mlc_config/mlc_activity.h` | Activity-recognition derived (not used) |

The authoritative tree for v7 is `code/mlc_config/tree_w75.json`
(host) and `code/jetson/mlc_config/mlc_motion_w75.h` (silicon flash).
These were aligned per v7.2 amendment.

### Parity test fixture

`code/jetson/host_inference/test_replay_parity.sh` contains a fixture
JSON with `mlc_odr_hz = 208`, which is above the AN5259 cap of 104
Hz. This fixture is a stress test of the parity engine's MLC-ODR
warning path (see `host_pipeline_parity.c:201-207` for the warning).
It is not a deployment configuration; do not use this fixture's
values as operational parameters.

## 10. Cross-references

| Topic | Authoritative location |
|---|---|
| Pin assignments (sensor, PCA9685, Saleae, GPIO) | `docs/pin-assignment.md` |
| Session orchestration runbook | `docs/session-runbook.md` |
| Pre-registration (research design, hypotheses, gates) | `docs/pre-registration.md` |
| Training data spec (ODR, geometry) | `docs/training-data-spec.md` |
| MEMS Studio JSON → C header conversion | `docs/mems-studio-json-parity-extraction.md` |

When values in this document conflict with the cross-references above,
this document takes precedence for parameters listed in §1-§7 (sensor,
MLC, host pipeline, I²C bus, register-read sequences, Saleae). The
cross-referenced documents are authoritative for their respective
non-overlapping scopes (e.g. `docs/pin-assignment.md` for wiring is
canonical; this document defers to it for pin numbers).

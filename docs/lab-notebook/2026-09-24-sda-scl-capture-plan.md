# SDA/SCL capture plan — 2026-09-24 (committed before first capture)

## Purpose
Direct on-wire evidence for the three-transaction MLC read protocol
(write FUNC_CFG_ACCESS=0x80, read MLC0_SRC=0x70, write FUNC_CFG_ACCESS=0x00)
and decomposition of MLC decision latency into bus time vs. scheduling/gaps.

## Hardware
- Saleae Logic Pro 8, Logic 2, 25 MS/s digital, 3.3 V threshold, glitch filter off
- Ch0=D0 (INT1, header pin 15), Ch1=D1 (decision GPIO, pin 11), Ch2=D2 (servo PWM),
  Ch3=SDA (pin 3), Ch4=SCL (pin 5), GND pin 6
- LSM6DSOX (Adafruit PID 4438) on I2C bus 7, address 0x6A, 400 kHz

## Planned captures
1. Sanity: 10 s, pipeline running, verify decode + transaction triple inside D0->D1 windows
2. Block A: idle, 300 s, latency_test_mlc_w75 alone
3. Block B: i2c-contention, 300 s, pipeline + 3x i2c_hammer on bus 7
4. Block C: stress, 300 s, pipeline + stress-ng --cpu 6 --cpu-method matrixprod
5. Control: short mlc-binary block (negative control)

## Analysis (pre-committed)
- Decode I2C; classify transactions by register:
  0x01 write / 0x70 read = pipeline; all other registers = hammer traffic (NOT deviations)
- Per D0->D1 window: verify exactly one 0x80-write / 0x70-read / 0x00-write triple
- Decompose D0->D1 latency: bus transaction time vs. inter-transaction gaps vs. GPIO path
- Measure SCL/SDA rise times (spot check)
- No on-wire arbitration expected (single master; Linux i2c adapter lock serializes)

## Amendment 2026-09-25 — clock-regime provenance and re-capture

Finding: retroactive tegrastats inspection shows the confirmatory campaign
(2026-05-26, e.g. b018) ran with all CPU cores pegged at 1728 MHz, while the
2026-09-24 evidence blocks b001–b004 ran under dynamic clocking (729 MHz idle,
ramping on load). Consequences: (a) all four 09-24 blocks fail the v7.6
servo-jitter inclusion gate (jc_eff 5.8–97.8% vs 99% threshold; confirmatory
blocks were 100%); (b) idle-regime D0→D1 latency is inflated ~0.66 ms by
frequency-ramp/wakeup effects. The latency shift and jc_eff collapse share
this single root cause; no hardware or pipeline regression is indicated.

Action: blocks b005–b008 (mlc-idle, mlc-i2c-contention, mlc-stress,
mlc-binary-idle) are captured under nvpmodel mode 3 (MAXN_SUPER_JC), the measurement configuration required by pre-registration v7.6 Change 2, to match
the confirmatory regime; clock state is recorded in each block directory
(nvpmodel -q and tegrastats header) at capture time. Blocks b001–b004 are
retained as a labeled dynamic-clock regime for the OS-sensitivity analysis;
they are not used as gate-passing evidence.

Additional correction: the i2c-contention hammer targets the sensor's own
address (0x6A) with WHO_AM_I (0x0F) reads, not a separate 0x60 device as
previously assumed; verified by on-wire decode of block b002.

**Evidence archive (2026-09-24):** all blocks described in this plan and its amendment - raw Saleae captures, tegrastats/sweep logs, block metadata, and verification code - are archived at Zenodo DOI 10.5281/zenodo.22950121 (evidence package v1.1.0-r1).

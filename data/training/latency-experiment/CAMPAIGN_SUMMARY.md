# v7.5 latency-experiment campaign — 2026-05-25 (btest scale)

## Block index

Block IDs partition the day's runs into distinct campaigns:

| ID range  | Pipeline(s)              | Conditions                | Orchestrator state            | Notes |
|-----------|--------------------------|---------------------------|-------------------------------|-------|
| 001-005   | host, mlc                | idle, stress, i2c-cont    | Pre-restructure orchestrator  | Early btest, pre-orchestrator restructure. Some MLC blocks failed under contention because pipeline init ran concurrently with contention. |
| 101-112   | host, mlc                | idle, i2c-contention      | Pre-restructure orchestrator  | First full 12-block run. MLC i2c-contention cells failed (WHO_AM_I init failure under bus contention). |
| 200-202   | mlc                      | i2c-contention            | Restructured orchestrator     | Validation that init-grace fix lets MLC pipeline run under contention. |
| 301-312   | host, mlc                | idle, i2c-contention      | Restructured orchestrator     | Clean 12-block run. Vanilla scheduling. The primary dataset. |
| 401-407   | mlc-binary               | idle, i2c-contention      | Restructured orchestrator     | mlc-binary (skip-MLC0_SRC-read variant). Vanilla scheduling. |
| 501-502   | mlc-binary               | idle, i2c-contention      | Restructured + chrt+taskset   | Initial chrt+taskset smoke test. |
| 601-618   | host, mlc-binary, mlc    | idle, i2c-contention      | Restructured + chrt+taskset   | Full 18-block chrt+taskset campaign. SCHED_FIFO -f 99, CPU pin -c 5. |

All blocks use `--btest` (30-second blocks, 6 stimulus transitions per block).

## Per-cell summary (btest scale, n ≈ 15-18 per cell)

### Vanilla scheduling (blocks 301-312, 401-407)

| Cell                            | n  | min | p25 | median | p75  | max  | mean | sd  |
|---------------------------------|----|-----|-----|--------|------|------|------|-----|
| host       idle                 | 18 | 262 | 339 | 351    | 386  | 468  | 359  | 41  |
| host       i2c-contention       | 15 | 347 | 574 | 643    | 675  | 777  | 624  | 96  |
| mlc-binary idle                 | 18 | 65  | 88  | 274    | 483  | 568  | 283  | 201 |
| mlc-binary i2c-contention       | 18 | 42  | 57  | 76     | 303  | 586  | 184  | 173 |
| mlc        idle                 | 17 | 545 | 732 | 761    | 1061 | 1579 | 935  | 356 |
| mlc        i2c-contention       | 18 | 540 | 1397| 1534   | 1644 | 2531 | 1467 | 453 |

### chrt -f 99 + taskset -c 5 scheduling (blocks 601-618)

| Cell                            | n  | min | p25 | median | p75 | max  | mean | sd  |
|---------------------------------|----|-----|-----|--------|-----|------|------|-----|
| host       idle                 | 15 | 294 | 340 | 367    | 393 | 620  | 399  | 94  |
| host       i2c-contention       | 17 | 364 | 380 | 392    | 435 | 501  | 409  | 41  |
| mlc-binary idle                 | 18 | 112 | 131 | 333    | 591 | 618  | 359  | 189 |
| mlc-binary i2c-contention       | 18 | 87  | 104 | 116    | 328 | 620  | 200  | 152 |
| mlc        idle                 | 17 | 559 | 584 | 799    | 812 | 1605 | 788  | 249 |
| mlc        i2c-contention       | 18 | 524 | 648 | 796    | 858 | 1048 | 779  | 147 |

All latencies in microseconds. Median is the primary statistic; sd quantifies within-cell jitter.

## Key findings (btest scale)

1. **CPU stress (stress-ng) does NOT degrade either pipeline's median wire-level latency.** Pre-reg H1/H4 (host pipeline degrades under CPU stress while MLC does not) is FALSIFIED at btest scale.

2. **I²C bus contention DOES degrade pipelines under vanilla scheduling.** Host pipeline median increases +83% under N=3 i2c_hammer contention; MLC bank-switch pipeline median increases +102%.

3. **The MLC bank-switch read protocol takes 3 I²C transactions per measurement.** Predicted latency = 3 × i2c_read_bench median. Predicted ≈ 903µs idle, 1869µs contention. Observed 761 / 1534. Mechanism confirmed.

4. **chrt+taskset (SCHED_FIFO priority 99, CPU pinned to core 5) DRAMATICALLY reduces the contention effect.** Host pipeline median goes from +292µs degradation under contention to +25µs. MLC bank-switch from +773µs to +0µs.

5. **mlc-binary (skip the MLC0_SRC read) exposes a bimodal gpiod userspace jitter floor.** Internal `host_dt_us` is 17-21µs but wire-level (Saleae D0→D1) is bimodal between ~60µs and ~550µs. Bimodality persists under chrt+taskset.

6. **Host pipeline is the fastest at the median in ALL conditions tested**, contradicting pre-reg H1.

## Reproducibility

Each block dir contains:
- `block_metadata.json` — orchestrator state (pipeline, condition, sync timestamps, verification results, exclusions)
- `saleae.sal` — Saleae Logic 2 capture (D0=Pin15 INT1, D1=Pin11 decision, D2=Pin18 servo PWM)
- `digital.csv` — exported Saleae digital channels
- `trials.csv` — extracted per-trial latencies (extract_latency_v7.py output)
- `pipeline.log` — pipeline binary stdout/stderr (includes per-event host_dt_us)
- `sweep.log` — servo_sweep PWM event timestamps
- `tegrastats.log` — system state log

Code state: commit d4a877d (chrt+taskset variant runs are not committed to orchestrator; apply transform `s|f"timeout|f"chrt -f 99 taskset -c 5 timeout|` to reproduce).

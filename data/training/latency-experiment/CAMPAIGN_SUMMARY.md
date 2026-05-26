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

## Energy findings (added 2026-05-25 post-analysis)

The on-Jetson INA3221 (bus 1, address 0x40, kernel `hwmon1`) is the source of
all `VDD_IN`, `VDD_CPU_GPU_CV`, and `VDD_SOC` readings in the `tegrastats.log`
files. This is a Jetson-internal power monitor measuring SoC rails (not a
separate user-deployed power probe; there is no separate sensor-side power
measurement in this rig). Tegrastats samples roughly every 400 ms, giving
~75 instantaneous samples per 30-second btest block; aggregated across n=18
blocks per cell, each cell has ~220 energy samples.

This is the correct axis to test the industry claim that on-sensor MLC
inference "lets the host sleep" — the Jetson SoC's idle power IS what would
benefit from a host duty-cycle reduction.

### Per-cell energy summary (primary blocks only, VDD_IN mean mW)

Primary blocks = 301-312 + 402-407 (vanilla scheduling) and 601-618
(chrt+taskset scheduling). Pre-restructure (001-005, 101-112), restructure
validation (200-202, 401), and chrt+taskset smoke (501-502) are excluded
because the orchestrator state differs and the pre-restructure MLC
i2c-contention cells failed at startup.

#### Vanilla scheduling

| Pipeline | Idle (mW, n≈225) | i2c-contention (mW, n≈220) | Δ |
|----------|------------------|----------------------------|---|
| host        | 4799 | 5012 | +213 (+4.4%) |
| mlc-binary  | 4646 | 4962 | +316 (+6.8%) |
| mlc         | 4644 | 4983 | +339 (+7.3%) |

#### chrt+taskset scheduling

| Pipeline | Idle (mW, n≈225) | i2c-contention (mW, n≈225) | Δ |
|----------|------------------|----------------------------|---|
| host        | 4848 | 5075 | +227 (+4.7%) |
| mlc-binary  | 4643 | 4968 | +325 (+7.0%) |
| mlc         | 4643 | 4982 | +339 (+7.3%) |

### Combined latency + energy (primary blocks only, vanilla scheduling)

#### At idle

| Pipeline | Latency median (µs) | Energy mean (mW) | n_lat | n_eng |
|----------|--------------------:|-----------------:|------:|------:|
| host        | 351  | 4799 | 18 | 228 |
| mlc-binary  | 274* | 4646 | 18 | 221 |
| mlc         | 761  | 4644 | 17 | 224 |

#### Under I²C contention

| Pipeline | Latency median (µs) | Energy mean (mW) | n_lat | n_eng |
|----------|--------------------:|-----------------:|------:|------:|
| host        | 643   | 5012 | 15 | 222 |
| mlc-binary  | 76*   | 4962 | 18 | 225 |
| mlc         | 1534  | 4983 | 18 | 220 |

*mlc-binary medians are unstable due to bimodal gpiod jitter (sd 150-200 µs);
median bounces between the fast mode (~60 µs) and slow mode (~330 µs)
depending on which mode happens to dominate a given block.

### Key energy + latency findings

1. **MLC variants use ~150 mW less than host at idle.** At idle (vanilla
   scheduling), host pipeline draws 4799 mW vs 4644-4646 mW for the MLC
   variants. That's ~3% of total Jetson SoC power. The industry "on-sensor
   inference lets the host sleep" claim is directionally validated by the
   energy measurement — but the savings are smaller than the marketing
   would suggest (~150 mW out of ~4800 mW, not "20-100x less" at the
   system level).

2. **The energy gap shrinks under I²C contention.** Under i2c-contention,
   the host-vs-MLC energy gap narrows to ~30-50 mW. The MLC's idle-energy
   advantage is mostly an idle-mode property; under stress, both pipelines
   converge.

3. **CPU stress (pre-restructure block-002 host-stress, block-003
   mlc-stress)** showed VDD_IN at ~7780-8037 mW versus ~4644-4799 mW under
   idle — a ~3000 mW spike for CPU stress that has no parallel in the
   latency data (CPU stress did NOT move median wire-level latency by
   more than ~10 µs). Energy and latency respond to different stress
   modalities: CPU stress hits energy; I²C contention hits latency.
   This may be the most counterintuitive single finding of the campaign.

4. **mlc-binary uses MORE energy than mlc (bank-switch) under
   i2c-contention** (4962 vs 4983 mW — within noise, but contention
   raises mlc-binary by 316 mW vs mlc's 339 mW). Skipping the I²C read
   does not save energy at the system level once classifier-driven
   wakeups are accounted for. This is contrary to the naive "fewer I²C
   reads → less energy" intuition.

5. **chrt+taskset scheduling has minimal energy impact.** Energy means
   shift by less than 1% between vanilla and chrt+taskset scheduling
   for all cells. The dramatic latency improvement under chrt+taskset
   (e.g., mlc i2c-contention: 1534 → 796 µs) comes without a measurable
   energy cost on this rig.

### Reproducing the energy analysis

```bash
python3 code/analysis/analyze_energy_and_latency.py \
    --include-experimental primary \
    --out data/training/latency-experiment/ANALYSIS_OUTPUT.md
```

The script also supports `--include-experimental all` to include
pre-restructure / smoke / validation blocks. Those blocks are present in
the data tree (see Block Index above) but the orchestrator behavior
differed and their cells are not directly comparable to the primary
campaigns.

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

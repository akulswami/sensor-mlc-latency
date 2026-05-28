# Campaign Results: confirmatory-2026-05-26

**Source:** `data/training/confirmatory-2026-05-26/campaign_manifest.json`
**Seed:** 1990185399 (per pre-reg v7.8, DOI 10.5281/zenodo.20401819)
**Wall time:** 25506.2s = 7.09 hours
**Blocks:** 81/81 completed, 81/81 OK, 100% jc_eff across all blocks
**Pipeline binaries:**
- `host`: host_pipeline_parity, decision-tree on accelerometer 75-sample windows at 416 Hz
- `mlc`: latency_test_mlc_w75, 3-transaction bank-switch read of MLC0_SRC
- `mlc-binary`: latency_test_mlc_binary_w75, 0-transaction binary-fast variant (toggles GPIO unconditionally on INT1)

## Table 1: Wire-level latency (µs) per cell

Latency = t(D1 rising) − t(D0 rising) per pre-reg v7 Change 3.

| pipeline | condition | n_blocks | n_incl | excl_% | median | p25 | p75 | p05 | p95 | mean | stdev |
|----------|-----------|---------:|-------:|-------:|-------:|----:|----:|----:|----:|-----:|------:|
| host       | idle           |        9 |    536 |  0.74% |  321.7 | 319.7 | 326.4 | 318.3 | 349.1 | 328.8 |  33.2 |
| host       | i2c-contention |        9 |    529 |  2.04% |  574.5 | 547.8 | 599.0 | 467.6 | 640.2 | 570.4 |  54.7 |
| host       | stress         |        9 |    532 |  1.48% |  345.0 | 342.0 | 349.0 | 335.5 | 361.3 | 351.3 | 138.9 |
| mlc        | idle           |        9 |    525 |  2.78% |  681.5 | 505.4 | 1086.8 | 483.3 | 1780.7 | 866.6 | 422.0 |
| mlc        | i2c-contention |        9 |    532 |  1.48% | 1325.4 | 1283.8 | 1371.5 | 1247.3 | 1536.6 | 1333.2 | 125.5 |
| mlc        | stress         |        9 |    527 |  2.41% |  546.1 | 535.8 | 557.0 | 521.8 | 580.3 | 560.6 | 162.0 |
| mlc-binary | idle           |        9 |    531 |  1.67% |  231.9 | 61.8 | 246.2 | 49.8 | 485.5 | 236.7 | 155.3 |
| mlc-binary | i2c-contention |        9 |    527 |  2.41% |   49.4 | 46.9 | 53.2 | 43.7 | 247.4 |  64.5 |  53.3 |
| mlc-binary | stress         |        9 |    531 |  1.67% |   70.2 | 66.9 | 73.0 | 62.0 | 78.4 |  72.0 |  19.0 |

## Observations

### Pre-registered (H1'-H7' from v7.5/v7.6/v7.10):
- **H1' (host < MLC at idle): SUPPORTED.** Host median 321.7µs vs MLC median 681.5µs (factor of 2.1x).
- **H2' (host < MLC under contention): SUPPORTED.** Host i2c-contention 574.5µs vs MLC i2c-contention 1325.4µs (factor of 2.3x).
- **H3' (MLC degrades more under contention): SUPPORTED.** MLC: 681.5 → 1325.4 (+95%). Host: 321.7 → 574.5 (+79%).
- **H5' (CPU stress null for host latency): SUPPORTED (equivalent).** Host stress 345.0µs vs idle 321.7µs. Formal TOST with ±30 µs margin: median diff +23.3 µs (90% CI [22.7, 23.7]) ⊂ [-30, +30]. Equivalence declared.
- **H7' (classifier stability degrades under contention): NOT SUPPORTED, direction OPPOSITE to prediction.** MLC stability under i2c-contention (98.89%, 534/540) is slightly HIGHER than under idle (97.22%, 525/540); Fisher's exact one-sided in pre-reg direction p=0.9874; two-sided reference p=0.0755 (marginal, n.s.). Formally falsified in v7.10 (Zenodo DOI 10.5281/zenodo.20420866). Substantive implication: I²C contention adds latency (H2', H3') but does NOT degrade classifier reliability.

### Exploratory (post-hoc):
- **Multimodal latency distributions** observed in mlc and mlc-binary pipelines under all conditions. mlc/idle shows modes at 480µs and 675µs separated by ~180µs. mlc-binary shows modes at 50µs, 230µs, and 450µs.
- **MLC 706.5ms intrinsic decision cadence** confirmed: D0 inter-edge gaps are quantized to integer multiples of 706.5ms.
- **mlc-binary is 0-I²C-transaction:** the binary toggles D1 unconditionally on every INT1 rising edge, without reading MLC0_SRC. Its measured latency reflects pure kernel/gpiod interrupt-to-GPIO write time, which is itself multimodal at ~50µs and ~230µs.

### Exclusion rates
All cells under §11's 10% cap. Highest: mlc/idle at 2.78%. Lowest: host/idle at 0.74%.

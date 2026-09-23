# Canonical latency summary table (confirmatory-2026-05-26)

Source: `data/training/latency-experiment/block-confirmatory-2026-05-26-b*-<pipeline>-<condition>/trials.csv` (81 blocks, 9 per cell). Quantiles: `np.percentile` default linear interpolation. stdev: sample stdev (`ddof=1`). Only `included == true` trials counted.

| pipeline | condition | n | p25 (µs) | median (µs) | p75 (µs) | p95 (µs) | p99 (µs) | max (µs) | mean (µs) | stdev (µs) |
|----------|-----------|---:|---------:|------------:|---------:|---------:|---------:|---------:|----------:|-----------:|
| host | idle | 536 | 319.7 | 321.7 | 326.3 | 347.3 | 506.3 | 642.9 | 328.8 | 33.2 |
| host | i2c-contention | 529 | 547.8 | 574.5 | 599.0 | 639.5 | 662.3 | 854.1 | 570.4 | 54.7 |
| host | stress | 532 | 342.0 | 345.0 | 348.9 | 361.2 | 400.6 | 3504.8 | 351.3 | 138.9 |
| mlc | idle | 525 | 505.4 | 681.5 | 1086.8 | 1779.7 | 2120.6 | 2604.5 | 866.6 | 422.0 |
| mlc | i2c-contention | 532 | 1283.7 | 1325.4 | 1370.8 | 1536.2 | 1675.4 | 1904.8 | 1333.2 | 125.5 |
| mlc | stress | 527 | 535.9 | 546.1 | 557.0 | 579.5 | 879.1 | 3868.2 | 560.6 | 162.0 |
| mlc-binary | idle | 531 | 61.8 | 231.9 | 246.2 | 485.3 | 654.2 | 723.9 | 236.7 | 155.3 |
| mlc-binary | i2c-contention | 527 | 46.9 | 49.4 | 53.1 | 246.7 | 272.1 | 289.3 | 64.5 | 53.3 |
| mlc-binary | stress | 531 | 66.9 | 70.2 | 73.0 | 78.4 | 197.5 | 253.7 | 72.0 | 19.0 |

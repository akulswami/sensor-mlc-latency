# Table I

<!-- NOTE: this is a human-readable reference copy, NOT a build input.
     The compiled PDF's Table I comes from _float_tableI.tex via
     build_tex.py; this file is not read by the build at all. Keep the
     two in sync by hand -- editing only this file will not change the
     PDF. -->

**TABLE I**
**Wire-Level Latency per Pipeline × Condition (µs)**

Latency = t(D1 rising) − t(D0 rising). Each cell aggregates 9 blocks of 300 s. n = included trials (4,770 of 4,860 candidates, 98.15%). IQR = interquartile range (p25–p75). All values µs except n.

| Pipeline | Condition | n | Median | IQR | p95 | Mean |
|----------|-----------|---:|------:|----:|----:|-----:|
| host | idle | 536 | 321.7 | 319.7–326.3 | 347.3 | 328.8 |
| host | i2c-cont. | 529 | 574.5 | 547.8–599.0 | 639.5 | 570.4 |
| host | stress | 532 | 345.0 | 342.0–348.9 | 361.2 | 351.3 |
| mlc | idle | 525 | 681.5 | 505.4–1086.8 | 1779.7 | 866.6 |
| mlc | i2c-cont. | 532 | 1325.4 | 1283.7–1370.8 | 1536.2 | 1333.2 |
| mlc | stress | 527 | 546.1 | 535.9–557.0 | 579.5 | 560.6 |
| mlc-binary | idle | 531 | 231.9 | 61.8–246.2 | 485.3 | 236.7 |
| mlc-binary | i2c-cont. | 527 | 49.4 | 46.9–53.1 | 246.7 | 64.5 |
| mlc-binary | stress | 531 | 70.2 | 66.9–73.0 | 78.4 | 72.0 |

*Note: The mlc/idle mean (866.6) exceeding its median (681.5), and the wide mlc/idle IQR, reflect the multimodal structure discussed in §V.B. The mlc-binary pipeline performs zero I²C transactions on the decision path, isolating the kernel/gpiod latency floor.*

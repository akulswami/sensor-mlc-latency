# References

*(IEEE format, ordered by first appearance in the manuscript.)*

[1] STMicroelectronics, "LSM6DSOX: 6-axis IMU with machine learning core," Datasheet DS12140, Rev. 6, 2024. [Online]. Available: https://www.st.com/resource/en/datasheet/lsm6dsox.pdf

[2] STMicroelectronics, "LSM6DSOX: Machine Learning Core," Application Note AN5259, Rev. 4, 2023. [Online]. Available: https://www.st.com/resource/en/application_note/an5259-lsm6dsox-machine-learning-core-stmicroelectronics.pdf

[3] M. Razmi and I. Shojaei, "Event-driven on-sensor locomotion mode recognition using a shank-mounted IMU with embedded machine learning for exoskeleton control," arXiv preprint arXiv:2602.21418, Feb. 2026. [Online]. Available: https://arxiv.org/abs/2602.21418

[4] A. Swami, "Pre-registration chain for the sensor-mlc-latency study," Zenodo, multi-amendment DOI chain, 2026. v6.1 (DOI: 10.5281/zenodo.20370205), v7 (10.5281/zenodo.20370234), v7.1 (10.5281/zenodo.20370549), v7.2 (10.5281/zenodo.20371440), v7.3 (10.5281/zenodo.20389899), v7.4 (10.5281/zenodo.20389909), v7.5 (10.5281/zenodo.20389914), v7.6 (10.5281/zenodo.20400025), v7.7 (10.5281/zenodo.20401671), v7.8 (10.5281/zenodo.20401819), v7.9 (10.5281/zenodo.20405611), v7.10 (10.5281/zenodo.20420866). Repository: https://github.com/akulswami/sensor-mlc-latency

[5] H. B. Mann and D. R. Whitney, "On a test of whether one of two random variables is stochastically larger than the other," *Annals of Mathematical Statistics*, vol. 18, no. 1, pp. 50–60, 1947. doi:10.1214/aoms/1177730491.

[6] J. L. Hodges and E. L. Lehmann, "Estimates of location based on rank tests," *Annals of Mathematical Statistics*, vol. 34, no. 2, pp. 598–611, 1963. doi:10.1214/aoms/1177704172.

[7] S. Holm, "A simple sequentially rejective multiple test procedure," *Scandinavian Journal of Statistics*, vol. 6, no. 2, pp. 65–70, 1979. [Online]. Available: https://www.jstor.org/stable/4615733

[8] D. J. Schuirmann, "A comparison of the two one-sided tests procedure and the power approach for assessing the equivalence of average bioavailability," *Journal of Pharmacokinetics and Biopharmaceutics*, vol. 15, no. 6, pp. 657–680, 1987. doi:10.1007/BF01068419.

[9] B. Efron, "Bootstrap methods: Another look at the jackknife," *Annals of Statistics*, vol. 7, no. 1, pp. 1–26, 1979. doi:10.1214/aos/1176344552.

[10] R. A. Fisher, *Statistical Methods for Research Workers*, 5th ed. Edinburgh: Oliver and Boyd, 1934, ch. 12. (Fisher's exact test.)

[11] B. A. Nosek, C. R. Ebersole, A. C. DeHaven, and D. T. Mellor, "The preregistration revolution," *Proceedings of the National Academy of Sciences*, vol. 115, no. 11, pp. 2600–2606, Mar. 2018. doi:10.1073/pnas.1708274114.

[12] C. I. King, "stress-ng: a tool to load and stress a computer system," version 0.13.12, 2022. [Online]. Available: https://github.com/ColinIanKing/stress-ng

[13] NVIDIA Corporation, "Jetson Orin Nano Developer Kit user guide," JetPack 6.2, 2024. [Online]. Available: https://developer.nvidia.com/embedded/jetson-orin-nano-developer-kit

[14] Saleae Inc., "Logic Pro 8 datasheet," 2024. [Online]. Available: https://www.saleae.com/products/saleae-logic-pro-8

---

## Citation map (which references appear where)

- **§I (Introduction):** [1] LSM6DSOX datasheet, [2] AN5259, [3] Razmi & Shojaei 2026, [4] pre-registration chain
- **§II.A (Background — MEMS IMUs):** [2] AN5259, [3] Razmi & Shojaei (mentions LSM6DSV16X usage)
- **§II.B (Background — safety-critical edge ML):** [2] AN5259, [3] Razmi & Shojaei
- **§II.C (Background — pre-registration):** [11] Nosek 2018
- **§III (Setup):** [4] pre-registration chain (v7.4, v7.6, v7.8), [13] Jetson Orin Nano, [14] Saleae Logic Pro 8, [12] stress-ng
- **§IV (Methodology):** [4] pre-registration chain, [5] Mann-Whitney, [6] Hodges-Lehmann, [7] Holm-Bonferroni, [8] Schuirmann TOST, [9] Efron bootstrap, [10] Fisher's exact
- **§V (Results):** [4] pre-registration chain (v7.10), [2] AN5259
- **§VI (Discussion):** [3] Razmi & Shojaei, [2] AN5259

## Notes for final paper

This bibliography uses 14 entries. IEEE Sensors Letters has no strict reference-count limit, but the 4-page format encourages brevity. Tightening pass at submission could:

1. Drop [12]-[14] (tool/platform datasheets) if URLs in main text or footnotes suffice
2. Combine [5] and [10] into a single methodological-statistics block citation
3. Consider whether [9] (bootstrap) is needed if the bootstrap is described as "standard percentile bootstrap" rather than cited

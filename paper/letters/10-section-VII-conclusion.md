# §VII. Conclusion

We measured wire-level interrupt-to-decision latency for three pipelines on a Jetson Orin Nano + LSM6DSOX edge platform. The host pipeline is consistently faster; the three-transaction I²C read, not the silicon's classification, dominates.

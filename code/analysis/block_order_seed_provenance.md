# Block-order seed provenance

This document records how the block-order seed in
`code/analysis/block_order_seed.txt` was derived.

## Method

The seed is a deterministic function of commit `8c48e19` (the
orchestrator dispatch fix). It is derived as:

```
seed = uint32(first_8_hex_chars(SHA256(commit_hash_as_string)))
```

Specifically:

- Commit hash: `8c48e19ede18a610aba09949939b25dffa5d3338`
- SHA256 of that hash (as ASCII string): `1a54ac091fe825ce627fa8851e931f13c395429766f601666b2eae49bad246a5`
- First 8 hex chars: `1a54ac09`
- Interpreted as uint32: `441756681`

## Reproducibility

The derivation can be re-verified with:

```bash
echo -n "$(git rev-parse 8c48e19)" | sha256sum | awk '{print $1}' | head -c 8
```

This should produce `1a54ac09`, which when interpreted as a hex
uint32 equals `441756681`.

## Why this derivation

Per pre-reg §7 (block-randomized order from seeded RNG), the
block-order seed must be set before any randomized data is
collected. To avoid the appearance of post-hoc seed selection
("pick the seed that produces the best results"), the seed is
derived from a commit that pre-exists the latency experiment.

Commit `8c48e19` was chosen as the anchor because it is the
orchestrator dispatch fix — the first commit that made the
latency-experiment infrastructure operationally correct. Any
randomization seeded after this commit is post-fix data.

## When this seed is used

The seed is consumed by:
- `code/orchestrator/run_stress_block.py` (Gate 4 of v7 Change 6)
  to determine the block-randomized order of the 40 blocks (10 per
  condition × 4 conditions = MLC{idle,stress} × host{idle,stress}).

The seed is read once at the start of the latency-experiment
session. It is recorded into `session.json` for audit.

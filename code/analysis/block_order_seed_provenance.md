# Block-order seed provenance

This document records how the block-order seed in
`code/analysis/block_order_seed.txt` was derived.

## Current seed (v7.5+ confirmatory campaign)

**Value:** `1990185399`

**Method:** The seed is a deterministic function of commit `f5bd702`
(the pre-reg v7.7 amendment, the commit at which all pre-flight gates
for the v7.5+ confirmatory campaign were cleared). It is derived as:
seed = uint32(first_8_hex_chars(SHA256(commit_hash_as_string)))

Specifically:
- Commit hash: `f5bd702d82818348c6f606864cf6c0d720751797`
- SHA256 of that hash (as ASCII string):
  `769fd1b776ad03f33ff081c701e8e55db2cfee4e588e4bfafe8d0186f69f987e`
- First 8 hex chars: `769fd1b7`
- Interpreted as uint32: `1990185399`

### Reproducibility

The derivation can be re-verified with:

```bash
echo -n "$(git rev-parse f5bd702)" | sha256sum | awk '{print $1}' | head -c 8
```

This should produce `769fd1b7`, which when interpreted as a hex uint32
equals `1990185399`.

### Why this commit as the anchor

Commit `f5bd702` is the v7.7 pre-registration amendment. It is the
last gate-clearing amendment before the v7.5+ confirmatory campaign:

- v7.5 (commit `206e06a`) established the campaign's 9-cell design
  (3 pipelines × 3 conditions × 500 trials per cell, vanilla
  scheduling)
- v7.6 (commit `51dd95f`) required nvpmodel MAXN_SUPER_JC for all
  confirmatory measurements
- v7.7 (commit `f5bd702`) re-specified §9 for burst protocol and
  established the §9 PASS at 95.35%/92.41% under the actual
  campaign protocol

After v7.7, all pre-flight items are cleared. Anchoring the seed
on v7.7 means it pre-dates any confirmatory data and post-dates
all design decisions. The seed is therefore neither post-hoc-
selectable nor pre-design.

### When this seed is used

The seed is consumed by the campaign-level driver (to be added)
that orchestrates the 81 blocks of the v7.5+ confirmatory campaign:

- 9 cells = 3 pipelines × 3 conditions
- 9 blocks per cell × 300 seconds per block = 9 blocks × ~60 trials/block
- Total: 81 blocks, randomly ordered via the seeded RNG, interleaved
  across all 9 cells to mitigate time-of-day / thermal drift confounds

The seed is read once at the start of the campaign and recorded in
each block's `block_metadata.json` for audit.

## Prior seed (v7-era, never used to collect data)

**Value:** `441756681` (from commit `8c48e19`)

This earlier seed was derived for the v7-era 40-block experiment design:
"10 blocks per condition × 4 conditions = MLC{idle,stress} × host{idle,stress}".
The v7-era design was superseded by v7.5's 9-cell design (Change 6 of
v7.5, Zenodo DOI 10.5281/zenodo.20389914) before any data was collected
under it. No experimental data was ever produced with the v7-era seed.

For transparency: the old seed's value and derivation are preserved
in git history (commit history of this file). The seed file's current
content (`1990185399`) replaces but does not erase the prior seed's
audit record.

The seed change from `441756681` to `1990185399` is formalized in
pre-registration amendment v7.8 (commit and Zenodo DOI to be assigned
in the same commit that updates `block_order_seed.txt`).

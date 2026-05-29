
## Journal-version debt (not blocking the Letter)
- generate_paper_figures.py hardcodes section9 accuracy + confusion-matrix values ("yesterday's results"); must be rewired to compute from section9_gate.py output and re-verified against committed data before journal submission.
- extract_latency_from_saleae.py hardcodes training session paths (2026-05-24-S4-prime/S5/S6) reading untracked saleae_timing.csv; commit that training data with the journal version or parameterize the paths.
- Training/validation CSVs (2026-05-24-S*) back the accuracy gate (journal §9); commit them when the journal accuracy section is written.
- Stacked 3x1 Fig.1 layout (readable in print) built this session but reverted for page budget; recover from history if a reviewer requests figure enlargement.

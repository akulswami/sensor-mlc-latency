
## Journal-version debt (not blocking the Letter)
- generate_paper_figures.py hardcodes section9 accuracy + confusion-matrix values ("yesterday's results"); must be rewired to compute from section9_gate.py output and re-verified against committed data before journal submission.
- extract_latency_from_saleae.py hardcodes training session paths (2026-05-24-S4-prime/S5/S6) reading untracked saleae_timing.csv; commit that training data with the journal version or parameterize the paths.
- Training/validation CSVs (2026-05-24-S*) back the accuracy gate (journal §9); commit them when the journal accuracy section is written.
- Stacked 3x1 Fig.1 layout (readable in print) built this session but reverted for page budget; recover from history if a reviewer requests figure enlargement.

## LSENS migration — IN PROGRESS (resume here)
- Migrated to IEEE_lsens.cls; compiles to 4pp clean. main_lsens.tex created; IEEE_lsens.cls copied into paper/letters/. NOT yet promoted to main.tex, NOT committed.
- RENDERING BUGS to fix before submit (introduced by class/font change, exposed by newtxmath):
  1. Literal < and > render as inverted punctuation. 4 instances: 06-section-V-results.md (host < MLC x2), 07-section-IV-methodology.md (> 0, > 1000 mW). Fix in build_tex.py: map < -> \textless{}, > -> \textgreater{}.
  2. Straight double-quotes render as right-quote both ends. 6 pairs: 04 (1), 08 (3), 09 (2). Fix: convert "..." to ``...'' in source or converter.
  3. TODO: audit ALL math symbols in new PDF under newtxmath (± ≥ ⊂ − ε △ • superscripts) — not yet verified.
- Page 4 now has free space under LSENS. DECISION PENDING: restore Efron ref / un-squash figure / restore falsification narrative — make deliberately.
- Set real \IEEELSENSarticlesubject{} category (currently placeholder "Sensor Applications") before submit.
- Clean up: remove extracted IEEE_lsens/ kit dir (keep only .cls); decide on main_lsens.tex / main_ieeetran_backup.tex.

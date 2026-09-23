# Work Log — 2026-09-21 (SENSL-26-06-RL-0906 revision, day 7 of 8)

**Goal for the day:** run the MLC-binary scheduler-affinity experiment (R1 pt.2) and capture the Saleae trace for R1 pt.3.
**End-of-day status:** measurement chain validated end-to-end *except* the Saleae D1 channel, which failed its square-wave check. The three 300-s blocks did **not** run. Diagnosis was handed off at ~14:05 with two decisive tests; outcome not yet reported.

---

## 1. Carried-over verified results (context for today's decisions)

All independently re-derived from tracked repo data earlier in this working session:

- **Table 1 fully reproduces** from raw `trials.csv` (81 confirmatory blocks under `data/training/latency-experiment/block-confirmatory-2026-05-26-b001…b081`; campaign manifest: 81/81 complete, seed 1990185399, all exit code 0).
- **R1 pt.4 audit closed:** mlc/i2c-contention 540 candidates → 8 latency exclusions (5 `multiple_d1_in_window`, 2 `multiple_d0_before_d1`, 1 `no_d1_in_window`) → **n=532** (Table 1); single-D1 stability exclusions = 6 → **n=534** (§V.A/H7′). Response-letter sentence drafted.
- **R2 p95/p99/max table computed** for all 9 cells. Two findings to handle proactively: (a) §V.B's inline "mlc/idle p95 1,780.7 µs" vs computed 1,779.7 — unify the percentile method before resubmission; (b) mlc-binary/i2c-contention has a hidden second mode (median 49.4 µs, p95 246.7 µs) — the "tight distribution under contention" narrative is overstated.
- **Energy JSON verified:** host vs mlc idle +31.1 mW [27.8, 34.4] on `VDD_CPU_GPU_CV`; +7.3 mW under contention; under stress the CIs span ±~30 mW despite p ≈ 1e-27 → **CI-primary wording is mandatory**. VDD_IN replicates (+37.3 mW). Response-letter wording locked.
- **INT1 asymmetry answered at register level** (R2's question): host pipeline `INT1_CTRL=0x01` (DRDY, 208 Hz); mlc/mlc-binary force `INT1_CTRL=0x00` with MLC routed via `MD1_CFG=0x02` (matches ST's own UCF). Drafted disclosure text for the response letter.
- **Host window = MLC window = 721.2 ms** confirmed in `parity_core.c` (`pc_step` implements 2:1 decimation) — R1 pt.1 confound dissolves to 1×, but §III.B of the manuscript must explicitly mention the decimation or the reviewer recomputes 75/208 = 360 ms.
- **Affinity baseline:** per-block mode composition of the 9 original mlc-binary idle blocks — frac_high ranges b005 0.000 → b009/b032 0.431/0.433 (block-sticky, matches hypothesis).

---

## 2. Saleae / Logic 2 setup (Asus) — COMPLETE

- Logic 2 2.4.46 AppImage installed to `/opt/saleae/Logic2`, launcher `logic2` (+ `.desktop` entry). Pitfall hit: AppImages don't self-register in the GNOME menu; launcher is the terminal command.
- Device **Logic Pro 8 Connected**, automation server enabled, port 10430.
- **`logic2-automation 1.0.11` installed into `.venv`** — the May environment's automation package had been lost; this was the fix for `ModuleNotFoundError: saleae`. Added to `requirements.txt` and committed.
- Device check prints `['6F657C15C3EEE446']` (same code path the orchestrator uses).
- Probes: D0 → Jetson pin 15 (INT1), D1 → pin 11 (intended), D2 → PCA9685 channel-0 signal pin (identified via board silkscreen + software proof: the sweep only drives channel 0 and the horn moved). **Update §5: the D1 probe is NOT actually on pin 11's net.**
- Environment rule established: invoke all project scripts with the explicit interpreter `~/sensor-mlc-latency/.venv/bin/python3` — terminal pastes have repeatedly crossed windows (fake `(.venv)` prompts, corrupted heredocs). `VIRTUAL_ENV` verified empty in the working terminal.

## 3. Affinity-experiment infrastructure — COMPLETE

- Orchestrator chain mapped: `run_campaign.py` → `run_stress_block.py --pipeline X --condition Y --duration 300` → SSH to Jetson (embedded-bank MLC0_SRC check → sync_edge → pipeline binary → servo_sweep burst 5s/5s/1s → stressor for non-idle cells → metadata).
- **`--affinity-pin` patch written, locally tested, applied, committed as `8a3a03a`** (after one corrupted heredoc paste and one misleading commit `8020d15` that was soft-reset): pipeline process pinned to core 2 via `taskset`, servo_sweep pinned to core 0, IRQ-steering attempt with `interrupts_before.txt` snapshot, `affinity_pin` field in `block_metadata.json`, default off.
- Design rationale (for the letter): pinning controls the only placement variable the platform permits.

## 4. Rig power-up sanity — COMPLETE (from rig session)

- Buses: sensor 0x6A on bus 7; UU 0x25/0x40, 0x60, 0x70 on bus 1; WHO_AM_I 0x6C. No stale processes. nvpmodel 25W (persisted). VDD_IN ~6 W, temps ~48 °C.
- **`jetson_clocks` re-applied** (lost during the long power-off): all six cores @1728 verified — must be re-applied every session; per-block jc_eff check remains the campaign rule.
- Anchor check on the cold rig: `host_pipeline_parity --tree …/tree_w75.json` → `window=75 mlc_odr=104 decim=2`, live 721.2 ms warmup. **The 104 Hz correction survives a cold boot.**
- Servo: PCA9685 re-init (PRE_SCALE 0x79, 50 Hz), continuous + burst sweeps — horn moved cleanly; 31 writes in 45 s consistent with the 5s/8s burst pattern.

## 5. Smoke block + diagnosis — INCOMPLETE (the day's crux)

**Smoke block `affinity-2026-09-21-smoke-mlc-binary-idle` (60 s) ran the full orchestrated chain successfully:** Saleae OK → MLC flash OK → silicon liveness OK → sync edge → pinned pipeline + servo → jc_eff 100.00% PASS → saved with metadata + `interrupts_before.txt`.

**But extraction: 12/12 trials excluded, all `no_d1_in_window`; t_d0/t_d1 empty.** Diagnosis path:

1. `digital.csv`: Ch2 (servo) active; **Ch1 (D1) constant 1, zero edges**; Ch0 nearly flat.
2. `pipeline.log` on the Jetson: **binary received all 12 INT1 events and toggled D1** (host_dt 14–17 µs), exit 124 (normal timeout) → DUT path healthy.
3. Foreground run: 34 events, host_dt 11–16 µs (faster than campaign unpinned modes — noted, not interpreted).
4. **IRQ diagnostic (important result):** all five matched IRQs (228, 229, 230, 244, 278) are Tegra GPIO-controller **chained interrupts**, `smp_affinity_list 0-5`, all rejecting affinity writes (EIO). irq 278 = gpio line 85 (Edge, 123K counts, **all on CPU 0**) = the INT1 handler. → IRQ placement never varied during the campaign; the affinity hypothesis reduces to process placement only, and the pinning experiment tests exactly the right variable. Two-branch interpretation pre-registered in advance of results.
5. `gpio_squarewave` (line 112 = pin 11, 100 Hz, 5 s) ran **3× clean**, no EBUSY → software line claim fine.
6. Live Logic 2 frame: **D0 shows real INT1 pulses, D2 shows servo PWM, Ch1 flat-high throughout** despite the square-wave runs → exactly one broken channel; constant-high reading points at a wrong (pulled-high neighboring) pin or an open probe lead.
7. Handed off two decisive tests at ~14:05 — **Test A:** D1 tip onto pin 15 (does the probe chain see known pulses?); **Test B:** known-good D0 probe on "pin 11" + square-wave (pin identity / off-by-two check). **Outcome not yet reported.**

### Evening update (~19:50) — smoke2 + local analysis of the uploaded capture

**Smoke2 (`affinity-2026-09-21-smoke2-mlc-binary-idle`, 60 s) ran the full chain clean again** (Saleae OK, MLC flash OK, jc_eff 100% PASS, Included: True) after pin 11 was reconfigured as GPIO. Extraction changed character: 12/12 excluded as **`multiple_d1_in_window`** (was `no_d1_in_window`) with t_d1 populated at t_stim + 20 µs. The uploaded `digital.csv`/`trials.csv` were analyzed locally:

- **Ch0 (D0/INT1) is HEALTHY:** 13 pulses — exactly one per stimulus transition, landing +0.08 to +1.68 s after each (MLC window-boundary quantization, as expected). Pulse width ~9 ms, consistent with AN5259's pulsed-mode duration (~1/104 Hz). Pin 15 / INT1 / D0 channel: proven good.
- **Ch1 is crosstalk junk, not D1:** 2,296 pulses, **median width 0.1 µs**, 50% within 0–2 ms after a PWM edge (798 within 200 µs after an INT1 edge), occurring in motion AND still phases at 16–148/s. Zero level-holds ≥ 5 ms — the binary's real D1 toggles (levels held for seconds; software side proven by pipeline.log's 12 events at host_dt 14–17 µs and the foreground run's 34 events) appear nowhere on Ch1. **Verdict: the Ch1 probe is not on pin 11's net** — floating/mis-placed, picking up capacitive glitches from PWM and INT1 wires. The pinmux change DID take effect (failure mode changed); the probe placement is the remaining fault.
- The 43.57 s / 49.22 s Ch0 bursts in the raw rows are the ~9 ms INT1 pulses plus their glitch replicas, not data traffic.

**Square-wave gate (the discriminator, sharper signature):** after re-seating the Ch1 probe on pin 11, pass = clean 5 s of 100 Hz square wave, 500 edges, **levels held ~5 ms per half-cycle**. The 100 ns glitch pulses of a floating probe look nothing like this.

### Results (~21:10) — gate PASS, all four blocks complete

- **Square-wave gate: PASS** (`~/sqw_gate.py`): 989 edges in the drive window, **500 level-holds at 5.06 ms** — D1 chain verified end-to-end after the pin-11 GPIO reconfiguration + probe re-seat. (Correction logged: header GND landmark is pin 6; pin 9 is also GND on this 40-pin header.)
- **smoke3** (60 s, pinned): 10/12 included, latencies **40.7–48.8 µs, median 47.6** — a single tight mode (campaign unpinned idle was tri-modal ~60/240/470 µs).
- **b001/b002/b003** (mlc-binary idle, 300 s, `--affinity-pin`): all complete, Included: True, jc_eff 100.00% PASS (n=3606 each).
- **mlc001** (mlc idle, 300 s, `--affinity-pin`): complete, Included: True (59/60), median 481.8 µs, tight — this `.sal` is the R1 pt.3 figure source.
- **Extraction + pre-registered mode composition (21:20):** pinned blocks **collapsed to a single mode** —
  b001 n=55 median 47.5 IQR (45.7–50.6) frac_high 0.000; b002 n=60 median 46.9 IQR (45.2–48.9) frac_high 0.000; b003 n=59 median 48.3 IQR (46.1–50.1) frac_high 0.000. **174/174 pinned trials < 150 µs vs campaign unpinned 159 low / 372 mid+high of 531** — Fisher exact OR ≈ 0, p ≈ 1.3e-71. Pre-registered criterion (frac_high ≈ 0 in ≥2/3 blocks) met in 3/3.
- **ctrl001 (same-session unpinned control), extracted 21:24: n=58, median 48.3, IQR (44.9–50.2), low=58 mid=0 high=0, frac_high=0.000.** The tri-modality did not reproduce tonight in EITHER condition. **Verdict (pre-registered Branch B): process placement is excluded as the cause of the block-sticky tri-modality.** The experiment falsified the hypothesis as designed; combined with the IRQ finding (Tegra GPIO chained interrupts non-steerable, always CPU0 — routing never varied), the systematic investigation R1 pt.2 demanded is complete: placement controlled and excluded; IRQ routing provably fixed; mode structure non-reproducing under 2026-09-21 conditions. All four Sept-21 blocks pooled: 232/232 trials < 150 µs.
- **Recorded environmental difference between sessions:** pin 11's pinmux (SFIO→GPIO reconfiguration today; state in May unknown but must have been GPIO-capable for the campaign D1 measurements to work). Listed as a suspect for the session difference, low confidence — pad parameters cannot plausibly create 240/470 µs multimodality. Alternative: May-session background-load/scheduling state. Neither affects campaign Table 1 (pre-registered, unchanged).
- **Letter framing (draft):** R1 pt.2 answered with a controlled experiment + same-session control: modes absent under both placement conditions → placement excluded; measurement shown stable (IQR ≈ 5 µs) when placement is controlled; mlc-binary median ~48 µs in rerun (favorable vs Table 1's 231.9, reported transparently, campaign data unchanged).

## 6. Notebook debts (open items)

- [ ] Commit ctrl001 `trials.csv` + push (follow-up commit to `caae886`)
- [ ] Upload b001/b002/b003/ctrl001 `trials.csv` for independent statistical verification (Fisher/MWU on full per-trial data, not aggregates)
- [ ] IRQ diagnostic output for the five IRQs (already captured above — transcribe)
- [ ] Foreground host_dt 11–16 µs observation + rerun median ~48 µs vs campaign low mode ~60 µs (notebook, don't over-interpret)
- [ ] `servo_sweep` `[1]+ Exit 1` — check sweep.log; if the sweep can die before duration, stimulus thinning must be ruled out per block
- [ ] jetson_clocks re-applied 2026-09-21; per-block jc_eff ≥ 99% rule reaffirmed
- [ ] Logic 2 install + `logic2-automation` environment drift (recorded in `requirements.txt`)
- [ ] Runbook addition: "pin 11 must be GPIO-verified every session via 100 Hz square-wave on Saleae D1 (levels held ~5 ms)"; and the general lesson: gpiod success ≠ pin driving — check the pinmux when a claimed line doesn't wiggle

## 7. Next actions (in order)

0. (done) D1 diagnosis closed; gate PASS; smoke3 verified; three pinned blocks + mlc001 + ctrl001 captured and extracted. **ctrl001 verdict: pinning excluded (Branch B).**
1. Commit ctrl001's `trials.csv` (follow-up commit to `caae886`), push:

```bash
cd ~/sensor-mlc-latency
git add data/training/latency-experiment/block-affinity-2026-09-21-ctrl001-mlc-binary-idle/trials.csv
git commit -m "affinity experiment: extract ctrl001 (unpinned same-session control); tri-modality absent, placement excluded"
git push
```

2. Upload b001/b002/b003/ctrl001 `trials.csv` for independent verification; draft the R1 pt.2 response text from the framing in §5.
3. R1 pt.3 figure from `mlc001`'s `.sal` (D0 → three I²C transactions → D1), manuscript text pass, response letter.

## 8. Today's commits

| Commit | Content |
| --- | --- |
| `8a3a03a` | orchestrator: `--affinity-pin` for R1 pt.2 (default off); env: logic2-automation |
| `caae886` (pushed) | affinity blocks: smoke ×3, pinned b001–b003, mlc001 trace block, ctrl001 raw; 46 files |
| `eea5295` (pushed) | extract ctrl001 trials.csv (unpinned same-session control; verdict: placement excluded) |

## 9. Handoff

Repo documentation update delegated to Claude Code with a pinned-spec prompt (all facts pre-verified; scope: runbook rules, DECISIONS.md, lab-notebook entry, pre-reg v7.12 addendum, `code/analysis/sqw_gate.py` from `~/sqw_gate.py`). Manuscript text (`paper/`), campaign data, and results JSONs explicitly out of scope — text pass is tomorrow's task.

**Claude verification report (21:37), six commits unpushed, DO-NOT-TOUCH confirmed clean. Resolutions:**

1. **Fisher p dispute → resolved:** scipy two-sided Fisher on the pre-registered 2×2 table [[159, 372], [174, 0]] reproduces **p = 1.266e-71** (my number). Claude's p ≈ 3.6e-89 implies a different test configuration — most plausibly a 2×3 exact test (low/mid/high). **Letter quotes the pre-registered 2×2 only: p ≈ 1.3e-71 (or conservatively p < 1e-70); never both** (p-value-shopping appearance). Note: yesterday's MWU p ≈ 8e-94 was a synthetic mode-center approximation — never quotable; real per-trial MWU pending the four uploaded trials.csv.
2. **IQR ~0.1–0.2 µs differences → interpolation methods** (Tukey hinges in the quick snippet vs pandas/numpy linear used for campaign Table 1). Recompute the four blocks' IQRs with `np.quantile(lat, [0.25, 0.75])` and amend the notebook entry.
3. **Untracked `code/tools/manual_channel_test.py`** — reviewed in VS Code screenshot (21:40): KEEPER — the observe-half of the diagnostic pair (sqw_gate drives+verifies; this watches a line), imports repo Saleae constants, correct style. Approved commit: `"tools: manual Saleae channel diagnostic (observe what a line is doing)"`.
4. Commit messages eyeballed (21:40) — all six approved as written; honest framing ("falsified", "placement excluded"), no spin. Push approved after the IQR amendment.

**Final close-out (21:42):** commit the diagnostic + Claude's np.quantile IQR amendment → push → upload four `trials.csv` → stop for the night.

**Final state (21:50):** the "mystery push" Claude flagged was Akul's own VS Code sync at 21:42 (the `manual_channel_test.py` commit `5328dde` was created from the terminal command in the 21:40 message). Everything through `5328dde` is on origin; only `3be04d3` (IQR recompute) remains unpushed — push it. Real per-trial statistics computed on the three uploaded pinned-block files, cross-verifying Claude's IQR values exactly:

- b001 n=55 median 47.5 IQR (45.7, 50.4) p95 54.0 max 95.3 | b002 n=60 median 46.9 IQR (45.2, 48.8) p95 53.4 | b003 n=59 median 48.3 IQR (46.2, 50.1) p95 53.8
- Pinned pooled n=174, median 47.4 µs, 0 trials ≥150 µs. Campaign unpinned n=531, median 231.9, 70.1% ≥150 µs.
- **MWU (real per-trial) p = 1.8e-75; Hodges-Lehmann shift −184.4 µs. Fisher 2×2 OR = 0, p = 1.27e-71** (reproduced). Letter-ready: MWU p≈1.8×10⁻⁷⁵, HL −184.4 µs; Fisher p≈1.3×10⁻⁷¹. The earlier synthetic-approximation MWU (8e-94) is superseded and never to be quoted.
- ctrl001 `trials.csv` uploaded 21:51; **all control comparisons complete (push done, origin fully synced through `3be04d3`)**: ctrl001 (n=58, median 48.3, IQR 45.0–50.2, 0 ≥150 µs, 2 `multiple_d1` exclusions) **vs campaign unpinned: MWU p = 1.1e-30, HL −184.3 µs** — same massive shift as pinned; **vs pinned pooled: MWU p = 0.673, HL +0.27 µs** — statistically indistinguishable from the pinned blocks. Arm symmetry: still→motion 47.2, motion→still 49.4. **Complete R1 pt.2 evidence chain: pinning changed nothing tonight because the modes were already absent; the tri-modality is a May-26-session property, excluded from process placement (controlled) and IRQ routing (provably constant at CPU0).**

**Deadline context:** revision due 2026-09-28; ~6 days remain. The affinity experiment and Saleae figure are the last rig-gated items; everything else is desk work (manuscript text pass, response letter, p95/p99/max table insertion, graphical-abstract qualifier).

**Day closed 21:55. All four trials.csv analyzed; origin/main = `3be04d3`; log final.**

## 10. mlc001 intent clarification (2026-09-22)

mlc001 (mlc bank-switch pipeline, 300 s, --affinity-pin) was DELIBERATE
opportunistic bundling, not a scope expansion of the pre-registered R1 pt.2
design (which is exclusively mlc-binary x {pinned, unpinned}, complete with
ctrl001). Primary purpose: R1 pt.3 Saleae trace (D0 -> three I2C transactions
-> D1) — only the mlc pipeline does the embedded-bank read, so an mlc run was
required regardless; the --affinity-pin flag was free.

GUARDRAIL: mlc001 is never evidence in the R1 pt.2 argument (different
pipeline, pinned, no unpinned mlc control). Sanctioned letter role: figure
source only. Its latency numbers (median 481.8 us vs campaign mlc idle 681.5)
are CONFOUNDED (session vs pinning) — either omit them from the letter
(default recommendation) or deconfound with an unpinned mlc control block
(ctrl002, ~6 min, share the PPK2 session) before mentioning them.

## 11. Integrity loop closed (2026-09-22)

v7.12 "pre-registered branches" characterization corrected. v7.12 Zenodo DOI
10.5281/zenodo.22907481 (minted one day post-commit, gap recorded); v7.13
(f2595fa, DOI 10.5281/zenodo.22907600 same-day) restates branches as
pre-specified working-log criteria (13:41 PDT, verbatim quote archived at
docs/lab-notebook/2026-09-21-affinity-experiment-analysis-branches.md) and
adds the standing rule: analysis criteria must be chain-committed and
Zenodo-timestamped BEFORE the data they interpret, or be labeled post-hoc.
STANDING WORKFLOW RULE: no multi-line content via terminal paste (3
corruption events in 2 days) — file transfer or VS Code editor for bulk
text; terminal for git/commands only.
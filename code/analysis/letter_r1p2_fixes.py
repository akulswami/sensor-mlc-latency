#!/usr/bin/env python3
"""
letter_r1p2_fixes.py — two letter-only corrections to the R1P2 response,
adjudicated by verify_letter_stats.py against raw data:

  E1  "232/232 trials with the process pinned" -> "174/174 trials ..."
      Raw data: pinned blocks b001+b002+b003 = 55+60+59 = 174 included
      trials. The 232 figure is the POOLED count across pinned + the
      same-session unpinned control (174+58=232), correctly described as
      pooled in docs/pre-registration.md:2659 and
      docs/lab-notebook/2026-09-21-affinity-experiment.md:68. The letter
      sentence conflated the pooled count with the pinned subset, and is
      inconsistent with its own MWU/HL (computed on the 174).
  E2  "..., ruling out session-to-session drift as a confound."
      -> "; pinning had no measurable effect in this session."
      The control logic was inverted: ctrl001 (unpinned, same session)
      showing no difference from pinned (p=0.673) means the May anomaly
      did NOT reproduce in September regardless of pinning — the result
      REMOVES support from pinning and leaves session differences as the
      leading explanation. The letter's own next sentence ("Process
      affinity is not supported by the follow-up data...") already says
      this; the clause contradicted it.

No manuscript files touched; no 4-page risk. Response PDF rebuilt inline
(same pdflatex + unicode-header machinery as letter_final_fixes.py).

Pre-flight re-proves the counts from raw trials.csv and from the
historical documents before anything is written.

Usage:  python3 letter_r1p2_fixes.py
"""
import csv
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

TS = datetime.now().strftime("%Y%m%d-%H%M%S")


def sh(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)


# ---------------- locate repo ----------------
candidates = sh(["find", str(Path.home()), "-maxdepth", "8", "-name",
                 "05-section-III-setup.md", "-path", "*paper/letters*"]).stdout.split()
hits = [h for h in candidates
        if "arxiv_build" not in h and ".bak" not in h
        and "Downloads" not in h and "extract" not in h]
if len(hits) != 1:
    sys.exit(f"ABORT: expected exactly 1 setup file, got {len(hits)}: {hits}")
LETTERS = Path(hits[0]).parent
REPO = LETTERS.parent.parent
LETTER = REPO / "docs/lab-notebook/response-to-reviewers-SENSL-26-06-RL-0906.md"
RESP_PDF = LETTERS / "response-to-reviewers-SENSL-26-06-RL-0906.pdf"
LAT = REPO / "data/training/latency-experiment"
print(f"repo: {REPO}")

E1_OLD = "232/232 trials with the process pinned to a fixed CPU core fell under 150 µs"
E1_NEW = "174/174 trials with the process pinned to a fixed CPU core fell under 150 µs"
E2_OLD = ("showed no difference from the pinned blocks (p = 0.673), "
          "ruling out session-to-session drift as a confound.")
E2_NEW = ("showed no difference from the pinned blocks (p = 0.673); "
          "pinning had no measurable effect in this session.")

text = LETTER.read_text(encoding="utf-8")

# ---------------- re-prove counts from raw data ----------------
def included_n(block_dir):
    with open(block_dir / "trials.csv", newline="") as f:
        return sum(1 for r in csv.DictReader(f)
                   if (r.get("included") or "").strip() == "True")


pinned_dirs = sorted(LAT.glob("block-affinity-2026-09-21-b00[123]-*"))
ctrl_dirs = sorted(LAT.glob("block-affinity-2026-09-21-ctrl001-*"))
if len(pinned_dirs) != 3 or len(ctrl_dirs) != 1:
    sys.exit(f"ABORT: expected 3 pinned + 1 control block dirs, got "
             f"{len(pinned_dirs)} + {len(ctrl_dirs)}")
n_pin = sum(included_n(d) for d in pinned_dirs)
n_ctrl = included_n(ctrl_dirs[0])
print(f"raw data: pinned b001-b003 = {n_pin} included trials; "
      f"ctrl001 = {n_ctrl}; pooled = {n_pin + n_ctrl}")

AFF_DOC = REPO / "docs/lab-notebook/2026-09-21-affinity-experiment.md"
SUM_DOC = REPO / "docs/lab-notebook/2026-09-21-session-summary.md"
aff_text = AFF_DOC.read_text(encoding="utf-8") if AFF_DOC.exists() else ""
sum_text = SUM_DOC.read_text(encoding="utf-8") if SUM_DOC.exists() else ""

# ---------------- pre-flight ----------------
preflight = [
    (text.count(E1_OLD) == 1, "E1 anchor unique"),
    (text.count(E2_OLD) == 1, "E2 anchor unique"),
    (n_pin == 174, f"raw pinned count == 174 (got {n_pin})"),
    (n_ctrl == 58, f"raw control count == 58 (got {n_ctrl})"),
    (n_pin + n_ctrl == 232, "174 + 58 == 232 (pooled count explained)"),
    ("55+60+59+58=232" in aff_text.replace(" ", ""),
     "affinity-experiment.md documents 232 as the pooled four-block count"),
    ("did not reproduce tonight in EITHER condition" in sum_text,
     "session-summary.md documents non-reproduction in both conditions"),
]
for ok, msg in preflight:
    if not ok:
        sys.exit(f"ABORT pre-flight: {msg}")
print("pre-flight OK (anchors unique; counts re-proven from raw data + historical docs)")

# ---------------- backups + apply ----------------
for f in (LETTER, RESP_PDF):
    if f.exists():
        shutil.copy2(f, f.with_name(f.name + f".bak-{TS}"))
for old, new, label in ((E1_OLD, E1_NEW, "E1 232/232 -> 174/174 (pinned subset)"),
                        (E2_OLD, E2_NEW, "E2 de-invert control logic")):
    text = LETTER.read_text(encoding="utf-8")
    LETTER.write_text(text.replace(old, new), encoding="utf-8")
    print(f"OK {label}")

# ---------------- rebuild response PDF (pdflatex-first, fail-loud) ----------------
UNICODE_HEADER = r"""
\usepackage{textcomp}
\DeclareUnicodeCharacter{00B1}{\textpm}
\DeclareUnicodeCharacter{00B5}{\textmu}
\DeclareUnicodeCharacter{00B2}{\textsuperscript{2}}
\DeclareUnicodeCharacter{00B3}{\textsuperscript{3}}
\DeclareUnicodeCharacter{00B9}{\textsuperscript{1}}
\DeclareUnicodeCharacter{00D7}{\texttimes}
\DeclareUnicodeCharacter{2013}{--}
\DeclareUnicodeCharacter{2014}{---}
\DeclareUnicodeCharacter{2018}{`}
\DeclareUnicodeCharacter{2019}{'}
\DeclareUnicodeCharacter{201C}{``}
\DeclareUnicodeCharacter{201D}{''}
\DeclareUnicodeCharacter{2026}{\dots}
\DeclareUnicodeCharacter{2032}{$'$}
\DeclareUnicodeCharacter{2070}{\textsuperscript{0}}
\DeclareUnicodeCharacter{2074}{\textsuperscript{4}}
\DeclareUnicodeCharacter{2075}{\textsuperscript{5}}
\DeclareUnicodeCharacter{2076}{\textsuperscript{6}}
\DeclareUnicodeCharacter{2077}{\textsuperscript{7}}
\DeclareUnicodeCharacter{2078}{\textsuperscript{8}}
\DeclareUnicodeCharacter{2079}{\textsuperscript{9}}
\DeclareUnicodeCharacter{207B}{$^{-}$}
\DeclareUnicodeCharacter{2212}{$-$}
\DeclareUnicodeCharacter{2248}{$\approx$}
\DeclareUnicodeCharacter{2260}{$\neq$}
\DeclareUnicodeCharacter{2264}{$\leq$}
\DeclareUnicodeCharacter{2265}{$\geq$}
\DeclareUnicodeCharacter{03B5}{$\varepsilon$}
\DeclareUnicodeCharacter{00A7}{\S}
"""
hdr = LETTERS / f".pandoc-unicode-{TS}.tex"
hdr.write_text(UNICODE_HEADER, encoding="utf-8")
r = sh(["pandoc", str(LETTER), "-o", str(RESP_PDF), "--pdf-engine=pdflatex",
        "-H", str(hdr), "-V", "geometry:margin=1in", "-V", "fontsize=11pt"],
       cwd=LETTERS)
if r.returncode != 0 or not RESP_PDF.exists():
    sys.exit(f"ABORT: pandoc rebuild failed:\n{r.stderr[-1500:]}")

pdf_text = sh(["pdftotext", str(RESP_PDF), "-"]).stdout
final_text = LETTER.read_text(encoding="utf-8")
post = [
    ("174/174 trials with the process pinned" in final_text, "E1 in letter source"),
    ("232/232" not in final_text, "E1 old count gone from letter"),
    ("pinning had no measurable effect in this session" in final_text,
     "E2 in letter source"),
    ("ruling out session-to-session drift" not in final_text, "E2 old clause gone"),
    ("174/174 trials with the process pinned" in pdf_text, "E1 in response PDF"),
    ("pinning had no measurable effect in this session" in pdf_text,
     "E2 in response PDF"),
]
all_ok = True
for ok, msg in post:
    print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
    all_ok = all_ok and ok
if not all_ok:
    sys.exit("ABORT: post-check failed — do NOT commit; inspect first.")

print("\nDONE. Commit exactly these two files:")
print("  git add docs/lab-notebook/response-to-reviewers-SENSL-26-06-RL-0906.md \\")
print("          paper/letters/response-to-reviewers-SENSL-26-06-RL-0906.pdf")

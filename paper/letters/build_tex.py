#!/usr/bin/env python3
"""Assemble paper/letters/main.tex from the committed markdown section files.
Prose is taken verbatim from the .md files (with markdown->LaTeX conversion)
so the PDF reflects exactly what is committed, not a retyped copy."""
import re, os, sys

LETTERS = os.path.dirname(os.path.abspath(__file__))

def md_inline_to_tex(s):
    # Order matters. Protect LaTeX specials first (but keep math-ish µ etc via inputenc).
    # Escape characters that are special in LaTeX text mode.
    # We do NOT escape $ % & _ # inside already-bracketed citations later; handle generally.
    s = s.replace('\\', r'\textbackslash{}')
    for ch in ['&', '%', '#', '_']:
        s = s.replace(ch, '\\' + ch)
    # bold **x** -> \textbf{x}
    s = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', s)
    # italic *x* -> \emph{x}  (after bold so ** already consumed)
    s = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\\emph{\1}', s)
    # inline code `x` -> \texttt{x}
    s = re.sub(r'`(.+?)`', r'\\texttt{\1}', s)
    # citations [1] or [2, 3] -> \cite{ref1} / \cite{ref2,ref3}
    def cite_sub(m):
        nums = [n.strip() for n in m.group(1).split(',')]
        return '\\cite{' + ','.join('ref'+n for n in nums) + '}'
    s = re.sub(r'\[(\d+(?:\s*,\s*\d+)*)\]', cite_sub, s)
    # inline section cross-refs: §V.B -> Section~V-B, §V -> Section~V
    s = re.sub(r'§([IVX]+)\\.([A-Z])', r'Section~\1-\2', s)
    s = re.sub(r'§([IVX]+)', r'Section~\1', s)
    # Unicode -> LaTeX (pdflatex-safe), authoritative map (all 19 codepoints).
    # First: collapse superscript runs (p-value exponents) into \textsuperscript{...}.
    sup = {'\u207b':'-','\u00b9':'1','\u2070':'0','\u00b2':'2','\u00b3':'3',
           '\u2074':'4','\u2075':'5','\u2076':'6','\u2077':'7','\u2078':'8','\u2079':'9'}
    def sup_run(m):
        return r'\textsuperscript{' + ''.join(sup[c] for c in m.group(0)) + '}'
    s = re.sub('[' + ''.join(sup.keys()) + ']+', sup_run, s)
    # Then single-char substitutions
    s = s.replace('\u00b5', r'$\mu$')        # µ micro (always µs)
    uni = {
        '\u2014': r'---',                    # — em dash
        '\u2013': r'--',                     # – en dash
        '\u2212': r'$-$',                    # − true minus
        '\u00d7': r'$\times$',               # ×
        '\u00a7': r'',                       # § (shouldn't reach body; strip if so)
        '\u0394': r'$\Delta$',               # Δ
        '\u00b1': r'$\pm$',                  # ±
        '\u2265': r'$\geq$',                 # ≥
        '\u2264': r'$\leq$',                 # ≤
        '\u2282': r'$\subset$',              # ⊂
        '\u03b1': r'$\alpha$',               # α
        '\u03b5': r'$\varepsilon$',          # ε
        '\u2192': r'$\rightarrow$',          # →
        '\u201c': r'``', '\u201d': r"''",
        '\u2018': r'`',  '\u2019': r"'",
        '\u2032': r"'",
        '<': r'\textless{}',           # < literal (breaks under newtxmath)
        '>': r'\textgreater{}',        # > literal
    }
    for k, v in uni.items():
        s = s.replace(k, v)
    # Straight double-quotes -> LaTeX open/close (converter already maps curly;
    # source uses straight " which else renders as '' both ends).
    def pair_quotes(text):
        out = []
        open_q = True
        for c in text:
            if c == '"':
                out.append('``' if open_q else "''")
                open_q = not open_q
            else:
                out.append(c)
        return ''.join(out)
    s = pair_quotes(s)
    # Fig./Table bold refs already handled by **; leave as text
    return s

def convert_section(path):
    out = []
    with open(path) as f:
        lines = f.read().split('\n')
    for ln in lines:
        if not ln.strip():
            out.append('')
            continue
        # Headers
        m = re.match(r'^#\s+(.*)', ln)
        if m and ln.startswith('# '):
            title = m.group(1)
            # strip leading "§N. " or "Section N:" to get clean section name
            title = re.sub(r'^§?[IVX]+\.?\s*', '', title)
            title = re.sub(r'^Section\s+[IVX]+:?\s*', '', title, flags=re.I)
            out.append(r'\section{%s}' % md_inline_to_tex(title))
            continue
        m = re.match(r'^##\s+(.*)', ln)
        if m:
            title = m.group(1)
            title = re.sub(r'^[IVX]+\.[A-Z]?\s*', '', title)
            out.append(r'\subsection{%s}' % md_inline_to_tex(title))
            continue
        # skip italic annotation lines like *(Target ...)* or *(IEEE ...)*
        if re.match(r'^\*\(.*\)\*\s*$', ln):
            continue
        # bullet
        if ln.lstrip().startswith('- '):
            out.append(r'\item ' + md_inline_to_tex(ln.lstrip()[2:]))
            continue
        out.append(md_inline_to_tex(ln))
    # Wrap runs of consecutive \item lines in itemize environments
    wrapped = []
    in_list = False
    for line in out:
        is_item = line.lstrip().startswith(r'\item')
        if is_item and not in_list:
            wrapped.append(r'\begin{itemize}')
            in_list = True
        elif not is_item and in_list and line.strip() != '':
            wrapped.append(r'\end{itemize}')
            in_list = False
        wrapped.append(line)
    if in_list:
        wrapped.append(r'\end{itemize}')
    return '\n'.join(wrapped)

# Section order in the paper
order = [
    '04-section-I-introduction.md',
    '09-section-II-background.md',
    '05-section-III-setup.md',
    '07-section-IV-methodology.md',
    '06-section-V-results.md',
    '08-section-VI-discussion.md',
    '10-section-VII-conclusion.md',
]

body = '\n\n'.join(convert_section(os.path.join(LETTERS, f)) for f in order)

# Inject Fig.1 + Table I floats immediately after their first reference in §V
import os as _os
_fig = open(_os.path.join(LETTERS, "_float_fig1.tex")).read()
_tab = open(_os.path.join(LETTERS, "_float_tableI.tex")).read()
_ref_sentence = r"summary statistics in \textbf{Table I}."
if _ref_sentence in body:
    body = body.replace(_ref_sentence, _ref_sentence + "\n\n" + _fig + "\n\n" + _tab, 1)
else:
    # fallback: append at end if anchor sentence not found
    body = body + "\n\n" + _fig + "\n\n" + _tab
    print("WARN: V-ref sentence not found; floats appended at end")


# Abstract (strip headers/annotations, take the prose paragraph)
with open(os.path.join(LETTERS, '03-abstract.md')) as f:
    abs_lines = [l for l in f.read().split('\n')
                 if l.strip() and not l.startswith('#')
                 and not re.match(r'^\*\(', l)]
abstract = md_inline_to_tex(' '.join(abs_lines))

print("BODY_WORDS:", len(re.findall(r'\w+', body)))
with open(os.path.join(LETTERS, '_body.tex'), 'w') as f:
    f.write(body)
with open(os.path.join(LETTERS, '_abstract.tex'), 'w') as f:
    f.write(abstract)
print("Wrote _body.tex and _abstract.tex")

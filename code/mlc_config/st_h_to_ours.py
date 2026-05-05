#!/usr/bin/env python3
"""
st_h_to_ours.py

Converts an STMicroelectronics-style MLC config header to the format
expected by latency_test_mlc.c in this repository.

ST format (input):
    typedef struct {
      uint8_t address;
      uint8_t data;
    } ucf_line_t;
    const ucf_line_t lsm6dsox_<name>[] = {
      {.address = 0x10, .data = 0x00,},
      ...
    };

Our format (output):
    typedef struct { uint8_t reg; uint8_t val; } mlc_write_t;
    static const mlc_write_t MLC_CONFIG[] = {
        { 0x10, 0x00 },
        ...
    };
    #define MLC_CONFIG_LEN (N)
    #define MLC_OUT_NONTAP <user-supplied>
    #define MLC_OUT_TAP    <user-supplied>

Usage:
    python3 st_h_to_ours.py INPUT.h OUTPUT.h NAME NONTAP TAP

Where:
    INPUT.h  : ST-format header
    OUTPUT.h : our-format header to write
    NAME     : symbol prefix for the include guard (e.g. activity_mobile)
    NONTAP   : class code for "not the positive class" (hex, e.g. 0x00)
    TAP      : class code for "the positive class" (hex, e.g. 0x01)

For the activity_recognition_for_mobile config and a binary motion-vs-still
task, NONTAP = 0x00 (Stationary) and TAP is whichever motion class we're
treating as canonical "motion." But because ANY non-zero output is motion,
the host code handles this with `mlc_src != 0` rather than equality on a
single class code -- so the TAP define here is purely informational and
not used as an equality check in latency_test_mlc.c.

Verification: after conversion, the byte sequence in OUTPUT.h must be
identical to INPUT.h's byte sequence. We assert this by re-extracting and
comparing.
"""

from __future__ import annotations
import re
import sys
import os


ST_PAIR_RE = re.compile(
    r"\{\s*\.address\s*=\s*0x([0-9A-Fa-f]{2})\s*,\s*\.data\s*=\s*0x([0-9A-Fa-f]{2})\s*,?\s*\}"
)


def parse_st_h(text: str) -> list[tuple[int, int]]:
    pairs = []
    for m in ST_PAIR_RE.finditer(text):
        pairs.append((int(m.group(1), 16), int(m.group(2), 16)))
    return pairs


def emit_our_h(pairs: list[tuple[int, int]], name: str,
               nontap: int, tap: int, source_path: str) -> str:
    guard = f"MLC_{name.upper()}_H"
    lines = [
        f"/* Auto-converted from {os.path.basename(source_path)}",
        f" * by st_h_to_ours.py.",
        f" * Source format: STMicroelectronics ucf_line_t (.address/.data fields).",
        f" * Output format: mlc_write_t (reg/val fields, unnamed-init style).",
        f" * Do not hand-edit; re-run the converter to regenerate. */",
        f"#ifndef {guard}",
        f"#define {guard}",
        "",
        "#include <stdint.h>",
        "#include <stddef.h>",
        "",
        "typedef struct { uint8_t reg; uint8_t val; } mlc_write_t;",
        "",
        "static const mlc_write_t MLC_CONFIG[] = {",
    ]
    for reg, val in pairs:
        lines.append(f"    {{ 0x{reg:02X}, 0x{val:02X} }},")
    lines.append("};")
    lines.append("")
    lines.append(f"#define MLC_CONFIG_LEN ({len(pairs)})")
    lines.append("")
    lines.append("/* Output class codes (read from MLC0_SRC, register 0x70) */")
    lines.append(f"#define MLC_OUT_NONTAP 0x{nontap:02X}")
    lines.append(f"#define MLC_OUT_TAP    0x{tap:02X}")
    lines.append("")
    lines.append(f"#endif /* {guard} */")
    lines.append("")
    return "\n".join(lines)


def parse_our_h(text: str) -> list[tuple[int, int]]:
    """Parse the format we just emitted, for verification."""
    our_re = re.compile(
        r"\{\s*0x([0-9A-Fa-f]{2})\s*,\s*0x([0-9A-Fa-f]{2})\s*\}"
    )
    return [(int(m.group(1), 16), int(m.group(2), 16))
            for m in our_re.finditer(text)]


def main():
    if len(sys.argv) != 6:
        print(__doc__, file=sys.stderr)
        sys.exit(2)

    in_path, out_path, name, nontap_s, tap_s = sys.argv[1:6]
    nontap = int(nontap_s, 16) if nontap_s.startswith("0x") else int(nontap_s)
    tap    = int(tap_s,    16) if tap_s.startswith("0x")    else int(tap_s)

    with open(in_path) as f:
        in_text = f.read()
    in_pairs = parse_st_h(in_text)
    if not in_pairs:
        print(f"ERROR: no register pairs found in {in_path}.", file=sys.stderr)
        sys.exit(1)
    print(f"Parsed {len(in_pairs)} register writes from {in_path}")

    out_text = emit_our_h(in_pairs, name, nontap, tap, in_path)

    # Verification: round-trip parse the output and confirm identical sequence.
    out_pairs = parse_our_h(out_text)
    if out_pairs != in_pairs:
        print("ERROR: round-trip verification failed.", file=sys.stderr)
        print(f"  input  pairs: {len(in_pairs)}", file=sys.stderr)
        print(f"  output pairs: {len(out_pairs)}", file=sys.stderr)
        # Show first divergence
        for i, (a, b) in enumerate(zip(in_pairs, out_pairs)):
            if a != b:
                print(f"  divergence at index {i}: in={a}, out={b}",
                      file=sys.stderr)
                break
        sys.exit(1)
    print(f"Round-trip verification: OK (byte-identical sequence)")

    with open(out_path, "w") as f:
        f.write(out_text)
    print(f"Wrote {len(in_pairs)} writes to {out_path}")
    print(f"  MLC_OUT_NONTAP = 0x{nontap:02X}")
    print(f"  MLC_OUT_TAP    = 0x{tap:02X}")


if __name__ == "__main__":
    main()

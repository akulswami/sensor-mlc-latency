#!/usr/bin/env python3
"""
Convert MEMS Studio mlc_*.json output to a C header file
containing a static array of (reg, val) writes.

Usage: python3 json_to_header.py mlc_accuracy.json mlc_accuracy.h
"""
import json, sys

if len(sys.argv) != 3:
    print("Usage: json_to_header.py <input.json> <output.h>", file=sys.stderr)
    sys.exit(1)

infile, outfile = sys.argv[1], sys.argv[2]

with open(infile) as f:
    data = json.load(f)

# Get the configuration writes
sensor = data['sensors'][0]
writes = sensor['configuration']

# Get the output mapping
outputs = sensor['outputs'][0]
results = outputs['results']
class_codes = {}
for r in results:
    class_codes[r['label']] = int(r['code'], 16)

# Generate header
guard = outfile.upper().replace('.H', '_H').replace('-', '_').replace('/', '_')
guard = ''.join(c for c in guard if c.isalnum() or c == '_')

with open(outfile, 'w') as f:
    f.write(f"/* Auto-generated from {infile} */\n")
    f.write(f"#ifndef {guard}\n#define {guard}\n\n")
    f.write("#include <stdint.h>\n#include <stddef.h>\n\n")
    f.write("typedef struct { uint8_t reg; uint8_t val; } mlc_write_t;\n\n")

    f.write(f"static const mlc_write_t MLC_CONFIG[] = {{\n")
    for w in writes:
        if w['type'] == 'write':
            reg = int(w['address'], 16)
            val = int(w['data'], 16)
            f.write(f"    {{ 0x{reg:02X}, 0x{val:02X} }},\n")
    f.write("};\n\n")
    f.write(f"#define MLC_CONFIG_LEN ({len(writes)})\n\n")

    f.write("/* Output class codes (read from MLC0_SRC, register 0x70) */\n")
    for label, code in class_codes.items():
        # Sanitize label for C macro
        macro = ''.join(c.upper() if c.isalnum() else '_' for c in label)
        f.write(f"#define MLC_OUT_{macro} 0x{code:02X}\n")

    f.write(f"\n#endif /* {guard} */\n")

print(f"Wrote {outfile} ({len(writes)} register writes)")

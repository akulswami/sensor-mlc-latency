#!/usr/bin/env python3
"""
i2c_window_decode.py — On-wire I2C verification and latency decomposition for the
LSM6DSOX MLC three-transaction bank-switch read (manuscript SENSL-26-06-RL-0906).

Decodes Saleae digital CSV exports (50 MS/s, channels: 0=INT1, 1=decision GPIO,
2=servo PWM, 3=SDA, 4=SCL) and verifies, per decision window anchored on each
INT1 rising edge, the complete protocol sequence:

    W [0x01, 0x80]   FUNC_CFG_ACCESS: embedded-functions bank ON
    W [0x70] + Sr    register pointer MLC0_SRC, repeated-start combined read
    R         ->     MLC0_SRC value (0x04 = motion, 0x00 = still)
    W [0x01, 0x00]   bank OFF

Outputs one CSV row per decision window: sched_ms (INT1 rise -> first byte),
triple_ms (first START -> last STOP), strobe_ms (last STOP -> decision GPIO),
d0_d1_ms (INT1 rise -> decision GPIO), mlc0_src value, triple_ok flag.

Stdlib only (no pandas/numpy). Two modes:

  Full-block (idle/stress blocks, digital.csv < ~100 MB):
    python3 i2c_window_decode.py full <block_dir> -o out.csv

  Windowed (i2c-contention blocks with multi-GB digital.csv):
    # 1. extract D0/D1 transition rows:
    awk -F, 'NR==1{print;next} $2!=p2 || $3!=p3 {print; p2=$2; p3=$3}' digital.csv > d0d1.csv
    # 2. derive windows:
    awk -F, 'NR==1{next} {t=$1+0; c0=$2+0; if(c0!=p){ if(c0==1){r=t} else \
        {if(t-r>0.005) printf "%.7f,%.7f\n", r-0.0003, r+0.004} p=c0 } }' d0d1.csv | sort -n > windows.txt
    # 3. extract window rows:
    awk -F, 'NR==FNR{lo[NR]=$1;hi[NR]=$2;n=NR;next} FNR==1{print;next} \
        {t=$1+0; for(i=1;i<=n;i++) if(t>=lo[i]&&t<=hi[i]){print;break}}' windows.txt digital.csv > windows.csv
    # 4. decode:
    python3 i2c_window_decode.py windows <block_dir> --windows-csv windows.csv -o out.csv

Reference: pre-registration v7.6 (2026-05-26), Zenodo DOI 10.5281/zenodo.20400025.
Capture configuration: Saleae Logic Pro 8, 50 MS/s, 3.3V+ threshold, 200 ns glitch
filters on SDA/SCL (see docs/lab-notebook/2026-09-24-sda-scl-capture-plan.md).
"""
import argparse
import csv
import os
import sys

# INT1 pulses are fixed-width (~9.01 ms at MLC ODR 104 Hz); anything narrower
# than 5 ms is threshold/coupling glitch on the open-drain line.
MIN_PULSE_S = 0.005
WIN_PRE_S = 0.0003
WIN_POST_S = 0.004
DESPIKE_S = 5e-8  # 50 ns < 200 ns GUI glitch filter; raw export is unfiltered

SENSOR_ADDR = 0x6A
BANK_ON = [0x01, 0x80]
REG_MLC0_SRC = [0x70]
BANK_OFF = [0x01, 0x00]


def load_csv(path):
    with open(path, newline="") as f:
        r = csv.reader(f)
        next(r)
        return [[float(x) for x in row] for row in r]


def channel_edges(data, ch):
    out = []
    p = data[0][1 + ch]
    for row in data[1:]:
        if row[1 + ch] != p:
            out.append((row[0], int(p), int(row[1 + ch])))
            p = row[1 + ch]
    return out


def build_windows(data):
    """One window per INT1 pulse: last rise before a fall >= MIN_PULSE_S later."""
    wins = []
    r_ = None
    for t, a, b in channel_edges(data, 0):
        if b == 1:
            r_ = t
        else:
            if r_ is not None and t - r_ > MIN_PULSE_S:
                wins.append((r_ - WIN_PRE_S, r_ + WIN_POST_S, r_))
            r_ = None
    return wins


def decode_i2c(winrows):
    """Decode I2C frames from transition rows (cols: t, ch0..ch4; ch3=SDA, ch4=SCL)."""
    scl = [(r[0], int(r[5])) for r in winrows]
    sda = [(r[0], int(r[4])) for r in winrows]

    def edges(s):
        return [(s[i][0], s[i][1]) for i in range(1, len(s)) if s[i][1] != s[i - 1][1]]

    def despike(ev):
        out = []
        for t, v in ev:
            if out and t - out[-1][0] < DESPIKE_S:
                out.pop()
            else:
                out.append((t, v))
        return out

    se, de = despike(edges(scl)), despike(edges(sda))
    events = sorted([(t, "c", v) for t, v in se] + [(t, "d", v) for t, v in de])
    cv, dv = int(winrows[0][5]), int(winrows[0][4])
    frames, cur = [], None
    for t, sig, v in events:
        if sig == "d":
            if cv == 1:
                if v == 0:  # START / repeated START
                    if cur is not None and cur["bits"]:
                        frames.append(cur)
                    cur = {"start_t": t, "bits": [], "stop_t": None}
                else:  # STOP
                    if cur is not None:
                        cur["stop_t"] = t
                        frames.append(cur)
                        cur = None
            dv = v
        else:
            if v == 1 and cur is not None:
                cur["bits"].append(dv)
            cv = v
    if cur is not None and cur["bits"]:
        cur["stop_t"] = events[-1][0] if events else None
        frames.append(cur)
    out = []
    for f in frames:
        nb = len(f["bits"]) // 9
        if nb == 0:
            continue
        byts = []
        for i in range(nb):
            b = 0
            for bit in f["bits"][i * 9:i * 9 + 8]:
                b = (b << 1) | bit
            byts.append((b, 0 if f["bits"][i * 9 + 8] == 0 else 1))
        out.append({"start_t": f["start_t"], "stop_t": f["stop_t"], "bytes": byts,
                    "addr": byts[0][0] >> 1, "rw": byts[0][0] & 1})
    return out


def verify_window(wr, d0):
    frames = decode_i2c(wr)
    d1 = None
    p = wr[0][2]
    for row in wr[1:]:
        if row[2] != p:
            if row[2] == 1.0:
                d1 = row[0]
                break
            p = row[2]

    def is_w(f, data):
        return f["rw"] == 0 and [b for b, a in f["bytes"][1:]] == data

    t1i = next((k for k, f in enumerate(frames)
                if f["addr"] == SENSOR_ADDR and is_w(f, BANK_ON)), None)
    if t1i is None:
        return {"triple_ok": 0, "why": "no bank-on write"}
    t2i = next((k for k in range(t1i + 1, len(frames))
                if frames[k]["addr"] == SENSOR_ADDR and is_w(frames[k], REG_MLC0_SRC)), None)
    if t2i is None:
        return {"triple_ok": 0, "why": "no MLC0_SRC pointer write"}
    if t2i + 1 >= len(frames) or frames[t2i + 1]["rw"] != 1 or frames[t2i + 1]["addr"] != SENSOR_ADDR:
        return {"triple_ok": 0, "why": "pointer write not followed by read"}
    read = frames[t2i + 1]["bytes"][1][0] if len(frames[t2i + 1]["bytes"]) > 1 else None
    t3i = next((k for k in range(t2i + 2, len(frames))
                if frames[k]["addr"] == SENSOR_ADDR and is_w(frames[k], BANK_OFF)), None)
    if t3i is None:
        return {"triple_ok": 0, "why": "no bank-off write"}
    t1s = frames[t1i]["start_t"]
    t3e = frames[t3i]["stop_t"] or frames[t3i]["start_t"]
    trip = {t1i, t2i, t2i + 1, t3i}
    return {
        "triple_ok": 1,
        "mlc0_src": f"0x{read:02X}" if read is not None else "",
        "sched_ms": round((t1s - d0) * 1e3, 4),
        "triple_ms": round((t3e - t1s) * 1e3, 4),
        "strobe_ms": round((d1 - t3e) * 1e3, 4) if d1 else "",
        "d0_d1_ms": round((d1 - d0) * 1e3, 4) if d1 else "",
        "hammer_inside_triple": sum(1 for j in range(t1i, t3i + 1) if j not in trip),
        "frames_in_window": len(frames),
    }


def run(block_dir, windows_csv, out_path):
    if windows_csv:
        data = load_csv(windows_csv)
        d0d1 = os.path.join(block_dir, "d0d1.csv")
        if not os.path.exists(d0d1):
            sys.exit(f"windowed mode needs {d0d1} for window anchors")
        wins = build_windows(load_csv(d0d1))
        win_rows = [[] for _ in wins]
        wi = 0
        for row in data:
            t = row[0]
            while wi < len(wins) and t > wins[wi][1]:
                wi += 1
            if wi < len(wins) and wins[wi][0] <= t <= wins[wi][1]:
                win_rows[wi].append(row)
    else:
        data = load_csv(os.path.join(block_dir, "digital.csv"))
        wins = build_windows(data)
        win_rows = []
        for lo, hi, _ in wins:
            win_rows.append([row for row in data if lo <= row[0] <= hi])

    fields = ["block", "d0_s", "triple_ok", "mlc0_src", "sched_ms", "triple_ms",
              "strobe_ms", "d0_d1_ms", "hammer_inside_triple", "frames_in_window", "why"]
    block = os.path.basename(block_dir.rstrip("/"))
    n_ok = 0
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, wr in enumerate(win_rows):
            if not wr:
                continue
            rec = verify_window(wr, wins[i][2])
            n_ok += rec["triple_ok"]
            w.writerow({"block": block, "d0_s": round(wins[i][2], 7),
                        **{k: rec.get(k, "") for k in fields if k not in ("block", "d0_s")}})
    print(f"{block}: {n_ok}/{len(wins)} triples verified -> {out_path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["full", "windows"])
    ap.add_argument("block_dir")
    ap.add_argument("--windows-csv", help="pre-extracted window rows (windowed mode)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    run(a.block_dir, a.windows_csv if a.mode == "windows" else None, a.out)

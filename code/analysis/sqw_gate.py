#!/usr/bin/env python3
"""One-shot square-wave gate for the Saleae D1 channel (pin 11).

Captures 12 s on the Logic Pro 8 (D0/D1/D2 @ 50 MS/s), fires
gpio_squarewave on the Jetson mid-capture, exports the digital CSV,
and verifies the D1 channel shows a 100 Hz square wave with ~5 ms
level-holds for the 5 s drive window.

PASS requires BOTH:
  - >= 400 D1 edges in the busiest 5 s window (expect ~500)
  - >= 400 level-holds in the 4.5-5.5 ms range (expect ~500 @ 5 ms)
The hold-duration check is what rejects floating-probe crosstalk
junk (~0.1 us pulses) and PWM-mirror signals (~1.4 ms holds).

Run with the repo venv interpreter:
  ~/sensor-mlc-latency/.venv/bin/python3 sqw_gate.py
"""
import csv
import glob
import subprocess
import time

import numpy as np
from saleae import automation

PORT = 10430
DEVICE_ID = "6F657C15C3EEE446"
JETSON = "akulswami-jetson"
SQW = "sudo /home/akulswami/sensor-mlc-latency/code/jetson/gpio_harness/gpio_squarewave"
OUT_DIR = "/tmp/sqw_gate"


def main():
    print("[gate] connecting to Logic 2 automation (port 10430)...")
    manager = automation.Manager.connect(port=PORT)
    device_config = automation.LogicDeviceConfiguration(
        enabled_digital_channels=[0, 1, 2],
        digital_sample_rate=50_000_000,
        digital_threshold_volts=1.8,
    )
    capture_config = automation.CaptureConfiguration(
        capture_mode=automation.TimedCaptureMode(duration_seconds=12)
    )
    capture = manager.start_capture(
        device_id=DEVICE_ID,
        device_configuration=device_config,
        capture_configuration=capture_config,
    )
    print("[gate] capture running (12 s). Firing gpio_squarewave in 2 s...")
    time.sleep(2.0)
    subprocess.run(["ssh", JETSON, SQW], check=True)
    capture.wait()
    capture.export_raw_data_csv(directory=OUT_DIR, digital_channels=[0, 1, 2])
    capture.close()
    manager.close()

    csv_path = sorted(glob.glob(f"{OUT_DIR}/*.csv"))[-1]
    rows = list(csv.reader(open(csv_path)))
    hdr = rows[0]
    col = hdr.index("Channel 1")
    t = np.array([float(r[0]) for r in rows[1:]])
    v = np.array([int(r[col]) for r in rows[1:]])
    d = np.diff(v)
    et = t[1:][d != 0]
    ed = d[d != 0]

    best = max(
        ((et >= s) & (et < s + 5)).sum()
        for s in np.arange(et[0], et[-1] - 5, 0.25)
    )
    rises = et[ed > 0]
    falls = et[ed < 0]
    holds = np.array(
        [(falls[falls > x][0] - x) * 1000 for x in rises if len(falls[falls > x])]
    )
    good = holds[(holds >= 4.5) & (holds <= 5.5)]

    print(f"[gate] D1 edges in busiest 5 s window : {best}  (expect ~500)")
    print(f"[gate] D1 level-holds in 4.5-5.5 ms    : {len(good)}  (expect ~500)")
    if len(holds):
        print(f"[gate] D1 median hold overall          : {np.median(holds):.4f} ms")
    ok = best >= 400 and len(good) >= 400
    print(f"[gate] RESULT: {'PASS' if ok else 'FAIL — D1 probe is not seeing a clean pin-11 square wave'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

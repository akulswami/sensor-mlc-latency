#!/usr/bin/env python3
"""
manual_channel_test.py
=======================

Standalone Saleae capture, independent of the block orchestration in
run_stress_block.py. Starts a timed capture on the same digital channels
used by the latency experiment (D0/D1/D2, see SALEAE_DIGITAL_CHANNELS in
run_session.py) and exports it directly to CSV.

Touches nothing on the Jetson side: no SSH, no sensor, no MLC flash, no
pipeline binary. Purely the Saleae capture start/wait/export sequence, for
manually probing what a line is actually doing (e.g. confirming Pin 11 /
D1 / gpiochip0 line 112 goes high when driven) using the Saleae itself as
the test instrument.

Usage:
  python3 code/tools/manual_channel_test.py --duration 20 --out /tmp/probe.csv
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))
from run_session import (
    SALEAE_PORT,
    SALEAE_DEVICE_ID,
    SALEAE_DIGITAL_CHANNELS,
    SALEAE_DIGITAL_SAMPLE_RATE,
)


def run_capture(duration_sec: float, out_path: Path) -> None:
    from saleae import automation

    print(f"[manual-channel-test] Connecting to Saleae automation API on port {SALEAE_PORT}...")
    with automation.Manager.connect(port=SALEAE_PORT) as manager:
        device_config = automation.LogicDeviceConfiguration(
            enabled_digital_channels=SALEAE_DIGITAL_CHANNELS,
            digital_sample_rate=SALEAE_DIGITAL_SAMPLE_RATE,
            digital_threshold_volts=1.8,
        )
        capture_config = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(
                duration_seconds=duration_sec
            )
        )
        print(f"[manual-channel-test] Starting {duration_sec}s capture on channels {SALEAE_DIGITAL_CHANNELS}...")
        capture = manager.start_capture(
            device_id=SALEAE_DEVICE_ID,
            device_configuration=device_config,
            capture_configuration=capture_config,
        )

        print("[manual-channel-test] Waiting for capture to finish...")
        capture.wait()

        # export_raw_data_csv takes a directory (not a filename) and always
        # writes "digital.csv" into it -- export to a scratch dir, then move
        # the result to the exact --out path requested.
        with tempfile.TemporaryDirectory() as tmpdir:
            capture.export_raw_data_csv(
                directory=tmpdir,
                digital_channels=SALEAE_DIGITAL_CHANNELS,
            )
            exported = Path(tmpdir) / "digital.csv"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(exported), str(out_path))

        capture.close()

    print(f"[manual-channel-test] Saved: {out_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Standalone Saleae capture for manually probing a digital channel "
                     "(e.g. Pin 11 / D1 / gpiochip0 line 112), independent of the block "
                     "orchestration in run_stress_block.py."
    )
    parser.add_argument("--duration", type=float, default=20,
                        help="Capture duration in seconds (default: 20).")
    parser.add_argument("--out", required=True, type=Path,
                        help="Output CSV path.")
    args = parser.parse_args()

    run_capture(args.duration, args.out)


if __name__ == "__main__":
    main()

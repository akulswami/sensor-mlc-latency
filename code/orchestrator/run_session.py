#!/usr/bin/env python3
"""
run_session.py — orchestrate one training-data session.

Coordinates three pieces of hardware:
  - Jetson Orin Nano (LSM6DSOX sensor + PCA9685 + SG90 servo)
  - Saleae Logic Pro 8 (capturing on this host)
  - This host (orchestrator + Saleae GUI)

For each requested class (still, motion, or both), runs one capture:
  1. Command servo to center via SSH+i2cset
  2. Start Saleae timed capture (duration + 5 sec margin)
  3. If motion class: start servo_sweep on Jetson in background
  4. Start imu_logger on Jetson (blocks until duration completes)
  5. Wait for Saleae to finish, save .sal to local path
  6. SCP CSV (and sweep.log if motion) back from Jetson
  7. Write/update session.json

Usage:
  python3 run_session.py --session-date 2026-05-21 \\
                         --class both --duration 1200
  python3 run_session.py --session-date 2026-05-21 \\
                         --class motion --duration 600 --btest
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# --- Configuration (matches docs/pin-assignment.md and training-data-spec.md) ---

JETSON_SSH = "akulswami-jetson"
JETSON_REPO = "~/sensor-mlc-latency"
JETSON_IMU_LOGGER = f"{JETSON_REPO}/code/jetson/imu_logger/imu_logger"
JETSON_SERVO_SWEEP = f"{JETSON_REPO}/code/jetson/servo/servo_sweep"
JETSON_DATA_BASE = f"{JETSON_REPO}/data/training"

LOCAL_REPO = Path(__file__).resolve().parents[2]  # code/orchestrator/run_session.py -> repo root
LOCAL_DATA_BASE = LOCAL_REPO / "data" / "training"

SALEAE_DEVICE_ID = "6F657C15C3EEE446"   # Logic Pro 8
SALEAE_PORT = 10430
SALEAE_CAPTURE_MARGIN_SEC = 5            # capture this much longer than logger duration

# PCA9685 PWM endpoints (per docs/lab-notebook/2026-05-19.md)
PWM_CENTER_TICKS = 307
PWM_MIN_TICKS = 102
PWM_MAX_TICKS = 511

# Default ODR for training data
DEFAULT_ODR_HZ = 208

# Sensor INT1 on Jetson Pin 15 = gpiochip0 line 85
# Saleae channels:
#   D0 = sensor INT1 (Jetson Pin 15)
#   D2 = PCA9685 channel 0 PWM
SALEAE_DIGITAL_CHANNELS = [0, 2]
SALEAE_ANALOG_CHANNELS = []
SALEAE_DIGITAL_SAMPLE_RATE = 12_500_000  # 12.5 MS/s, well above Nyquist for both signals


# --- Helpers ---

def ssh(cmd, check=True, capture=False):
    """Run a command on the Jetson via SSH. Returns CompletedProcess."""
    full_cmd = ["ssh", JETSON_SSH, cmd]
    if capture:
        return subprocess.run(full_cmd, check=check, capture_output=True, text=True)
    else:
        return subprocess.run(full_cmd, check=check)


def scp_from_jetson(remote_path, local_path):
    """SCP a file from Jetson to local. Returns CompletedProcess."""
    return subprocess.run(
        ["scp", f"{JETSON_SSH}:{remote_path}", str(local_path)],
        check=True
    )


def i2cset_pca9685_pwm(off_ticks):
    """Set PCA9685 channel 0 PWM to ON=0, OFF=off_ticks via SSH."""
    on_l = 0x00
    on_h = 0x00
    off_l = off_ticks & 0xFF
    off_h = (off_ticks >> 8) & 0xFF
    cmd = (
        f"sudo i2cset -y 1 0x60 0x06 0x{on_l:02X} && "
        f"sudo i2cset -y 1 0x60 0x07 0x{on_h:02X} && "
        f"sudo i2cset -y 1 0x60 0x08 0x{off_l:02X} && "
        f"sudo i2cset -y 1 0x60 0x09 0x{off_h:02X}"
    )
    ssh(cmd)


def verify_jetson_state():
    """Check that the Jetson, sensor, and PCA9685 are all in expected state."""
    print("[orchestrator] Verifying Jetson state...")

    # Sensor on bus 7
    r = ssh("sudo i2cdetect -y -r 7 | grep -c '6a'", check=False, capture=True)
    if not r.stdout.strip().isdigit() or int(r.stdout.strip()) < 1:
        raise RuntimeError("Sensor (0x6A) not found on Jetson bus 7. Check wiring.")

    # PCA9685 on bus 1 at 0x60
    r = ssh("sudo i2cdetect -y -r 1 | grep -c '60 '", check=False, capture=True)
    if not r.stdout.strip().isdigit() or int(r.stdout.strip()) < 1:
        raise RuntimeError("PCA9685 (0x60) not found on Jetson bus 1. Check wiring.")

    # Logger binary exists
    r = ssh(f"test -x {JETSON_IMU_LOGGER}", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"imu_logger binary not found at {JETSON_IMU_LOGGER}")

    # Servo sweep binary exists
    r = ssh(f"test -x {JETSON_SERVO_SWEEP}", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"servo_sweep binary not found at {JETSON_SERVO_SWEEP}")

    print("[orchestrator] Jetson state OK.")


def verify_saleae():
    """Verify Saleae API is reachable and target device is connected."""
    print("[orchestrator] Verifying Saleae automation API...")
    from saleae import automation
    try:
        with automation.Manager.connect(port=SALEAE_PORT) as manager:
            devices = manager.get_devices(include_simulation_devices=False)
            real_ids = [d.device_id for d in devices]
            if SALEAE_DEVICE_ID not in real_ids:
                raise RuntimeError(
                    f"Saleae device {SALEAE_DEVICE_ID} not connected. "
                    f"Connected: {real_ids}"
                )
    except Exception as e:
        raise RuntimeError(f"Saleae API check failed: {e}")
    print("[orchestrator] Saleae OK.")


def run_class_capture(class_name, duration_sec, session_dir, jetson_session_dir, odr_hz):
    """Run a single class capture (still or motion). Saves all artifacts."""
    from saleae import automation

    is_motion = (class_name == "motion")
    class_local = session_dir / class_name
    class_remote = f"{jetson_session_dir}/{class_name}"
    class_local.mkdir(parents=True, exist_ok=True)
    ssh(f"mkdir -p {class_remote}")

    print(f"\n[orchestrator] === Class: {class_name} ===")
    print(f"[orchestrator] Duration: {duration_sec} sec")
    print(f"[orchestrator] Local dir: {class_local}")
    print(f"[orchestrator] Jetson dir: {class_remote}")

    # 1. Servo to center
    print("[orchestrator] Setting servo to center...")
    i2cset_pca9685_pwm(PWM_CENTER_TICKS)
    time.sleep(0.5)  # let servo settle

    capture_duration = duration_sec + SALEAE_CAPTURE_MARGIN_SEC

    # 2. Start Saleae capture
    print(f"[orchestrator] Starting Saleae capture ({capture_duration} sec)...")
    with automation.Manager.connect(port=SALEAE_PORT) as manager:
        device_config = automation.LogicDeviceConfiguration(
            enabled_digital_channels=SALEAE_DIGITAL_CHANNELS,
            digital_sample_rate=SALEAE_DIGITAL_SAMPLE_RATE,
            digital_threshold_volts=1.8,  # Jetson IO is 3.3V; 1.8V threshold splits cleanly
        )
        capture_config = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=capture_duration)
        )

        capture = manager.start_capture(
            device_id=SALEAE_DEVICE_ID,
            device_configuration=device_config,
            capture_configuration=capture_config,
        )

        # 3. Start servo_sweep on Jetson (motion class only), in background.
        sweep_remote_log = f"{class_remote}/sweep.log"
        if is_motion:
            print("[orchestrator] Starting servo_sweep on Jetson...")
            sweep_cmd = (
                f"sudo nohup {JETSON_SERVO_SWEEP} "
                f"--mode continuous --duration {duration_sec} --period-ms 1000 "
                f"--min-ticks {PWM_MIN_TICKS} --max-ticks {PWM_MAX_TICKS} "
                f"--log {sweep_remote_log} "
                f"> /dev/null 2>&1 &"
            )
            ssh(sweep_cmd)
            time.sleep(0.2)  # let sweep get started before logger

        # 4. Start imu_logger on Jetson, BLOCKING for duration_sec
        accel_remote = f"{class_remote}/accel.csv"
        print(f"[orchestrator] Starting imu_logger ({duration_sec} sec)...")
        logger_cmd = (
            f"sudo timeout {duration_sec} {JETSON_IMU_LOGGER} "
            f"--odr {odr_hz} {accel_remote}"
        )
        r = ssh(logger_cmd, check=False, capture=True)
        # `timeout` returns 124 when it kills the process, which is the normal end-of-run case
        if r.returncode not in (0, 124):
            print(f"[orchestrator] WARNING: imu_logger exited with code {r.returncode}")
            print(f"  stderr: {r.stderr}")

        # 5. Wait briefly for servo_sweep to finish; it should have hit its own duration
        if is_motion:
            time.sleep(2)
            # Confirm it's not still running
            r = ssh("pgrep -f servo_sweep", check=False, capture=True)
            if r.stdout.strip():
                print("[orchestrator] WARNING: servo_sweep still running, killing...")
                ssh("sudo pkill -f servo_sweep", check=False)

        # 6. Wait for Saleae capture to finish, save to file
        print("[orchestrator] Waiting for Saleae capture to finish...")
        capture.wait()
        saleae_local = class_local / "saleae.sal"
        print(f"[orchestrator] Saving Saleae capture to {saleae_local}...")
        capture.save_capture(filepath=str(saleae_local))

    # 7. SCP files back
    print("[orchestrator] Copying CSV from Jetson...")
    scp_from_jetson(accel_remote, class_local / "accel.csv")
    if is_motion:
        print("[orchestrator] Copying sweep.log from Jetson...")
        scp_from_jetson(sweep_remote_log, class_local / "sweep.log")

    # 8. Return to center (clean state for next phase)
    i2cset_pca9685_pwm(PWM_CENTER_TICKS)

    # Quick sanity check on CSV
    csv_local = class_local / "accel.csv"
    line_count = sum(1 for _ in open(csv_local))
    print(f"[orchestrator] Captured {line_count} CSV lines.")
    if line_count < duration_sec * odr_hz * 0.8:  # at least 80% of expected
        print(f"[orchestrator] WARNING: CSV has fewer rows than expected "
              f"(got {line_count}, expected ~{duration_sec * odr_hz})")

    return {
        "class": class_name,
        "duration_sec": duration_sec,
        "csv_lines": line_count,
        "started_at": datetime.now().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Run one training-data session.")
    parser.add_argument("--session-date", required=True,
                        help="Session date, e.g. 2026-05-21")
    parser.add_argument("--class", dest="class_name", required=True,
                        choices=["still", "motion", "both"],
                        help="Which class(es) to capture")
    parser.add_argument("--duration", type=int, default=1200,
                        help="Seconds per class (default: 1200 = 20 min)")
    parser.add_argument("--odr", type=int, default=DEFAULT_ODR_HZ,
                        help=f"Sample rate Hz (default: {DEFAULT_ODR_HZ})")
    parser.add_argument("--btest", action="store_true",
                        help="Mark as a test run (-btest suffix); reduce duration to 30 sec")
    args = parser.parse_args()

    session_date = args.session_date
    duration = args.duration
    if args.btest:
        session_date += "-btest"
        duration = min(duration, 30)
        print(f"[orchestrator] BTEST mode: session={session_date}, duration={duration}s")

    # Resolve local + remote session dirs
    session_dir = LOCAL_DATA_BASE / session_date
    jetson_session_dir = f"{JETSON_DATA_BASE}/{session_date}"

    # Refuse to overwrite an existing session (real sessions only)
    if not args.btest and session_dir.exists() and any(session_dir.iterdir()):
        raise RuntimeError(
            f"Session directory already has content: {session_dir}\n"
            f"Refusing to overwrite. Delete it or use --btest."
        )
    session_dir.mkdir(parents=True, exist_ok=True)

    # Pre-flight
    verify_jetson_state()
    verify_saleae()

    # Decide which classes to run
    classes_to_run = ["still", "motion"] if args.class_name == "both" else [args.class_name]

    session_metadata = {
        "session_date": session_date,
        "btest": args.btest,
        "duration_sec_per_class": duration,
        "odr_hz": args.odr,
        "pwm_center_ticks": PWM_CENTER_TICKS,
        "pwm_min_ticks": PWM_MIN_TICKS,
        "pwm_max_ticks": PWM_MAX_TICKS,
        "started_at": datetime.now().isoformat(),
        "classes": [],
    }

    for class_name in classes_to_run:
        result = run_class_capture(
            class_name=class_name,
            duration_sec=duration,
            session_dir=session_dir,
            jetson_session_dir=jetson_session_dir,
            odr_hz=args.odr,
        )
        session_metadata["classes"].append(result)

    session_metadata["finished_at"] = datetime.now().isoformat()

    # Write session.json
    session_json_path = session_dir / "session.json"
    with open(session_json_path, "w") as f:
        json.dump(session_metadata, f, indent=2)
    print(f"\n[orchestrator] Session complete. Metadata: {session_json_path}")
    print(f"[orchestrator] Files saved to {session_dir}")


if __name__ == "__main__":
    sys.exit(main())

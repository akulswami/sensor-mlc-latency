#!/usr/bin/env python3
"""
run_session_parity.py — orchestrate one session-4 (parity) capture.

Extends run_session.py with the on-sensor MLC pipeline:
  - Before each class capture, flashes the trained MLC tree via mlc_setup.
  - During each class capture, polls MLC0_SRC at 50 Hz alongside imu_logger
    via mlc_poller, recording silicon decisions to silicon_raw.csv.
  - Records both processes' CLOCK_MONOTONIC start times into session.json
    so silicon_align can join the streams post-hoc.

Compared to run_session.py:
  - Adds JETSON_MLC_SETUP, JETSON_MLC_POLLER paths.
  - Adds mlc_setup invocation and mlc_poller backgrounding to
    run_class_capture.
  - Captures t0_monotonic_s from imu_logger stderr (requires imu_logger
    patched to print this).
  - Captures t_start_monotonic from mlc_poller stderr (SCP'd back).
  - Emits silicon_raw.csv and mlc_poller_stderr.log alongside accel.csv.

Usage:
  python3 run_session_parity.py --session-date 2026-05-23 \\
                                --class both --duration 1200
  python3 run_session_parity.py --session-date 2026-05-23 \\
                                --class motion --duration 30 --btest

Pre-registration discipline:
  - The MLC config header used is recorded in session.json under
    `mlc_config_header`. Default: mlc_motion_w75.h.
  - The orchestrator does NOT modify the MLC config or thresholds.
  - All accel sampling parameters (ODR, FS, BDU) are inherited from
    imu_logger.c (unchanged from sessions 1-3 except for the flock
    patch, which is implementation-level synchronization only).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse helpers and constants from run_session.py
from run_session import (
    JETSON_SSH,
    JETSON_REPO,
    JETSON_IMU_LOGGER,
    JETSON_SERVO_SWEEP,
    JETSON_DATA_BASE,
    LOCAL_REPO,
    LOCAL_DATA_BASE,
    SALEAE_DEVICE_ID,
    SALEAE_PORT,
    SALEAE_CAPTURE_MARGIN_SEC,
    SALEAE_DIGITAL_CHANNELS,
    SALEAE_DIGITAL_SAMPLE_RATE,
    PWM_CENTER_TICKS,
    PWM_MIN_TICKS,
    PWM_MAX_TICKS,
    DEFAULT_ODR_HZ,
    ssh,
    scp_from_jetson,
    i2cset_pca9685_pwm,
    verify_jetson_state as _verify_jetson_state_base,
    verify_saleae,
)

# --- New paths for session 4 ---

JETSON_MLC_POLLER = f"{JETSON_REPO}/code/jetson/session4/mlc_poller"

# v7 Change 6 item 1 (Saleae sync-edge): the sync_edge binary fires a single
# rising edge on Pin 11 (gpiochip0 line 112, Saleae D1) and prints the
# CLOCK_MONOTONIC timestamp. Called once per session (first arm only) to
# align Saleae capture clock with Jetson monotonic clock. See
# code/jetson/sync_edge/sync_edge.c and docs/measurement-protocol.md.
JETSON_SYNC_EDGE = f"{JETSON_REPO}/code/jetson/sync_edge/sync_edge"

# Maps --mlc-config-header (e.g. "mlc_motion_w25.h") to the matching
# binary path under code/jetson/session4/mlc_setup_wN. Binaries must
# already be built; this orchestrator does not compile them.
#
# Naming convention: mlc_motion_wN.h <-> mlc_setup_wN. Established
# 2026-05-24 in v7.2 as part of the orchestrator-bug fix that retired
# the previous hardcoded JETSON_MLC_SETUP constant. See Zenodo DOI
# 10.5281/zenodo.20371440 for the v7.2 amendment.
_MLC_HEADER_RE = re.compile(r"^mlc_motion_w(\d+)\.h$")


def jetson_mlc_setup_path(mlc_config_header):
    """Derive the mlc_setup_wN binary path from --mlc-config-header.

    Raises ValueError if the header name doesn't match the expected
    pattern. The caller is responsible for checking the binary exists
    on the Jetson before invoking it.
    """
    m = _MLC_HEADER_RE.match(mlc_config_header)
    if not m:
        raise ValueError(
            f"--mlc-config-header {mlc_config_header!r} doesn't match the "
            f"expected pattern 'mlc_motion_wN.h' (e.g. 'mlc_motion_w75.h'). "
            f"The orchestrator derives the binary path from this argument; "
            f"a free-form header name is not supported. See v7.2 amendment "
            f"(Zenodo DOI 10.5281/zenodo.20371440)."
        )
    window_n = m.group(1)
    return f"{JETSON_REPO}/code/jetson/session4/mlc_setup_w{window_n}"


# MLC polling parameters
MLC_POLL_HZ = 50

# Extra duration for mlc_poller relative to imu_logger. Lets the poller
# overrun the logger by this much so the captured silicon stream
# definitely brackets imu_logger's run. Trimmed in post-processing.
MLC_POLLER_EXTRA_SEC = 3


# --- v5 Change 2: mount-geometry pre/post-check constants ---
# Pre-registered in docs/pre-registration.md "Amendment 2026-05-23"
# (Zenodo DOI 10.5281/zenodo.20361496). Do NOT modify without amendment.

MOUNT_CENTROID_X_G = -0.0116
MOUNT_CENTROID_Y_G = -0.0754
MOUNT_CENTROID_Z_G = -0.9664
MOUNT_THRESHOLD_G = 0.065
MOUNT_DRIFT_BOUND_G = 0.005
MOUNT_PRECHECK_DURATION_SEC = 30

def _euclidean_to_centroid(x_mean, y_mean, z_mean):
    import math
    dx = x_mean - MOUNT_CENTROID_X_G
    dy = y_mean - MOUNT_CENTROID_Y_G
    dz = z_mean - MOUNT_CENTROID_Z_G
    return math.sqrt(dx*dx + dy*dy + dz*dz)

def _accel_csv_means(csv_path):
    import csv as _csv
    sums = [0.0, 0.0, 0.0]
    cnt = 0
    with open(csv_path) as f:
        r = _csv.reader(f)
        try:
            next(r)
        except StopIteration:
            raise RuntimeError(f"Accel CSV empty: {csv_path}")
        for row in r:
            if not row or len(row) < 4:
                continue
            try:
                sums[0] += float(row[1])
                sums[1] += float(row[2])
                sums[2] += float(row[3])
                cnt += 1
            except ValueError:
                continue
    if cnt == 0:
        raise RuntimeError(f"No data rows in accel CSV: {csv_path}")
    return cnt, (sums[0]/cnt, sums[1]/cnt, sums[2]/cnt)


# --- Helpers ---

def verify_jetson_state_parity(mlc_setup_path):
    """Extends base verify_jetson_state with checks for session-4 binaries.

    mlc_setup_path is the per-session binary derived from
    --mlc-config-header by jetson_mlc_setup_path() per v7.2's dispatch
    logic. See Zenodo DOI 10.5281/zenodo.20371440.
    """
    _verify_jetson_state_base()

    # mlc_setup binary (path is derived from --mlc-config-header per v7.2)
    r = ssh(f"test -x {mlc_setup_path}", check=False)
    if r.returncode != 0:
        raise RuntimeError(
            f"mlc_setup binary not found at {mlc_setup_path}. "
            f"Build it on the Jetson: "
            f"cd code/jetson/session4 && "
            f"gcc -O2 -Wall -I<path-to-header-dir> "
            f"-DMLC_CONFIG_HEADER=<header-name>.h "
            f"-o mlc_setup_w<N> mlc_setup.c"
        )

    # mlc_poller binary
    r = ssh(f"test -x {JETSON_MLC_POLLER}", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"mlc_poller binary not found at {JETSON_MLC_POLLER}. "
                           f"Build it: cd code/jetson/session4 && "
                           f"gcc -O2 -Wall -o mlc_poller mlc_poller.c")

    print("[orchestrator] mlc_setup and mlc_poller binaries present.")


# v7.2 (Strategy C'): post-flash silicon liveness check.
# Reads MLC0_SRC from the embedded bank to confirm silicon is alive,
# responsive, and classifying. Does NOT verify window length or specific
# tree config -- that's caught post-hoc via the transition-count
# diagnostic in code/analysis/.
#
# Register addresses confirmed against mlc_poll_probe.c:
#   FUNC_CFG_ACCESS = 0x01 (user bank, controls bank selection)
#   BANK_USER = 0x00, BANK_EMBEDDED = 0x80
#   MLC0_SRC = 0x70 (in embedded bank)
def verify_silicon_alive():
    """Read MLC0_SRC over SSH/i2cget. Raise if readback fails or value
    is not in {0x00 still, 0x04 motion}. Bank-switch dance is the same
    three-step sequence as in mlc_poll_probe.c.
    """
    # Bank-switch to embedded
    r = ssh("sudo i2cset -y 7 0x6a 0x01 0x80", check=False, capture=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"silicon liveness check: bank-switch to embedded failed "
            f"(exit {r.returncode}): {r.stderr}"
        )

    # Read MLC0_SRC (0x70 in embedded bank)
    r = ssh("sudo i2cget -y 7 0x6a 0x70", check=False, capture=True)
    src_str = r.stdout.strip() if r.returncode == 0 else None

    # Restore bank to user (do this BEFORE raising if read failed -- we
    # do NOT want to leave silicon in embedded bank, which would break
    # subsequent operations).
    r_restore = ssh("sudo i2cset -y 7 0x6a 0x01 0x00", check=False, capture=True)
    if r_restore.returncode != 0:
        raise RuntimeError(
            f"silicon liveness check: failed to restore user bank "
            f"(exit {r_restore.returncode}). Silicon is in an inconsistent "
            f"state and may misbehave on subsequent operations."
        )

    if src_str is None:
        raise RuntimeError(
            f"silicon liveness check: MLC0_SRC read failed (exit {r.returncode}). "
            f"Bank was restored. stderr: {r.stderr}"
        )

    try:
        src_val = int(src_str, 16)
    except ValueError:
        raise RuntimeError(
            f"silicon liveness check: MLC0_SRC returned unparseable "
            f"value {src_str!r}; expected hex like '0x00'."
        )

    if src_val not in (0x00, 0x04):
        raise RuntimeError(
            f"silicon liveness check: MLC0_SRC = 0x{src_val:02X}, expected "
            f"0x00 (still) or 0x04 (motion). Silicon is responding but "
            f"not in a known-good classification state. The flashed tree "
            f"may not be the intended one."
        )

    print(f"[orchestrator] Silicon liveness OK: MLC0_SRC = 0x{src_val:02X} "
          f"({'still' if src_val == 0x00 else 'motion'}).")


def run_mlc_setup(mlc_setup_path):
    """One-shot: flash the trained MLC config. Raises on failure.

    mlc_setup_path is derived from --mlc-config-header per v7.2's
    dispatch logic. See jetson_mlc_setup_path() above.
    """
    print(f"[orchestrator] Flashing MLC via {mlc_setup_path}...")
    r = ssh(f"sudo {mlc_setup_path}", check=False, capture=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"mlc_setup failed (exit {r.returncode}).\n"
            f"  stdout: {r.stdout}\n"
            f"  stderr: {r.stderr}"
        )
    # Sanity-check the stderr for the expected "MLC ready" string.
    if "MLC ready" not in r.stderr:
        raise RuntimeError(
            f"mlc_setup exited 0 but didn't print 'MLC ready' on stderr. "
            f"Sensor may not have configured.\n  stderr: {r.stderr}"
        )
    print("[orchestrator] MLC flashed OK.")
    # v7.2 Strategy C': verify silicon is alive after flash.
    verify_silicon_alive()


# Regex for parsing the imu_logger and mlc_poller stderr.
_RE_T0_IMU = re.compile(r"t0_monotonic_s\s*=\s*([0-9.]+)")
_RE_T_START_MLC = re.compile(r"t_start_monotonic\s*=\s*([0-9.]+)")


def parse_imu_t0(stderr_text):
    """Extract t0_monotonic_s from imu_logger stderr. Returns float or None."""
    m = _RE_T0_IMU.search(stderr_text)
    return float(m.group(1)) if m else None


def parse_mlc_t_start(stderr_text):
    """Extract t_start_monotonic from mlc_poller stderr. Returns float or None."""
    m = _RE_T_START_MLC.search(stderr_text)
    return float(m.group(1)) if m else None


# --- v5 Change 2: mount-check functions ---

def run_class_capture_parity(class_name, duration_sec, session_dir,
                             jetson_session_dir, odr_hz, mlc_setup_path,
                             is_first_arm=False):
    """Run a single class capture with parallel MLC silicon capture.

    mlc_setup_path is the derived mlc_setup_wN binary path per v7.2's
    dispatch logic. Threaded through from main() via
    jetson_mlc_setup_path(args.mlc_config_header).

    is_first_arm (v7 Change 6 item 1): when True, fire a single sync edge
    on Pin 11 / line 112 / Saleae D1 between Saleae arming and the start
    of mlc_poller. The Jetson monotonic-clock timestamp of the toggle is
    returned in the result dict as 'saleae_sync_jetson_monotonic_ns' so
    main() can record it at session-metadata top level. Per-session sync;
    motion arm (is_first_arm=False) does NOT fire a second sync edge.
    """
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

    # 1. Servo to center, settle
    print("[orchestrator] Setting servo to center...")
    i2cset_pca9685_pwm(PWM_CENTER_TICKS)
    time.sleep(0.5)

    # 2. Flash MLC. This must happen BEFORE Saleae starts capturing because
    #    mlc_setup performs SW_RESET, which would briefly de-assert all
    #    INT lines and look like an anomaly on the wire trace.
    run_mlc_setup(mlc_setup_path)
    # mlc_setup includes a 100ms sleep after flash. Add a bit more buffer
    # before we start capturing.
    time.sleep(0.3)

    capture_duration = duration_sec + SALEAE_CAPTURE_MARGIN_SEC

    # 3. Start Saleae capture
    print(f"[orchestrator] Starting Saleae capture ({capture_duration} sec)...")
    with automation.Manager.connect(port=SALEAE_PORT) as manager:
        device_config = automation.LogicDeviceConfiguration(
            enabled_digital_channels=SALEAE_DIGITAL_CHANNELS,
            digital_sample_rate=SALEAE_DIGITAL_SAMPLE_RATE,
            digital_threshold_volts=1.8,
        )
        capture_config = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(duration_seconds=capture_duration)
        )
        capture = manager.start_capture(
            device_id=SALEAE_DEVICE_ID,
            device_configuration=device_config,
            capture_configuration=capture_config,
        )

        # 3a. v7 Change 6 item 1: fire sync edge on Pin 11/D1 once per
        #     session, before any measurement binary starts. The sync
        #     edge produces the FIRST D1 rising edge of the session's
        #     Saleae trace; subsequent D1 edges are measurement edges
        #     from host_pipeline_parity or latency_test_mlc_w75.
        #     Per-class sync edges are NOT fired (would re-toggle Pin 11
        #     which is owned by the host/silicon measurement binary
        #     during their arm). The motion arm relies on the
        #     post-analysis aligning Saleae and Jetson clocks via the
        #     still-arm sync edge plus its own arm-start timestamp.
        saleae_sync_jetson_monotonic_ns = None
        if is_first_arm:
            print("[orchestrator] Firing session-start sync edge on Pin 11...")
            # Brief settle so Saleae is unambiguously armed before the edge.
            time.sleep(0.5)
            r = ssh(f"sudo {JETSON_SYNC_EDGE}", capture=True, check=False)
            if r.returncode != 0:
                raise RuntimeError(
                    f"sync_edge failed (exit {r.returncode}). "
                    f"stdout: {r.stdout!r} stderr: {r.stderr!r}"
                )
            try:
                saleae_sync_jetson_monotonic_ns = int(r.stdout.strip())
            except ValueError:
                raise RuntimeError(
                    f"sync_edge did not print a parseable monotonic_ns: "
                    f"stdout={r.stdout!r}"
                )
            print(f"[orchestrator]   sync_edge fired at Jetson "
                  f"monotonic_ns = {saleae_sync_jetson_monotonic_ns}")
            # Let line 112 settle low (sync_edge holds high 10ms then
            # drives low) before the measurement binary starts and
            # takes ownership of the line.
            time.sleep(0.1)

        # 4. Start mlc_poller in background. Output silicon_raw.csv on
        #    Jetson side; we'll SCP back at the end. stderr goes to a
        #    log file so we can parse t_start_monotonic later.
        silicon_remote = f"{class_remote}/silicon_raw.csv"
        mlc_stderr_remote = f"{class_remote}/mlc_poller.stderr.log"
        mlc_poll_duration = duration_sec + MLC_POLLER_EXTRA_SEC
        print(f"[orchestrator] Starting mlc_poller ({mlc_poll_duration} sec)...")
        mlc_cmd = (
            f"sudo nohup {JETSON_MLC_POLLER} "
            f"--hz {MLC_POLL_HZ} --duration {mlc_poll_duration} "
            f"{silicon_remote} "
            f"> /dev/null 2> {mlc_stderr_remote} &"
        )
        ssh(mlc_cmd)
        # Give mlc_poller a moment to open files and write its t_start line.
        time.sleep(0.3)

        # 5. If motion: start servo_sweep in background.
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
            time.sleep(0.2)

        # 6. Start imu_logger BLOCKING for duration_sec. Capture stderr
        #    so we can parse t0_monotonic_s.
        accel_remote = f"{class_remote}/accel.csv"
        print(f"[orchestrator] Starting imu_logger ({duration_sec} sec)...")
        logger_cmd = (
            f"sudo timeout {duration_sec} {JETSON_IMU_LOGGER} "
            f"--odr {odr_hz} {accel_remote}"
        )
        r = ssh(logger_cmd, check=False, capture=True)
        if r.returncode not in (0, 124):
            print(f"[orchestrator] WARNING: imu_logger exited with code {r.returncode}")
            print(f"  stderr: {r.stderr}")

        imu_t0 = parse_imu_t0(r.stderr)
        if imu_t0 is None:
            raise RuntimeError(
                f"Failed to parse t0_monotonic_s from imu_logger stderr. "
                f"Is imu_logger patched with the t0 print line?\n"
                f"  stderr: {r.stderr}"
            )
        print(f"[orchestrator] imu_logger t0_monotonic_s = {imu_t0:.6f}")

        # 7. Wait briefly for mlc_poller and servo_sweep to finish on
        #    their own duration timers, then kill any stragglers.
        time.sleep(MLC_POLLER_EXTRA_SEC + 1)
        r = ssh("pgrep -x mlc_poller", check=False, capture=True)
        if r.stdout.strip():
            print("[orchestrator] WARNING: mlc_poller still running, killing...")
            ssh("sudo pkill mlc_poller", check=False)
            time.sleep(0.5)
        if is_motion:
            r = ssh("pgrep -x servo_sweep", check=False, capture=True)
            if r.stdout.strip():
                print("[orchestrator] WARNING: servo_sweep still running, killing...")
                ssh("sudo pkill servo_sweep", check=False)

        # 8. Wait for Saleae capture to finish
        print("[orchestrator] Waiting for Saleae capture to finish...")
        capture.wait()
        saleae_local = class_local / "saleae.sal"
        print(f"[orchestrator] Saving Saleae capture to {saleae_local}...")
        capture.save_capture(filepath=str(saleae_local))

    # 9. SCP files back
    print("[orchestrator] Copying accel CSV from Jetson...")
    scp_from_jetson(accel_remote, class_local / "accel.csv")
    print("[orchestrator] Copying silicon_raw.csv from Jetson...")
    scp_from_jetson(silicon_remote, class_local / "silicon_raw.csv")
    print("[orchestrator] Copying mlc_poller stderr log from Jetson...")
    scp_from_jetson(mlc_stderr_remote, class_local / "mlc_poller.stderr.log")
    if is_motion:
        print("[orchestrator] Copying sweep.log from Jetson...")
        scp_from_jetson(sweep_remote_log, class_local / "sweep.log")

    # 10. Parse mlc_poller stderr for t_start_monotonic
    with open(class_local / "mlc_poller.stderr.log") as f:
        mlc_stderr_text = f.read()
    mlc_t_start = parse_mlc_t_start(mlc_stderr_text)
    if mlc_t_start is None:
        raise RuntimeError(
            f"Failed to parse t_start_monotonic from mlc_poller stderr.\n"
            f"  stderr: {mlc_stderr_text}"
        )
    print(f"[orchestrator] mlc_poller t_start_monotonic = {mlc_t_start:.6f}")

    # 11. Return servo to center
    i2cset_pca9685_pwm(PWM_CENTER_TICKS)

    # 12. Sanity checks
    csv_local = class_local / "accel.csv"
    accel_lines = sum(1 for _ in open(csv_local))
    silicon_lines = sum(1 for _ in open(class_local / "silicon_raw.csv"))
    print(f"[orchestrator] Captured {accel_lines} accel rows, {silicon_lines} silicon rows.")
    if accel_lines < duration_sec * odr_hz * 0.8:
        print(f"[orchestrator] WARNING: accel CSV has fewer rows than expected "
              f"(got {accel_lines}, expected ~{duration_sec * odr_hz})")
    expected_silicon = duration_sec * MLC_POLL_HZ * 0.9
    if silicon_lines < expected_silicon:
        print(f"[orchestrator] WARNING: silicon CSV has fewer rows than expected "
              f"(got {silicon_lines}, expected ~{duration_sec * MLC_POLL_HZ})")

    return {
        "class": class_name,
        "duration_sec": duration_sec,
        "csv_lines": accel_lines,
        "silicon_raw_lines": silicon_lines,
        "started_at": datetime.now().isoformat(),
        "imu_t0_monotonic_s": imu_t0,
        "mlc_t_start_monotonic_s": mlc_t_start,
        "clock_offset_s": mlc_t_start - imu_t0,
        # v7 Change 6 item 1: only set for the first arm of the session;
        # None on subsequent arms. main() lifts this to session-metadata
        # top level after the loop.
        "saleae_sync_jetson_monotonic_ns": saleae_sync_jetson_monotonic_ns,
    }


def main():
    parser = argparse.ArgumentParser(description="Run one session-4 (parity) capture.")
    parser.add_argument("--session-date", required=True,
                        help="Session date, e.g. 2026-05-23")
    parser.add_argument("--class", dest="class_name", required=True,
                        choices=["still", "motion", "both"],
                        help="Which class(es) to capture")
    parser.add_argument("--duration", type=int, default=1200,
                        help="Seconds per class (default: 1200 = 20 min)")
    parser.add_argument("--odr", type=int, default=DEFAULT_ODR_HZ,
                        help=f"Sample rate Hz (default: {DEFAULT_ODR_HZ})")
    parser.add_argument("--btest", action="store_true",
                        help="Mark as a test run (-btest suffix); reduce duration to 30 sec")
    parser.add_argument("--mlc-config-header", required=True,
                        help="MLC config header to flash (e.g. "
                             "mlc_motion_w25.h, mlc_motion_w75.h, "
                             "mlc_motion_w200.h). The orchestrator derives "
                             "the mlc_setup_wN binary path from this "
                             "argument and records it in session.json. Per "
                             "v7.2 amendment, this is no longer optional and "
                             "no longer has a default. See Zenodo DOI "
                             "10.5281/zenodo.20371440.")
    args = parser.parse_args()

    session_date = args.session_date
    duration = args.duration
    if args.btest:
        session_date += "-btest"
        duration = min(duration, 30)
        print(f"[orchestrator] BTEST mode: session={session_date}, duration={duration}s")

    # Derive the per-session mlc_setup binary path from --mlc-config-header.
    # Per v7.2 amendment: the orchestrator no longer hardcodes the binary.
    mlc_setup_path = jetson_mlc_setup_path(args.mlc_config_header)
    print(f"[orchestrator] MLC setup binary: {mlc_setup_path}")

    session_dir = LOCAL_DATA_BASE / session_date
    jetson_session_dir = f"{JETSON_DATA_BASE}/{session_date}"

    if not args.btest and session_dir.exists() and any(session_dir.iterdir()):
        raise RuntimeError(
            f"Session directory already has content: {session_dir}\n"
            f"Refusing to overwrite. Delete it or use --btest."
        )
    session_dir.mkdir(parents=True, exist_ok=True)

    # Pre-flight
    verify_jetson_state_parity(mlc_setup_path)
    verify_saleae()
    # v6: Mount-check disabled; sessions proceed without geometry validation.

    classes_to_run = ["still", "motion"] if args.class_name == "both" else [args.class_name]

    session_metadata = {
        "session_date": session_date,
        "session_type": "parity",
        "btest": args.btest,
        "duration_sec_per_class": duration,
        "odr_hz": args.odr,
        "pwm_center_ticks": PWM_CENTER_TICKS,
        "pwm_min_ticks": PWM_MIN_TICKS,
        "pwm_max_ticks": PWM_MAX_TICKS,
        "mlc_config_header": args.mlc_config_header,
        "mlc_poll_hz": MLC_POLL_HZ,
        "started_at": datetime.now().isoformat(),
        "classes": [],
    }

    for i, class_name in enumerate(classes_to_run):
        result = run_class_capture_parity(
            class_name=class_name,
            duration_sec=duration,
            session_dir=session_dir,
            jetson_session_dir=jetson_session_dir,
            odr_hz=args.odr,
            mlc_setup_path=mlc_setup_path,
            is_first_arm=(i == 0),
        )
        # v7 Change 6 item 1: lift sync timestamp to session-metadata top
        # level; it's a session-wide field, recorded once per session.
        if i == 0 and result.get("saleae_sync_jetson_monotonic_ns") is not None:
            session_metadata["saleae_sync_jetson_monotonic_ns"] = (
                result["saleae_sync_jetson_monotonic_ns"]
            )
        session_metadata["classes"].append(result)
    session_metadata["finished_at"] = datetime.now().isoformat()

    session_json_path = session_dir / "session.json"
    with open(session_json_path, "w") as f:
        json.dump(session_metadata, f, indent=2)
    print(f"\n[orchestrator] Session complete. Metadata: {session_json_path}")
    print(f"[orchestrator] Files saved to {session_dir}")
if __name__ == "__main__":
    sys.exit(main())

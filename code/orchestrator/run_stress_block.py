#!/usr/bin/env python3
"""
run_stress_block.py
===================

Per-block runner for the v7 latency experiment.

Fulfills Gate 4 of v7 Change 6 (pre-reg amendment 2026-05-24,
Zenodo DOI 10.5281/zenodo.20371440), refined by v7.3 (2026-05-25,
Zenodo DOI [TBD-DOI-INSERT]).

A "block" per pre-reg §7 is one of 40 units in the experimental
campaign: 10 blocks per condition * 4 conditions = 40 blocks total.
The 4 conditions are {MLC, host} * {idle, stress}; each block fixes
one pipeline and one stress condition.

Per-block workflow:
  1. Verify Jetson state (sensor reachable, binaries present)
  2. Verify Saleae automation
  3. Create block directory
  4. Flash MLC (mlc_setup_w75) for sensor consistency across blocks
  5. Verify silicon liveness (read MLC0_SRC = 0x00)
  6. Start tegrastats logging (background, for §11 throttling check)
  7. Start Saleae capture (D0, D1, D2 enabled)
  8. Brief settle
  9. Fire sync edge (sync_edge binary)
 10. If --condition stress: start stress-ng via run_stress.sh
 11. Verify CPU state per §8 (>=95% stress, <10% idle)
 12. Start servo_sweep --mode burst (background, motion stimulus)
 13. Start pipeline binary (host_pipeline_parity OR latency_test_mlc_w75)
     in background; this drives D1
 14. Sleep for block duration
 15. Stop pipeline binary, servo_sweep, stress-ng (in that order)
 16. Wait for Saleae capture to finish; save .sal
 17. Stop tegrastats
 18. Scan tegrastats output for throttling events (§11 criterion 3)
 19. Write block_metadata.json with all timestamps and verification
     results

Output:
  data/latency-experiment/block-NNN-pipeline-condition/
    saleae.sal
    sweep.log
    tegrastats.log
    block_metadata.json

Per-block exclusion criteria (per §8, §11):
  - cpu_verification_failed: block ran under stress condition but
    sustained CPU utilization was below 95%, OR ran under idle but
    above 10%
  - thermal_throttling: tegrastats logged throttling event during
    the block
  - Per-trial exclusions (§6.2, §11) are applied later by
    extract_latency_v7.py against the saleae.sal file.

Usage:
  python3 run_stress_block.py --block-id 1 --condition idle \\
      --pipeline mlc --duration 300
  python3 run_stress_block.py --block-id 2 --condition stress \\
      --pipeline host --duration 300 --btest
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Reuse helpers and constants from run_session.py for SSH + Saleae setup
sys.path.insert(0, str(Path(__file__).parent))
from run_session import (
    JETSON_REPO,
    JETSON_SERVO_SWEEP,
    JETSON_DATA_BASE,
    LOCAL_REPO,
    LOCAL_DATA_BASE,
    SALEAE_DEVICE_ID,
    SALEAE_PORT,
    SALEAE_DIGITAL_SAMPLE_RATE,
    SALEAE_DIGITAL_CHANNELS,
    SALEAE_CAPTURE_MARGIN_SEC,
    PWM_CENTER_TICKS,
    PWM_MIN_TICKS,
    PWM_MAX_TICKS,
    DEFAULT_ODR_HZ,
    ssh,
    i2cset_pca9685_pwm,
    verify_saleae,
)
from run_session_parity import (
    JETSON_SYNC_EDGE,
    jetson_mlc_setup_path,
    run_mlc_setup,
    verify_jetson_state_parity,
)

# Jetson binary paths.
#
# JETSON_REPO uses '~' which resolves to the SSH user's home (akulswami).
# JETSON_REPO_ABS is the absolute path; required when constructing commands
# that run inside a `sudo bash -c '...'` shell (since the inner shell runs as
# root and '~' would resolve to /root/, which doesn't have the repo).
JETSON_REPO_ABS = "/home/akulswami/sensor-mlc-latency"
JETSON_DATA_BASE_ABS = f"{JETSON_REPO_ABS}/data/training"

JETSON_HOST_PIPELINE_PARITY = (
    f"{JETSON_REPO_ABS}/code/jetson/host_inference/host_pipeline_parity"
)
JETSON_LATENCY_TEST_MLC_W75 = (
    f"{JETSON_REPO_ABS}/code/jetson/mlc_pipeline/latency_test_mlc_w75"
)
JETSON_LATENCY_TEST_MLC_BINARY_W75 = (
    f"{JETSON_REPO_ABS}/code/jetson/mlc_pipeline/latency_test_mlc_binary_w75"
)
JETSON_TREE_W75 = f"{JETSON_REPO_ABS}/code/mlc_config/tree_w75.json"
JETSON_RUN_STRESS_SH = f"{JETSON_REPO_ABS}/code/stress/run_stress.sh"

# Tegrastats output parsed for throttling indicators
THROTTLE_INDICATORS = ["thermal_throttling", "thr@", "Throttled", "throttling"]


# --- Helpers ---


def run_block(args) -> int:
    """Run a single block. Returns 0 on success (block usable), nonzero on failure."""

    duration_sec = 30 if args.btest else args.duration
    block_name = f"block-{args.block_id:03d}-{args.pipeline}-{args.condition}"
    if args.btest:
        block_name += "-btest"

    block_local = Path(LOCAL_DATA_BASE) / "latency-experiment" / block_name
    # Use absolute path on Jetson side because the pipeline binary's stdout/stderr
    # is redirected to a file under this path from within a `sudo bash -c '...'`
    # shell where '~' would resolve to /root/.
    block_remote = f"{JETSON_DATA_BASE_ABS}/latency-experiment/{block_name}"
    block_local.mkdir(parents=True, exist_ok=True)
    ssh(f"mkdir -p {block_remote}")

    print(f"\n[block-runner] === BLOCK: {block_name} ===")
    print(f"[block-runner] Pipeline: {args.pipeline}")
    print(f"[block-runner] Condition: {args.condition}")
    print(f"[block-runner] Duration: {duration_sec}s")
    print(f"[block-runner] Local dir: {block_local}")
    print(f"[block-runner] Jetson dir: {block_remote}")

    block_metadata = {
        "block_id": args.block_id,
        "block_name": block_name,
        "pipeline": args.pipeline,
        "condition": args.condition,
        "duration_sec": duration_sec,
        "btest": args.btest,
        "started_at": datetime.now().isoformat(),
        "mlc_config_header": "mlc_motion_w75.h",  # pinned per v7.2
    }

    # 1. Verify Jetson state
    mlc_setup_path = jetson_mlc_setup_path("mlc_motion_w75.h")
    verify_jetson_state_parity(mlc_setup_path)

    # 2. Verify Saleae
    verify_saleae()

    # 3. Setup servo to center
    print("[block-runner] Setting servo to center...")
    i2cset_pca9685_pwm(PWM_CENTER_TICKS)
    time.sleep(0.5)

    # 4. Flash MLC (consistency across blocks)
    run_mlc_setup(mlc_setup_path)
    time.sleep(0.3)

    # 5. Silicon liveness check
    r = ssh(
        "sudo i2cset -y 7 0x6a 0x01 0x80 && "
        "sudo i2cget -y 7 0x6a 0x70 && "
        "sudo i2cset -y 7 0x6a 0x01 0x00",
        check=False, capture=True,
    )
    mlc_src = r.stdout.strip().split("\n")[0] if r.stdout else ""
    block_metadata["silicon_liveness_mlc_src"] = mlc_src
    print(f"[block-runner] Silicon liveness: MLC0_SRC = {mlc_src}")

    # 6. Start tegrastats logging on Jetson
    tegrastats_remote_log = f"{block_remote}/tegrastats.log"
    tegrastats_pid_file = f"/tmp/tegrastats_pid_{args.block_id}.txt"
    ssh(
        f"sudo nohup tegrastats --interval 500 "
        f"> {tegrastats_remote_log} 2>&1 & echo $! > {tegrastats_pid_file}",
        check=False,
    )
    time.sleep(0.5)  # let tegrastats spawn
    block_metadata["tegrastats_pid_file"] = tegrastats_pid_file

    # 7. Start Saleae capture
    capture_duration = duration_sec + SALEAE_CAPTURE_MARGIN_SEC
    print(f"[block-runner] Starting Saleae capture ({capture_duration}s)...")
    from saleae import automation

    with automation.Manager.connect(port=SALEAE_PORT) as manager:
        device_config = automation.LogicDeviceConfiguration(
            enabled_digital_channels=SALEAE_DIGITAL_CHANNELS,
            digital_sample_rate=SALEAE_DIGITAL_SAMPLE_RATE,
            digital_threshold_volts=1.8,
        )
        capture_config = automation.CaptureConfiguration(
            capture_mode=automation.TimedCaptureMode(
                duration_seconds=capture_duration
            )
        )
        capture = manager.start_capture(
            device_id=SALEAE_DEVICE_ID,
            device_configuration=device_config,
            capture_configuration=capture_config,
        )

        # 8. Brief settle
        time.sleep(0.5)

        # 9. Fire sync edge
        print("[block-runner] Firing block-start sync edge on Pin 11...")
        r = ssh(f"sudo {JETSON_SYNC_EDGE}", capture=True, check=False)
        if r.returncode != 0:
            raise RuntimeError(
                f"sync_edge failed (exit {r.returncode}). "
                f"stdout: {r.stdout!r} stderr: {r.stderr!r}"
            )
        try:
            sync_ns = int(r.stdout.strip())
        except ValueError:
            raise RuntimeError(
                f"sync_edge did not print parseable monotonic_ns: "
                f"stdout={r.stdout!r}"
            )
        block_metadata["sync_edge_jetson_monotonic_ns"] = sync_ns
        print(f"[block-runner]   sync_edge fired at {sync_ns} ns")
        time.sleep(0.1)

        # NEW ORDER (per stress-block restructure 2026-05-25):
        #   10. Start pipeline binary in background
        #   11. Start servo_sweep in background
        #   12. Init grace period (3s) for pipeline to finish startup
        #   13. Verify pipeline still alive after init grace
        #   14. Verify sensor still reachable
        #   15. Start contention (if applicable)
        #   16. Verify contention is active
        #   17. Wait for pipeline binary to complete via `wait` over SSH
        #
        # This ordering prevents the pipeline binary's init sequence
        # (WHO_AM_I check, SW_RESET, sensor configuration) from being
        # disrupted by contention. Contention only runs during the
        # measurement window of the block, after init completes.

        INIT_GRACE_SEC = 3.0

        # 10-11. Start pipeline binary AND servo_sweep in background.
        # The pipeline binary owns Pin 11; servo_sweep owns the PCA9685.
        # Both must run for the full block duration. We wrap the pipeline
        # binary in a shell that writes its exit code to a known file
        # (the SSH "wait $pid" pattern returns 127 because the pid isn't a
        # child of the new SSH shell).
        pipeline_remote_log = f"{block_remote}/pipeline.log"
        pipeline_exit_file = f"/tmp/pipeline_exit_{args.block_id}.txt"
        # Clear any stale exit file before launch
        ssh(f"rm -f {pipeline_exit_file}", check=False)

        if args.pipeline == "host":
            pipeline_bin = JETSON_HOST_PIPELINE_PARITY
            pipeline_extra_args = f"--tree {JETSON_TREE_W75}"
        elif args.pipeline == "mlc":
            pipeline_bin = JETSON_LATENCY_TEST_MLC_W75
            pipeline_extra_args = ""
        elif args.pipeline == "mlc-binary":
            pipeline_bin = JETSON_LATENCY_TEST_MLC_BINARY_W75
            pipeline_extra_args = ""
        else:
            raise ValueError(f"unknown pipeline: {args.pipeline}")

        pipeline_inner = (
            f"timeout {duration_sec} "
            f"{pipeline_bin} {pipeline_extra_args} "
            f"> {pipeline_remote_log} 2>&1; "
            f"echo $? > {pipeline_exit_file}"
        )

        pipeline_cmd = (
            f"sudo nohup bash -c '{pipeline_inner}' "
            f"</dev/null >/dev/null 2>&1 & "
            f"echo $!"
        )

        print(f"[block-runner] Starting {args.pipeline} pipeline binary in background...")
        r = ssh(pipeline_cmd, check=False, capture=True)
        pipeline_pid_str = r.stdout.strip().split("\n")[-1] if r.stdout else ""
        try:
            pipeline_pid = int(pipeline_pid_str)
        except ValueError:
            pipeline_pid = None
            print(f"[block-runner] WARNING: could not parse pipeline pid: {pipeline_pid_str!r}")
        block_metadata["pipeline_pid"] = pipeline_pid
        print(f"[block-runner]   pipeline binary pid: {pipeline_pid}")

        sweep_remote_log = f"{block_remote}/sweep.log"
        print("[block-runner] Starting servo_sweep --mode burst in background...")
        sweep_cmd = (
            f"sudo nohup {JETSON_SERVO_SWEEP} "
            f"--mode burst "
            f"--motion-ms 5000 --still-ms 5000 --burst-period-ms 1000 "
            f"--duration {duration_sec} "
            f"--min-ticks {PWM_MIN_TICKS} --max-ticks {PWM_MAX_TICKS} "
            f"--log {sweep_remote_log} "
            f"> /dev/null 2>&1 &"
        )
        ssh(sweep_cmd)

        # 12. Init grace: give the pipeline binary time to finish startup.
        print(f"[block-runner] Init grace ({INIT_GRACE_SEC}s) for pipeline startup...")
        time.sleep(INIT_GRACE_SEC)

        # 13. Verify pipeline binary is still alive (didn't fail init).
        if pipeline_pid is not None:
            r = ssh(f"kill -0 {pipeline_pid} 2>&1 && echo ALIVE || echo DEAD",
                    capture=True, check=False)
            pipeline_alive = "ALIVE" in r.stdout
            block_metadata["pipeline_alive_after_init"] = pipeline_alive
            if not pipeline_alive:
                print(f"[block-runner]   pipeline binary DIED during init")
                # Read pipeline log for context
                r2 = ssh(f"cat {pipeline_remote_log} 2>&1 | tail -5",
                         capture=True, check=False)
                print(f"[block-runner]   pipeline log tail: {r2.stdout.strip()}")
            else:
                print(f"[block-runner]   pipeline binary alive after {INIT_GRACE_SEC}s init grace")
        else:
            pipeline_alive = False
            block_metadata["pipeline_alive_after_init"] = False

        # 14. Verify sensor still reachable after pipeline init.
        r = ssh("sudo i2cdetect -y -r 7 2>/dev/null | grep -q 6a && echo OK || echo DEAD",
                capture=True, check=False)
        sensor_post_init = "OK" in r.stdout
        block_metadata["sensor_reachable_after_init"] = sensor_post_init
        if not sensor_post_init:
            print(f"[block-runner]   WARNING: sensor unreachable after pipeline init")
        else:
            print(f"[block-runner]   sensor still reachable after init")

        # 15. Start contention/stress AFTER pipeline init.
        contention_start_jetson_monotonic_ns = None
        if args.condition in ("stress", "i2c-contention"):
            # Get monotonic ns just before starting contention.
            # Uses code/jetson/sensor_bringup/print_monotonic_ns which emits
            # clock_gettime(CLOCK_MONOTONIC) as a single integer line.
            r_ts = ssh(
                f"{JETSON_REPO_ABS}/code/jetson/sensor_bringup/print_monotonic_ns",
                capture=True, check=False,
            )
            try:
                contention_start_jetson_monotonic_ns = int(r_ts.stdout.strip())
            except ValueError:
                print(f"[block-runner] WARNING: could not parse monotonic ns: "
                      f"{r_ts.stdout!r}")
                contention_start_jetson_monotonic_ns = None

            if args.condition == "stress":
                # Reduce stress duration to fit remaining block time
                remaining = duration_sec - INIT_GRACE_SEC
                print(f"[block-runner] Starting stress-ng for {remaining:.0f}s...")
                ssh(
                    f"sudo {JETSON_RUN_STRESS_SH} start {int(remaining) + 2}",
                    check=False,
                )
            else:  # i2c-contention
                print("[block-runner] Starting i2c contention (N=3 i2c_hammer)...")
                ssh(
                    f"sudo {JETSON_RUN_STRESS_SH} start-i2c-contention",
                    check=False,
                )
            time.sleep(1.0)  # let contention spin up

        block_metadata["contention_start_jetson_monotonic_ns"] = contention_start_jetson_monotonic_ns

        # 16. Verify the contention state.
        print(f"[block-runner] Verifying state (expected: {args.condition})...")
        if args.condition == "stress":
            verify_cmd = "verify-stress"
        elif args.condition == "i2c-contention":
            verify_cmd = "verify-i2c-contention"
        else:
            verify_cmd = "verify-idle"

        r = ssh(
            f"sudo {JETSON_RUN_STRESS_SH} {verify_cmd}",
            capture=True, check=False,
        )
        cpu_ok = (r.returncode == 0)
        block_metadata["cpu_verification_passed"] = cpu_ok
        block_metadata["cpu_verification_output"] = r.stderr.strip()
        if cpu_ok:
            print(f"[block-runner]   {args.condition} verification: PASS")
        else:
            print(f"[block-runner]   {args.condition} verification: FAIL")
            print(f"[block-runner]   Output: {r.stderr.strip()}")

        # 17. Wait for pipeline binary to complete (either timeout or early exit).
        # Poll for the pid being gone, then read the exit code from the file
        # the launch shell writes when the binary finishes.
        if pipeline_pid is not None:
            print(f"[block-runner] Waiting for pipeline binary (pid {pipeline_pid}) to exit...")
            ssh(
                f"while kill -0 {pipeline_pid} 2>/dev/null; do sleep 0.5; done",
                capture=False, check=False,
            )
            # Read the exit code from the file
            r = ssh(f"cat {pipeline_exit_file} 2>/dev/null",
                    capture=True, check=False)
            try:
                pipeline_exit_code = int(r.stdout.strip())
            except (ValueError, AttributeError):
                pipeline_exit_code = -1
                print(f"[block-runner] WARNING: could not parse exit code from "
                      f"{pipeline_exit_file}: {r.stdout!r}")
            # Cleanup the exit file
            ssh(f"rm -f {pipeline_exit_file}", check=False)
            if pipeline_exit_code not in (0, 124):
                print(
                    f"[block-runner] WARNING: pipeline binary exited with code "
                    f"{pipeline_exit_code}"
                )
        else:
            pipeline_exit_code = -1

        block_metadata["pipeline_exit_code"] = pipeline_exit_code

        # 14-15. Cleanup: stop background stress sources
        if args.condition == "stress":
            print("[block-runner] Stopping stress-ng...")
            ssh(f"sudo {JETSON_RUN_STRESS_SH} stop", check=False)
            time.sleep(0.3)
        elif args.condition == "i2c-contention":
            print("[block-runner] Stopping i2c contention...")
            ssh(f"sudo {JETSON_RUN_STRESS_SH} stop-i2c-contention", check=False)
            time.sleep(0.3)

        ssh("pgrep -x servo_sweep > /dev/null && sudo pkill servo_sweep || true",
            check=False)

        # 16. Wait for Saleae capture to finish; save .sal
        print("[block-runner] Waiting for Saleae capture to finish...")
        capture.wait()
        saleae_local = block_local / "saleae.sal"
        print(f"[block-runner] Saving Saleae capture to {saleae_local}...")
        capture.save_capture(filepath=str(saleae_local))

    # 17. Stop tegrastats
    print("[block-runner] Stopping tegrastats...")
    ssh(
        f"if [ -f {tegrastats_pid_file} ]; then "
        f"  sudo kill $(cat {tegrastats_pid_file}) 2>/dev/null || true; "
        f"  rm -f {tegrastats_pid_file}; "
        f"fi",
        check=False,
    )

    # 18. Scan tegrastats for throttling events
    tegrastats_local = block_local / "tegrastats.log"
    print(f"[block-runner] Copying tegrastats.log from Jetson...")
    subprocess.run(
        ["scp", f"akulswami-jetson:{tegrastats_remote_log}",
         str(tegrastats_local)],
        check=False,
    )

    throttling_events = 0
    throttling_lines = []
    if tegrastats_local.exists():
        with open(tegrastats_local) as f:
            for line in f:
                for ind in THROTTLE_INDICATORS:
                    if ind.lower() in line.lower():
                        throttling_events += 1
                        if len(throttling_lines) < 5:
                            throttling_lines.append(line.rstrip())
    block_metadata["throttling_events"] = throttling_events
    block_metadata["throttling_sample_lines"] = throttling_lines
    if throttling_events > 0:
        print(
            f"[block-runner] Thermal throttling DETECTED: "
            f"{throttling_events} indicator lines"
        )

    # Copy sweep.log
    sweep_local = block_local / "sweep.log"
    subprocess.run(
        ["scp", f"akulswami-jetson:{sweep_remote_log}", str(sweep_local)],
        check=False,
    )

    # 19. Compute block-level inclusion verdict
    block_metadata["included"] = (
        cpu_ok and throttling_events == 0
    )
    if not block_metadata["included"]:
        reasons = []
        if not cpu_ok:
            reasons.append("cpu_verification_failed")
        if throttling_events > 0:
            reasons.append("thermal_throttling")
        block_metadata["exclusion_reason"] = ",".join(reasons)
    else:
        block_metadata["exclusion_reason"] = ""

    block_metadata["finished_at"] = datetime.now().isoformat()

    # Save block metadata
    metadata_path = block_local / "block_metadata.json"
    with open(metadata_path, "w") as f:
        json.dump(block_metadata, f, indent=2)

    print(f"\n[block-runner] === BLOCK {block_name} COMPLETE ===")
    print(f"[block-runner] Included: {block_metadata['included']}")
    if not block_metadata["included"]:
        print(f"[block-runner] Reason: {block_metadata['exclusion_reason']}")
    print(f"[block-runner] Saved to: {block_local}")
    print(f"[block-runner] Metadata: {metadata_path}")

    return 0 if block_metadata["included"] else 1


def main():
    parser = argparse.ArgumentParser(
        description="Run one block of the v7 latency experiment."
    )
    parser.add_argument(
        "--block-id", type=int, required=True,
        help="Block ID (1-40 in pre-registered campaign)."
    )
    parser.add_argument(
        "--condition", choices=["idle", "stress", "i2c-contention"], required=True,
        help="Stress condition per pre-reg §8 (idle / stress) or v7.5 "
             "candidate amendment (i2c-contention: N=3 parallel i2c_hammer "
             "processes on bus 7)."
    )
    parser.add_argument(
        "--pipeline", choices=["host", "mlc", "mlc-binary"], required=True,
        help="Which pipeline drives D1: host_pipeline_parity, "
             "latency_test_mlc_w75 (3-transaction bank-switch read), or "
             "latency_test_mlc_binary_w75 (0-transaction binary-fast variant)."
    )
    parser.add_argument(
        "--duration", type=int, default=300,
        help="Block duration in seconds (default 300s = ~50 trials per §7)."
    )
    parser.add_argument(
        "--btest", action="store_true",
        help="Force btest mode: 30s duration, btest suffix on directory."
    )
    args = parser.parse_args()

    return run_block(args)


if __name__ == "__main__":
    sys.exit(main())

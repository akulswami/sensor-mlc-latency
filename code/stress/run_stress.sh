#!/usr/bin/env bash
# run_stress.sh
#
# CPU stress wrapper for the v7 latency-experiment "stress" condition.
#
# Per pre-reg §8 (stress condition): saturate all CPU cores at the
# highest non-thermal-throttling load achievable on the Jetson Orin
# Nano in MAXN mode.
#
# Per v7 Change 6 item 3: pinned stress-ng version is in
# env/stress-ng-version.txt (currently 0.13.12).
#
# Workload choice rationale: stress-ng's matrix-method=matrixprod
# (3x3 matrix products) provides sustained, deterministic
# arithmetic load that saturates ARM Cortex-A78AE cores without
# requiring large memory footprints (which would interact with
# cache thermal characteristics). Single workload pinned for the
# pre-registered experiment; alternate workloads may be explored
# in post-hoc sensitivity analysis only.
#
# Usage:
#   run_stress.sh start [duration_sec]
#       Start stress workload, optionally for a specified duration.
#       If no duration given, runs until 'run_stress.sh stop' is
#       called (or the process is killed).
#
#   run_stress.sh stop
#       Kill any running stress-ng processes.
#
#   run_stress.sh verify
#       Snapshot /proc/stat + tegrastats to verify stress is at
#       >=95% CPU utilization across all cores. Returns 0 if pass,
#       1 if fail. Output to stderr for human consumption.
#
# Per pre-reg §8: pre-block verification via 'top' or 'tegrastats'.
# This wrapper implements the 'verify' subcommand for that purpose;
# the orchestrator (Gate 4, run_stress_block.py) is responsible for
# logging the snapshot to session.json.

set -euo pipefail

# Pinned configuration.
N_CORES=6                              # Jetson Orin Nano: 6 Cortex-A78AE
STRESS_NG_BIN=/usr/bin/stress-ng
EXPECTED_VERSION="0.13.12"
STRESS_METHOD=matrixprod               # 3x3 matrix products
PID_FILE=/tmp/run_stress.pid

# I2C contention parameters (per pre-reg amendment v7.5 candidate).
#
# Mechanism: N parallel instances of i2c_hammer (a tight C program that
# does back-to-back ioctl-based reads of WHO_AM_I from the sensor under
# test). Earlier shell-loop versions (sudo i2cget in a while loop) failed
# to drive bus contention because sudo overhead dominated; i2c_hammer
# eliminates that.
#
# Empirical sweep on 2026-05-25 with i2c_hammer (n=1000 reads each):
#   N=0 (idle):  median 300us
#   N=1:         median 417us  (+39%)
#   N=2:         median 498us  (+66%)
#   N=3:         median 623us  (+108%)  <-- chosen
#   N=4:         median 733us  (+144%)
#   N=6:         median 977us  (+226%)
#   N=8:         median 1242us (+314%)
#
# N=3 is chosen as a defensibly minimal contention that doubles the median.
# It models a real-world scenario of 3 sensors sharing an I2C bus.
I2C_CONTENTION_N=3
I2C_CONTENTION_BUS=7
I2C_CONTENTION_ADDR=0x6a
I2C_CONTENTION_HAMMER_BIN=/home/akulswami/sensor-mlc-latency/code/jetson/sensor_bringup/i2c_hammer
I2C_CONTENTION_PIDS_FILE=/tmp/run_stress_i2c_pids.txt

# Verify stress-ng matches the pinned version.
verify_version() {
    local actual
    actual=$($STRESS_NG_BIN --version 2>&1 | head -1 | awk '{print $3}')
    if [[ "$actual" != "$EXPECTED_VERSION" ]]; then
        echo "ERROR: stress-ng version $actual != expected $EXPECTED_VERSION" >&2
        echo "       Update env/stress-ng-version.txt or revert the binary." >&2
        return 1
    fi
    return 0
}

# Start the stress workload.
start_stress() {
    local duration_sec="${1:-}"

    # Refuse to start if already running.
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: stress-ng already running (pid $pid)." >&2
            echo "       Stop it first with: $0 stop" >&2
            return 1
        fi
        # Stale pid file; remove.
        rm -f "$PID_FILE"
    fi

    verify_version

    local cmd=("$STRESS_NG_BIN"
               "--cpu" "$N_CORES"
               "--cpu-method" "$STRESS_METHOD"
               "--metrics-brief"
               "--quiet")

    if [[ -n "$duration_sec" ]]; then
        cmd+=("--timeout" "${duration_sec}s")
    fi

    echo "Starting: ${cmd[*]}" >&2
    # Use nohup + redirect + disown so the process survives SSH session close.
    # Without this, ssh closing sends SIGHUP to the process group and stress-ng
    # workers stop loading the CPU even though they remain in the process table.
    nohup "${cmd[@]}" </dev/null >/tmp/stress_ng_stdout.log 2>&1 &
    local pid=$!
    disown $pid 2>/dev/null || true
    echo "$pid" > "$PID_FILE"
    echo "Started stress-ng (pid $pid, nohup'd + disowned)." >&2
    return 0
}

# Stop any running stress workload.
stop_stress() {
    if [[ ! -f "$PID_FILE" ]]; then
        echo "No PID file; nothing to stop." >&2
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "Killing stress-ng (pid $pid)..." >&2
        kill -TERM "$pid" 2>/dev/null || true
        sleep 0.5
        if kill -0 "$pid" 2>/dev/null; then
            echo "Process didn't exit on SIGTERM; SIGKILL..." >&2
            kill -KILL "$pid" 2>/dev/null || true
        fi
    fi

    # Belt and suspenders: stress-ng spawns child processes;
    # killall to clean up.
    pkill -KILL -x stress-ng 2>/dev/null || true

    rm -f "$PID_FILE"
    echo "Stopped." >&2
    return 0
}

# Verify CPU utilization is high enough for stress condition.
# Per §8: >=95% CPU utilization across cores during a stress block.
# Returns 0 if pass, 1 if fail.
verify_stress() {
    # Sample CPU utilization over 2 seconds via /proc/stat
    local cpu1 cpu2 idle1 idle2 total1 total2 usage
    cpu1=$(awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8}' /proc/stat)
    idle1=$(awk '/^cpu / {print $5}' /proc/stat)
    sleep 2
    cpu2=$(awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8}' /proc/stat)
    idle2=$(awk '/^cpu / {print $5}' /proc/stat)

    total1=$cpu1
    total2=$cpu2
    local total_delta=$((total2 - total1))
    local idle_delta=$((idle2 - idle1))
    usage=$(awk "BEGIN {printf \"%.2f\", ($total_delta - $idle_delta) * 100.0 / $total_delta}")

    echo "CPU utilization (2s sample): ${usage}%" >&2

    # Threshold per §8: >=95% for stress condition.
    if awk "BEGIN { exit !($usage >= 95.0) }"; then
        echo "STRESS verify: PASS (utilization >= 95%)" >&2
        return 0
    else
        echo "STRESS verify: FAIL (utilization < 95%)" >&2
        return 1
    fi
}

# Start I2C contention workload.
# Spawns I2C_CONTENTION_N parallel processes each doing back-to-back i2cget
# reads of WHO_AM_I from the sensor under test. Per pre-reg amendment v7.5
# candidate: a real-world scenario where multiple processes contend for the
# same I2C bus.
start_i2c_contention() {
    local n="${1:-$I2C_CONTENTION_N}"

    # Refuse if already running
    if [[ -f "$I2C_CONTENTION_PIDS_FILE" ]]; then
        echo "ERROR: i2c contention pids file exists. Stop first with: $0 stop-i2c-contention" >&2
        return 1
    fi

    if [[ ! -x "$I2C_CONTENTION_HAMMER_BIN" ]]; then
        echo "ERROR: i2c_hammer binary not found at $I2C_CONTENTION_HAMMER_BIN" >&2
        echo "       Build it with: cd $(dirname $I2C_CONTENTION_HAMMER_BIN) && gcc -O2 -o i2c_hammer i2c_hammer.c" >&2
        return 1
    fi

    : > "$I2C_CONTENTION_PIDS_FILE"

    echo "Starting $n parallel i2c_hammer processes on bus $I2C_CONTENTION_BUS addr $I2C_CONTENTION_ADDR..." >&2
    for ((i=1; i<=n; i++)); do
        nohup "$I2C_CONTENTION_HAMMER_BIN" "$I2C_CONTENTION_BUS" "$I2C_CONTENTION_ADDR" \
            </dev/null >/dev/null 2>&1 &
        local pid=$!
        disown $pid 2>/dev/null || true
        echo "$pid" >> "$I2C_CONTENTION_PIDS_FILE"
    done

    sleep 1  # let hammers start
    echo "Started $n i2c_hammer processes; pids in $I2C_CONTENTION_PIDS_FILE." >&2
    return 0
}

# Stop the i2c contention workload.
stop_i2c_contention() {
    if [[ ! -f "$I2C_CONTENTION_PIDS_FILE" ]]; then
        echo "No i2c contention pids file; nothing to stop." >&2
        return 0
    fi

    while IFS= read -r pid; do
        if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
            sudo kill -KILL "$pid" 2>/dev/null || true
        fi
    done < "$I2C_CONTENTION_PIDS_FILE"

    # Belt-and-suspenders: kill any orphaned i2c_hammer processes
    sudo pkill -KILL -x i2c_hammer 2>/dev/null || true

    rm -f "$I2C_CONTENTION_PIDS_FILE"
    echo "Stopped i2c contention." >&2
    return 0
}

# Verify i2c contention is active: count running processes matching the
# i2cget-loop pattern. Per pre-reg v7.5 candidate: a block under
# i2c-contention condition must show >=I2C_CONTENTION_N active i2cget loops.
verify_i2c_contention() {
    local n_running
    n_running=$(pgrep -c -x i2c_hammer 2>/dev/null || echo 0)
    echo "I2C contention: $n_running active i2c_hammer processes (target: $I2C_CONTENTION_N)" >&2
    if [[ "$n_running" -ge "$I2C_CONTENTION_N" ]]; then
        echo "I2C-CONTENTION verify: PASS" >&2
        return 0
    else
        echo "I2C-CONTENTION verify: FAIL (only $n_running running, need $I2C_CONTENTION_N)" >&2
        return 1
    fi
}

# Verify idle (no-stress) condition: <10% non-harness CPU.
# Per §8: idle blocks above 10% mean CPU utilization are flagged.
verify_idle() {
    local cpu1 cpu2 idle1 idle2 total_delta idle_delta usage
    cpu1=$(awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8}' /proc/stat)
    idle1=$(awk '/^cpu / {print $5}' /proc/stat)
    sleep 2
    cpu2=$(awk '/^cpu / {print $2+$3+$4+$5+$6+$7+$8}' /proc/stat)
    idle2=$(awk '/^cpu / {print $5}' /proc/stat)

    total_delta=$((cpu2 - cpu1))
    idle_delta=$((idle2 - idle1))
    usage=$(awk "BEGIN {printf \"%.2f\", ($total_delta - $idle_delta) * 100.0 / $total_delta}")

    echo "CPU utilization (2s sample, idle check): ${usage}%" >&2

    # Threshold per §8: <10% for idle condition (allows measurement harness overhead).
    if awk "BEGIN { exit !($usage < 10.0) }"; then
        echo "IDLE verify: PASS (utilization < 10%)" >&2
        return 0
    else
        echo "IDLE verify: FAIL (utilization >= 10%)" >&2
        return 1
    fi
}

usage() {
    cat <<USAGEMSG
Usage:
  $0 start [duration_sec]    Start stress-ng (optionally with timeout)
  $0 stop                    Stop any running stress-ng
  $0 verify-stress           Check that CPU is currently >=95% utilized
  $0 verify-idle             Check that CPU is currently <10% utilized
  $0 start-i2c-contention    Start I2C contention (per v7.5 candidate)
  $0 stop-i2c-contention     Stop I2C contention loops
  $0 verify-i2c-contention   Check that I2C contention is active
  $0 --help                  Print this message

Environment:
  Pinned: $STRESS_NG_BIN version $EXPECTED_VERSION
  Workload: --cpu $N_CORES --cpu-method $STRESS_METHOD
  Pre-reg: §8 (sensor-mlc-latency)
USAGEMSG
}

case "${1:-}" in
    start)                  shift; start_stress "$@" ;;
    stop)                   stop_stress ;;
    verify-stress)          verify_stress ;;
    verify-idle)            verify_idle ;;
    start-i2c-contention)   shift; start_i2c_contention "$@" ;;
    stop-i2c-contention)    stop_i2c_contention ;;
    verify-i2c-contention)  verify_i2c_contention ;;
    --help|-h|"")           usage ;;
    *)                      echo "Unknown subcommand: $1" >&2; usage; exit 2 ;;
esac

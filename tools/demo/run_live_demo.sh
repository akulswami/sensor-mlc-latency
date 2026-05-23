#!/bin/bash
# run_live_demo.sh
#
# Launches the live MLC classification demo:
#   - servo_sweep on Jetson (burst mode: 5 sec motion / 5 sec still)
#   - mlc_poll_probe3_motion on Jetson (CSV stream to stdout)
#   - demo_live_plot.py locally reads the stream over ssh and plots live
#
# Run from the repo root on the Asus, with the Jetson reachable via the
# 'akulswami-jetson' ssh alias and the binaries already built per
# docs/lab-notebook/2026-05-22.md.
#
# Usage:
#   tools/demo/run_live_demo.sh                  # 5 min duration default
#   tools/demo/run_live_demo.sh --duration 60    # 60 sec
#   tools/demo/run_live_demo.sh --no-servo       # probe only, no servo motion
#
# Close the matplotlib window or Ctrl+C the terminal to stop. The remote
# probe terminates on SSH SIGHUP. The remote servo is killed by an
# explicit `kill` inside the remote shell when the foreground probe exits.

set -uo pipefail   # don't 'set -e' — we want the ssh exit to be handled

DURATION=300       # 5 min default
SERVO_ENABLED=1
SSH_ALIAS="akulswami-jetson"

# Absolute paths on Jetson (sudo over ssh strips PATH; required to be absolute)
JETSON_PROBE="/home/akulswami/sensor-mlc-latency/code/jetson/mlc_pipeline/mlc_poll_probe3_motion"
JETSON_SERVO="/home/akulswami/sensor-mlc-latency/code/jetson/servo/servo_sweep"

# Local plot script — relative to this script's location so it works from any pwd
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOCAL_PLOT="$SCRIPT_DIR/demo_live_plot.py"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --duration)   DURATION="$2"; shift 2 ;;
    --no-servo)   SERVO_ENABLED=0; shift ;;
    -h|--help)
      sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$LOCAL_PLOT" ]]; then
  echo "ERROR: demo_live_plot.py not found at $LOCAL_PLOT" >&2
  exit 1
fi

echo "Live demo:" >&2
echo "  duration: ${DURATION} sec" >&2
echo "  servo:    $([ $SERVO_ENABLED -eq 1 ] && echo 'ON (5s motion / 5s still)' || echo 'OFF')" >&2
echo "  jetson:   $SSH_ALIAS" >&2
echo "" >&2
echo "Matplotlib window will open. Close it or Ctrl+C here to stop." >&2
echo "" >&2

# Build the remote command. Put servo_sweep in background (if enabled),
# sleep 1 to let it settle, then run probe in foreground. When probe
# exits, kill the servo. The probe's stdout is CSV which we pipe to
# python on the Asus.
if [[ $SERVO_ENABLED -eq 1 ]]; then
  REMOTE_CMD="
    sudo $JETSON_SERVO --mode burst --motion-ms 5000 --still-ms 5000 \\
         --duration $DURATION --log /tmp/demo_live_servo.log \\
         > /dev/null 2>&1 &
    SERVO_PID=\$!
    sleep 1
    sudo $JETSON_PROBE --pulsed --duration $DURATION --stdout 2>/dev/null
    kill \$SERVO_PID 2>/dev/null
    wait
  "
else
  REMOTE_CMD="
    sudo $JETSON_PROBE --pulsed --duration $DURATION --stdout 2>/dev/null
  "
fi

ssh "$SSH_ALIAS" "$REMOTE_CMD" | python3 "$LOCAL_PLOT"

echo "" >&2
echo "Demo stopped." >&2

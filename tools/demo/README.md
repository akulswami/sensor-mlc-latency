# tools/demo

Demonstration tooling for the trained MLC classifier. **NOT** part of
the measurement pipeline — these are reference/verification artifacts
built on 2026-05-22 evening to validate the end-to-end flash chain and
to provide a visual demo of the trained classifier in action.

## Contents

| File | Purpose |
|---|---|
| `run_live_demo.sh` | Launcher. Runs servo_sweep + mlc_poll_probe3_motion on Jetson over ssh, pipes CSV stream to local Python plot. |
| `demo_live_plot.py` | matplotlib live plot. Reads CSV from stdin, shows rolling 15-sec window of accel + MLC decision strip. Updates at 15 FPS. |
| `demo_replay.py` | matplotlib post-hoc playback of a recorded capture at 1× wall-clock speed. Three panels: accel, MLC decision, servo phase ground truth. Used the night of 2026-05-22 before the live version was built. |

## Prerequisites

- Jetson reachable at ssh alias `akulswami-jetson`.
- `mlc_poll_probe3_motion` built on Jetson against `mlc_motion_w75.h`:
  ```
  cd code/jetson/mlc_pipeline
  gcc -O2 -Wall -I../../mlc_config \
      -DMLC_CONFIG_HEADER=\"mlc_motion_w75.h\" \
      -o mlc_poll_probe3_motion mlc_poll_probe_v3.c
  ```
- `servo_sweep` built on Jetson (already present in repo).
- LSM6DSOX physically mounted on the servo rig (sessions 1-3 mount).
- PCA9685 connected (bus 1, address 0x60). Servo wired to channel 0.
- On the Asus: Python 3 with matplotlib and numpy.

## Live demo

From the repo root on the Asus:

```
tools/demo/run_live_demo.sh
```

A matplotlib window opens. The servo physically oscillates 5 sec
motion / 5 sec still in burst mode for 5 minutes. The plot updates in
real time showing the accelerometer Z-axis trace and an MLC decision
strip (red = motion, grey = still). The MLC should track the servo's
motion phases with a few hundred ms of latency (one MLC window at 75
samples / 104 Hz = 721 ms).

Options:

```
tools/demo/run_live_demo.sh --duration 60     # shorter run
tools/demo/run_live_demo.sh --no-servo        # probe alone, no servo
```

Close the matplotlib window or Ctrl+C the terminal to stop. The remote
servo and probe both terminate.

## Replay a captured run

Two files are needed: a per-poll CSV from the probe and a servo log
from servo_sweep. See `mlc_poll_probe_v3.c --csv` and
`servo_sweep --log`.

```
python3 tools/demo/demo_replay.py \
    --capture /path/to/probe.csv \
    --servo   /path/to/servo.log
```

## Known limitations

These scripts are demo-quality, not measurement-quality:

- **Probe over-samples accel.** The probe polls at ~500 Hz, the
  accelerometer ODR is 208 Hz. Same sample appears 2-3x in
  consecutive rows. Fine for visualization, not for any quantitative
  analysis.
- **MLC cold-start transient.** The first 1-2 MLC windows after flash
  often show a spurious motion classification while the IIR HP filter
  converges from zero initial state. Visible in the plot's first
  ~1 sec.
- **Probe/servo clock alignment is approximate.** The launcher
  `sleep 1` between starting the servo and starting the probe is a
  rough synchronization; the offline replay script defaults to
  assuming a 2-sec lag for plot alignment. Not suitable for
  latency measurements.

For measurement-grade work see `code/jetson/mlc_pipeline/latency_test_mlc.c`
and the pre-registration in `docs/pre-registration.md`.

## Provenance

Built 2026-05-22 evening session as part of verifying the end-to-end
flash chain for the custom-trained 2-class motion-vs-still MLC. See
`docs/lab-notebook/2026-05-22.md` for the verification narrative.

The first demo captured run (60 sec, burst mode, recorded by
mlc_poll_probe3_motion + servo_sweep) is the reference dataset for
`demo_replay.py`. If a fresh reference capture is needed:

```
ssh akulswami-jetson '
  sudo /home/akulswami/sensor-mlc-latency/code/jetson/servo/servo_sweep \
       --mode burst --motion-ms 5000 --still-ms 5000 --duration 60 \
       --log /tmp/demo_servo.log > /dev/null 2>&1 &
  sleep 2
  sudo /home/akulswami/sensor-mlc-latency/code/jetson/mlc_pipeline/mlc_poll_probe3_motion \
       --pulsed --duration 60 --csv /tmp/demo_capture.csv
'
scp akulswami-jetson:/tmp/demo_capture.csv /tmp/demo_files/
scp akulswami-jetson:/tmp/demo_servo.log /tmp/demo_files/
```

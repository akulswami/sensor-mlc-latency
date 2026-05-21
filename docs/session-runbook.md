# Session runbook — training data collection

Operational procedure for collecting one training-data session per
`docs/training-data-spec.md`. Each session produces motion and still
recordings for the custom MLC and the host parity classifier.

Sessions must be ≥1 day apart per the spec to capture day-to-day
variation. Plan for at least 3 sessions before training.

---

## Before you start

Wall-clock budget: **~50 minutes** per session.
- Pre-session: ~10 min
- Recording: ~40 min (2 classes × 20 min)
- Post-session: ~5-10 min

What you need at the bench:
- Asus desktop with Logic 2 installed
- Jetson reachable via SSH alias `akulswami-jetson`
- Saleae Logic Pro 8 connected via USB to Asus, probes wired:
  - D0 → Jetson Pin 15 (sensor INT1)
  - D2 → PCA9685 channel 0 PWM
- USB power brick plugged into wall and connected to PCA9685 V+
- Servo rig mounted (servo on heavy base, sensor on horn near tip,
  wires routed with slack)

---

## Pre-session (~10 min)

### 1. Bench verification

Visually confirm:
- [ ] Servo body is firmly attached to its heavy base (try to wobble
      it gently; it should not shift)
- [ ] Sensor is firmly attached to the servo horn (try to wobble; it
      should not move relative to the horn)
- [ ] Sensor wires have slack and do not pull on the horn through its
      full motion range (rotate horn by hand carefully if needed)
- [ ] No new objects near the rig (a coffee cup vibrating on the
      bench will contaminate "still" data)

### 2. Power and connectivity

```bash
# Bench state verification
ssh akulswami-jetson 'echo "=== Bus 7 (sensor) ===" && \
  sudo i2cdetect -y -r 7 && \
  echo "=== Bus 1 (PCA9685) ===" && \
  sudo i2cdetect -y -r 1 && \
  echo "=== tegrastats ===" && \
  tegrastats --interval 1000 | head -2 && \
  echo "=== GPIO ===" && \
  sudo gpioinfo gpiochip0 | grep -E "line\s+85|line 112" && \
  echo "=== repo state ===" && \
  cd ~/sensor-mlc-latency && git log --oneline -3 && git status'
```

Expected:
- Bus 7: `0x6A` (sensor)
- Bus 1: `UU` at `0x25`, `UU` at `0x40`, `60`, `70`
- tegrastats: VDD_IN ~5-7W, CPU mostly idle (single-digit percentages)
- GPIO lines 85 and 112: `unused`
- Repo: at latest origin/main, working tree clean

If anything is off, stop. Do not start a session with a degraded
bench. Look at `docs/lab-notebook/` for prior debugging entries.

### 3. PCA9685 initialization

The chip retains its configuration across runs but loses it on power
cycle. Re-init defensively before every session:

```bash
ssh akulswami-jetson 'bash -s' <<'EOF'
ADDR=0x60
BUS=1
sudo i2cset -y $BUS $ADDR 0x00 0x11  # sleep
sudo i2cset -y $BUS $ADDR 0xFE 0x79  # PRESCALE for ~50 Hz nominal
sudo i2cset -y $BUS $ADDR 0x00 0x01  # wake
sleep 0.01
sudo i2cset -y $BUS $ADDR 0x00 0x21  # auto-increment

# Center the servo
sudo i2cset -y $BUS $ADDR 0x06 0x00
sudo i2cset -y $BUS $ADDR 0x07 0x00
sudo i2cset -y $BUS $ADDR 0x08 0x33
sudo i2cset -y $BUS $ADDR 0x09 0x01

# Readback to confirm
echo "MODE1: $(sudo i2cget -y $BUS $ADDR 0x00)"
echo "PRESCALE: $(sudo i2cget -y $BUS $ADDR 0xFE)"
EOF
```

Expected: `MODE1: 0xa1`, `PRESCALE: 0x79`. The servo should snap to
the center position.

### 4. Logic 2 readiness

- [ ] Launch Logic 2 on Asus desktop
- [ ] Verify "Connected" appears in the title bar (real device, not
      simulation)
- [ ] Verify automation server is enabled (Settings → Automation)
- [ ] Quick API connectivity test (catches a server-not-running
      situation before the session burns time):

```bash
python3 -c "
from saleae import automation
with automation.Manager.connect(port=10430) as manager:
    devices = manager.get_devices(include_simulation_devices=False)
    ids = [d.device_id for d in devices]
    assert '6F657C15C3EEE446' in ids, f'Real device missing. Got: {ids}'
    print('OK')
"
```

Expected: `OK`. If you get a ConnectionRefusedError, the automation
server isn't enabled in Logic 2 settings.

### 5. Sensor sanity check

Run a 5-second logger capture to confirm the sensor is producing
reasonable data:

```bash
ssh akulswami-jetson 'cd /tmp && sudo rm -f sanity.csv && \
  sudo timeout 5 ~/sensor-mlc-latency/code/jetson/imu_logger/imu_logger \
    --odr 208 sanity.csv 2>&1; \
  echo "---"; \
  echo "X stddev: $(awk -F"," "NR>1 {sum+=\$2; sumsq+=\$2*\$2; n++} END {mean=sum/n; print sqrt(sumsq/n - mean*mean)}" sanity.csv)"; \
  echo "Z mean (should be ~+/-0.97g): $(awk -F"," "NR>1 {sum+=\$4; n++} END {print sum/n}" sanity.csv)"'
```

Expected:
- "Sensor configured at 208 Hz" in stderr
- "Stopped. Wrote ~1040 samples..." at end
- X stddev: small (~0.001-0.01g, noise floor)
- Z mean: roughly ±0.97g (gravity along one axis depending on sensor
  orientation)

If X stddev is large (>0.05g) with servo at rest, something is
vibrating the rig. Investigate before recording.

### 6. Process hygiene

Look for stale background processes that could contaminate the
session (this caught us once — 6 Python processes from a forgotten
test were burning all CPU cores for 5 days):

```bash
ssh akulswami-jetson 'ps aux --sort=-%cpu | head -10'
```

Top of the list should be sshd and system processes, all at low CPU%.
If anything else is using significant CPU, identify and kill it
before recording — it will affect the host pipeline's timing once we
get to measurements.

---

## Session execution (~40 min)

### Recording

One command does both classes:

```bash
cd ~/sensor-mlc-latency && \
python3 code/orchestrator/run_session.py \
  --session-date YYYY-MM-DD \
  --class both \
  --duration 1200
```

Replace `YYYY-MM-DD` with today's date. Duration 1200 = 20 min per
class (10 min minimum is required for 200-sample windows; 20 min
gives margin for labeling-discard losses).

### What to watch during the run

While the orchestrator is running, the servo will:
- Hold center silently for 20 min during the still class
- Oscillate 0°↔150° at 1 Hz during the motion class

Watch for:
- Servo behavior drift (does it sometimes fail to reach an extreme?)
- Visible wire tugging on the horn
- The heavy base shifting on the bench
- Any new noises from the servo (buzzing = motor under stress)

If anything looks wrong **after the still class has finished but
before motion starts**, you can Ctrl+C the orchestrator and restart.
If something fails mid-motion, that 20 min of motion data is
contaminated; abort and restart from scratch.

### If you need to abort

```bash
# Kill the orchestrator's Python process locally
Ctrl+C in the running terminal

# Kill anything left running on the Jetson
ssh akulswami-jetson 'sudo pkill -f imu_logger; sudo pkill -f servo_sweep'

# Clean up the partial session directory
sudo rm -rf data/training/<the-session-date>/
```

Then start over from the pre-session checklist (in particular, the
servo may have been left at an extreme; re-center it).

---

## Post-session (~10 min)

### 1. Verify file integrity

```bash
SESSION_DATE=2026-05-21  # set to today's date
cd ~/sensor-mlc-latency/data/training/$SESSION_DATE

echo "=== Files ==="
ls -la still/ motion/

echo ""
echo "=== Line counts (expected ~250000 at 208 Hz × 1200 sec × 1.02 measured rate) ==="
wc -l still/accel.csv motion/accel.csv

echo ""
echo "=== Last-line integrity (expect 4 fields each) ==="
echo "still:"
tail -3 still/accel.csv | awk -F',' '{print NF, "fields"}'
echo "motion:"
tail -3 motion/accel.csv | awk -F',' '{print NF, "fields"}'

echo ""
echo "=== Variance check (motion / still ratio should be 50x+) ==="
echo -n "still X stddev: "
awk -F',' 'NR>1 {sum+=$2; sumsq+=$2*$2; n++} END {mean=sum/n; print sqrt(sumsq/n - mean*mean)}' still/accel.csv
echo -n "motion X stddev: "
awk -F',' 'NR>1 {sum+=$2; sumsq+=$2*$2; n++} END {mean=sum/n; print sqrt(sumsq/n - mean*mean)}' motion/accel.csv

echo ""
echo "=== Sweep log integrity ==="
echo "expected ~1200 events: $(grep -cE "TO_MAX|TO_MIN" motion/sweep.log)"
```

Expected:
- 4 files in still/ (accel.csv, saleae.sal)
- 5 files in motion/ (accel.csv, saleae.sal, sweep.log)
- CSV line counts: ~255,000 each (208 Hz × 1200 sec × ~1.02 measured)
- All last 3 lines: 4 fields, no truncation
- Motion stddev / Still stddev ratio: ≥50× (motion should overwhelm
  noise floor)
- Sweep log: ~1200 transition events (1 per sec for 1200 sec)

### 2. Spot-check Saleae captures

Open both .sal files in Logic 2:

- **still/saleae.sal**: D0 shows continuous ~208 Hz pulse train; D2
  shows steady PWM (constant duty cycle, no transitions) for the
  whole capture
- **motion/saleae.sal**: D0 shows continuous ~208 Hz pulse train; D2
  shows PWM with visible duty-cycle transitions every second

If either capture is empty or missing channels, investigate before
treating the session as valid.

### 3. Session notes

Write `notes.md` in the session directory:

```bash
cat > ~/sensor-mlc-latency/data/training/$SESSION_DATE/notes.md << 'EOF'
# Session notes — YYYY-MM-DD

## Conditions
- Ambient temperature: ~XX°C
- Time of day: HH:MM
- Anything unusual at the bench

## Observations during session
- (anything you noticed during the recording)

## Post-session checks
- File integrity: PASS / FAIL
- Variance ratio: motion/still = XX×
- Saleae captures: PASS / FAIL
- Anything anomalous

## Decision
- Use this session: YES / NO (rationale)
EOF
```

The point of this file is not the data — it's the assessment of
whether the session is usable. The MLC training will pull from
`data/training/*/` directories indiscriminately; if you've recorded a
bad session, *mark it here* so you (or future-you) doesn't include
it.

### 4. Lab notebook entry

Add a brief entry to `docs/lab-notebook/YYYY-MM-DD.md` with anything
noteworthy from the session. The notebook is the historical record;
notes.md is the per-session assessment.

### 5. Commit anything that should be committed

The CSV and .sal files are typically *not* committed (they're large
and the .gitignore should already exclude `data/raw/` patterns).
Confirm what your repo's policy is before committing session data —
the spec implies session data should be tracked for reproducibility,
but the practical answer may be "tracked via Git LFS or hosted
externally with a manifest."

Either way, the session directory layout is in place; commit decision
is per-session.

---

## When to NOT use a session

Mark a session as `Use: NO` in notes.md if any of:

- Variance ratio (motion / still) < 50×
- Truncated rows in CSVs (more than 1 partial row, or partial rows
  anywhere except the very end)
- Sweep log shows < 80% of expected transition count
- Saleae .sal shows channel signal anomalies
- The servo audibly stalled or made unusual noise during recording
- Any human disruption (you bumped the bench, ran a competing
  workload on the Jetson, etc.)

Don't try to salvage a bad session by cropping the bad parts. Just
record another one. With 3 sessions minimum, having a 4th is fine.

---

## After 3+ usable sessions

Once you have 3 sessions marked `Use: YES`, the data is ready for the
next step: MEMS Studio classifier training. See `docs/training-data-spec.md`
section "Feature set" for the configuration to use.

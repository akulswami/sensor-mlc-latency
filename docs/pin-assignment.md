# Pin assignment — Jetson Orin Nano 40-pin header

Source: `sudo /opt/nvidia/jetson-io/jetson-io.py`. The 40-pin header
exposes i2c8 on pins 3 (SDA) and 5 (SCL) by default; this maps to
/dev/i2c-7 in the kernel (verified via i2cdetect 2026-05-01).

SPI was attempted first and abandoned — see lab notebook 2026-05-01 and
pre-registration amendment 2026-05-01 (evening) for details. SPI device
nodes (/dev/spidev0.0 etc.) are still enabled in jetson-io but unused.

## Sensor wiring (LSM6DSOX → Jetson, I2C mode)

| LSM6DSOX pin | Jetson pin | Jetson function | Notes |
|---|---|---|---|
| VIN | Pin 1 or 17 | 3.3V | Adafruit breakout has on-board regulator; 3.3V or 5V both ok, use 3.3V |
| GND | Pin 6, 9, 14, 20, 25, 30, 34, or 39 | GND | any GND |
| SCL | Pin 5 | i2c8 SCL | I2C clock; 10K pull-up on Adafruit breakout |
| SDA | Pin 3 | i2c8 SDA | I2C data; 10K pull-up on Adafruit breakout |
| I1 (INT1) | Pin 15 | GPIO input | sensor interrupt to host (silkscreen says "I1"); also probed by Saleae. I2 unused. |

Bus number: /dev/i2c-7 (verified via i2cdetect on 2026-05-01).
Sensor I2C address: 0x6A (default; not jumpered).

SDO and CS pins are unused in I2C mode and are left disconnected.


## PCA9685 wiring (servo control)

| PCA9685 pin | Jetson pin | Jetson function | Notes |
|---|---|---|---|
| VCC | Pin 1 | 3.3V | logic supply for PCA9685 |
| GND | Pin 6 | GND | common ground |
| SCL | Pin 28 | i2c1 SCL | I2C clock, bus 1 |
| SDA | Pin 27 | i2c1 SDA | I2C data, bus 1 |
| OE | (floating) | — | leave disconnected; internal pull-down enables outputs |
| V+ | external 5V supply | — | servo power rail; **do NOT** source from Jetson |

Bus number: /dev/i2c-1 (verified via i2cdetect 2026-05-12). Pins 27/28
expose i2c1 in this device tree configuration; this is independent
silicon from i2c-7 used by the sensor, so PCA9685 traffic does not
contend with sensor reads.

PCA9685 I2C address: **0x60**. The board ships at default 0x40, which
collides with the on-carrier INA3221 power monitor. An address-select
pad was bridged on 2026-05-12 to move the chip off 0x40; bit 5 was
set (the pad labeled A5 on the PCB silkscreen, intended target was A0
but the wrong pad was bridged — see lab notebook 2026-05-12). 0x60 is
not colliding with anything and is functionally equivalent to the
originally planned 0x41 for this experiment. The all-call address 0x70
is also enabled by default (PCA9685 power-up behavior, separate from
the individual address).

INA3221 sanity check: tegrastats should report sensible non-zero
VDD_IN values when PCA9685 is connected. Zero values would indicate
address contention.

## Measurement-instrumented GPIO

| Function | Jetson pin | Direction | Notes |
|---|---|---|---|
| Decision-edge output | Pin 11 | GPIO output | Toggled by host pipeline on positive classification; probed by Saleae |

## Saleae probe assignments

| Saleae channel | Probed signal | Source |
|---|---|---|
| D0 | LSM6DSOX INT1 | Jetson Pin 15 |
| D1 | Decision-edge GPIO | Jetson Pin 11 |
| D2 | PCA9685 channel 0 PWM (servo control / training-label ground truth) | PCA9685 OUT0 PWM pin |
| D3 | (unused) | — |
| A3 | (used during 2026-05-12 V+ rail diagnostics; not part of normal probe layout) | — |
| GND | GND | Pin 6 (or any GND) |

D0 and D1 are required for latency measurement. D2 is required for training
data collection (provides ground-truth labels for motion vs. still windows
per `docs/training-data-spec.md`); it is also retained during measurement
runs as a redundant timing reference.

The earlier SPI-decode allocation (D2=spi1_sck, D3=spi1_cs0) was used
during the SPI bring-up phase (2026-04-29 → 2026-05-01); since the move
to I²C and the addition of the servo rig, those probes are no longer
wired. See lab notebook 2026-05-01 for the SPI→I²C transition.



## i2cdetect `-r` flag is required, not optional

To verify either bus is functional, **always use `sudo i2cdetect -y -r <bus>`**.
The `-r` flag forces read-based probing. Without it, `i2cdetect` defaults to
SMBus Quick Write probing, which returns false-negatives for many
breakout-board devices including the LSM6DSOX at 0x6A and the PCA9685 at 0x60
used in this project.

This has burned multiple debugging detours: see lab notebook `2026-05-24.md`
line 284 ("`i2cdetect -r` flag failure mode") for the canonical writeup, and
`2026-05-25.md` for the orchestrator-bug-fix episode where this assumption
came up again.

Quick reference commands:

```bash
# Sensor bus (LSM6DSOX expected at 0x6A)
sudo i2cdetect -y -r 7

# Servo bus (PCA9685 expected at 0x60, also INA3221 at 0x40)
sudo i2cdetect -y -r 1
```

A device showing up here is necessary but not sufficient evidence it's
configured correctly. For the LSM6DSOX, the WHO_AM_I register (0x0F) should
read 0x6C. For the PCA9685, MODE1 (0x00) should be readable and non-zero
after init.

For sensor configuration verification (which window length is flashed, what
the MLC tree is doing), `i2cdetect` is insufficient; see
`docs/lab-notebook/2026-05-25.md` for the post-flash behavioral verification
pattern using `mlc_poll_probe` or direct MLC0_SRC readback.

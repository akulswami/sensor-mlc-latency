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

| Saleae channel | Probed signal | Jetson pin |
|---|---|---|
| D0 | LSM6DSOX INT1 | Pin 15 |
| D1 | Decision-edge GPIO | Pin 11 |
| D2 | spi1_sck (optional, for protocol decode) | Pin 23 |
| D3 | spi1_cs0 (optional) | Pin 24 |
| GND | GND | Pin 6 (or any GND) |

D0 and D1 are required for latency measurement. D2/D3 are optional but useful for debugging.

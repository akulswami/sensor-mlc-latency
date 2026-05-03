# Pin assignment — Jetson Orin Nano 40-pin header

Source: `sudo /opt/nvidia/jetson-io/jetson-io.py` after enabling spi1.
Spidev mapping: `/dev/spidev0.0` → `3210000.spi` (the 40-pin header SPI1).

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

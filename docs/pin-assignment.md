# Pin assignment — Jetson Orin Nano 40-pin header

Source: `sudo /opt/nvidia/jetson-io/jetson-io.py` after enabling spi1.
Spidev mapping: `/dev/spidev0.0` → `3210000.spi` (the 40-pin header SPI1).

## Sensor wiring (LSM6DSOX → Jetson)

| LSM6DSOX pin | Jetson pin | Jetson function | Notes |
|---|---|---|---|
| VIN          | Pin 1 or 17 | 3.3V         | Adafruit breakout has on-board regulator; 3.3V or 5V both ok, use 3.3V |
| GND          | Pin 6, 9, 14, 20, 25, 30, 34, or 39 | GND | any GND |
| SCL / SCK    | Pin 23 | spi1_sck       | SPI clock |
| SDA / SDI / MOSI | Pin 19 | spi1_dout  | host -> sensor |
| SDO / MISO   | Pin 21 | spi1_din       | sensor -> host |
| CS           | Pin 24 | spi1_cs0       | chip select |
| INT (INT1)   | Pin 15 | GPIO input     | sensor interrupt to host; also probed by Saleae |

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

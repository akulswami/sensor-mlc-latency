"""
LSM6DSOX WHO_AM_I sanity check.

Reads register 0x0F over SPI. Expected return value: 0x6C.
This confirms:
  - SPI bus is working
  - CS line is correct
  - MOSI / MISO / SCK are wired correctly
  - Sensor is powered
"""
import spidev
import sys

WHO_AM_I_REG = 0x0F
EXPECTED_ID = 0x6C
SPI_READ_FLAG = 0x80  # MSB set = read; clear = write

spi = spidev.SpiDev()
spi.open(0, 0)  # /dev/spidev0.0 = 3210000.spi (40-pin header SPI1, CS0)
spi.max_speed_hz = 1_000_000  # 1 MHz, conservative; LSM6DSOX supports up to 10 MHz
spi.mode = 0b11  # CPOL=1, CPHA=1 (SPI mode 3) — required by LSM6DSOX

# SPI transaction: send [reg | read_flag, dummy], read back [garbage, value]
tx = [WHO_AM_I_REG | SPI_READ_FLAG, 0x00]
rx = spi.xfer2(tx)

who_am_i = rx[1]
print(f"WHO_AM_I register read: 0x{who_am_i:02X} (expected 0x{EXPECTED_ID:02X})")

spi.close()

if who_am_i == EXPECTED_ID:
    print("PASS: sensor responded correctly. SPI link verified.")
    sys.exit(0)
else:
    print("FAIL: sensor did not respond as expected.")
    sys.exit(1)

"""
LSM6DSOX WHO_AM_I sanity check, I2C version.

Reads register 0x0F over I2C. Expected return value: 0x6C.
This confirms:
  - I2C bus is working
  - Sensor is at default address 0x6A
  - Sensor is responsive

Background: SPI bring-up failed on this JetPack 6.2.2 + Orin Nano combo.
i2cdetect confirmed sensor alive at 0x6A on /dev/i2c-7. Project switched
to I2C for both pipelines. See pre-registration amendment 2026-05-01.
"""
import sys
from smbus2 import SMBus

I2C_BUS = 7              # /dev/i2c-7 (Jetson Orin Nano pins 3/5 = i2c8 in jetson-io)
LSM6DSOX_ADDR = 0x6A     # Default 7-bit address (Adafruit breakout, no jumper)
WHO_AM_I_REG = 0x0F
EXPECTED_ID = 0x6C

with SMBus(I2C_BUS) as bus:
    who_am_i = bus.read_byte_data(LSM6DSOX_ADDR, WHO_AM_I_REG)

print(f"WHO_AM_I register read: 0x{who_am_i:02X} (expected 0x{EXPECTED_ID:02X})")

if who_am_i == EXPECTED_ID:
    print("PASS: sensor responded correctly. I2C link verified.")
    sys.exit(0)
else:
    print("FAIL: sensor did not respond as expected.")
    sys.exit(1)

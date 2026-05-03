"""
LSM6DSOX raw accelerometer read over I2C.

Configures accelerometer at 416 Hz, +/-2g, BDU enabled.
Reads 6 bytes (X/Y/Z low+high) at 5 Hz, prints g values.

Tilt or shake the sensor; values should change accordingly.
At rest with the breakout flat, Z should read ~1.0g, X and Y near 0.
"""
import time
import struct
from smbus2 import SMBus

I2C_BUS = 7
LSM6DSOX_ADDR = 0x6A

# Register map
CTRL1_XL = 0x10
CTRL3_C  = 0x12
OUTX_L_A = 0x28

# Configuration values
CTRL1_XL_VAL = 0x60   # ODR_XL = 416 Hz, FS_XL = +/-2g, LPF2 disabled
CTRL3_C_VAL  = 0x44   # BDU=1, IF_INC=1, all else default

# +/-2g range -> 0.061 mg per LSB per the datasheet
SENSITIVITY_G_PER_LSB = 0.061e-3

def configure(bus):
    bus.write_byte_data(LSM6DSOX_ADDR, CTRL1_XL, CTRL1_XL_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, CTRL3_C, CTRL3_C_VAL)
    # Datasheet says boot/turn-on settling is well under 100 ms;
    # 50 ms is a comfortable margin.
    time.sleep(0.05)

def read_accel_g(bus):
    raw = bus.read_i2c_block_data(LSM6DSOX_ADDR, OUTX_L_A, 6)
    x, y, z = struct.unpack('<hhh', bytes(raw))
    return (x * SENSITIVITY_G_PER_LSB,
            y * SENSITIVITY_G_PER_LSB,
            z * SENSITIVITY_G_PER_LSB)

def main():
    with SMBus(I2C_BUS) as bus:
        configure(bus)
        print("Reading accelerometer at 5 Hz. Ctrl+C to stop.")
        print("Tilt or move the sensor and watch the values.")
        print(f"{'X (g)':>10} {'Y (g)':>10} {'Z (g)':>10}")
        try:
            while True:
                ax, ay, az = read_accel_g(bus)
                print(f"{ax:>10.3f} {ay:>10.3f} {az:>10.3f}")
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\nStopped.")

if __name__ == '__main__':
    main()

"""
LSM6DSOX single-tap detection: bring-up test.

Configures the chip's built-in single-tap detector and routes the tap
event to the I1 pin. Polls TAP_SRC over I2C to confirm taps were
detected and to print which axis fired.

Important: this uses the LSM6DSOX's hardware single-tap block, NOT the
MLC. The MLC will be programmed separately via a .ucf file from ST
MEMS Studio. This script exists only to verify INT-edge generation
on the Saleae.

Wire Saleae D0 to sensor I1 pin and GND to GND. Set Logic 2 trigger to
rising edge on D0 with a 5-second buffer. Run this script, then tap
the breadboard sharply.
"""
import time
from smbus2 import SMBus

I2C_BUS = 7
LSM6DSOX_ADDR = 0x6A

# Registers
CTRL1_XL    = 0x10
TAP_CFG0    = 0x56
TAP_CFG1    = 0x57
TAP_CFG2    = 0x58
TAP_THS_6D  = 0x59
INT_DUR2    = 0x5A
WAKE_UP_THS = 0x5B
MD1_CFG     = 0x5E
TAP_SRC     = 0x1C

# Configuration values
CTRL1_XL_VAL    = 0x60   # ODR 416 Hz, FS +/-2g
TAP_CFG0_VAL    = 0x0E   # Enable tap on Z, Y, X (bits 1-3); LIR=0 (pulse, not latched)
                         # Set bit 0 (LIR) high if you want the INT to stay until cleared.
TAP_THS_VAL     = 0x88   # Bit 7 = enable; threshold = 0x08 = 500 mg
INT_DUR2_VAL    = 0x06   # quiet=1, shock=2 in default LSB units; tunable
WAKE_UP_THS_VAL = 0x00   # SINGLE_DOUBLE_TAP=0 -> single-tap only
MD1_CFG_VAL     = 0x40   # INT1_SINGLE_TAP -> route single tap to I1 pin

def configure_tap(bus):
    bus.write_byte_data(LSM6DSOX_ADDR, CTRL1_XL,    CTRL1_XL_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, TAP_CFG0,    TAP_CFG0_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, TAP_CFG1,    TAP_THS_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, TAP_CFG2,    TAP_THS_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, TAP_THS_6D,  TAP_THS_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, INT_DUR2,    INT_DUR2_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, WAKE_UP_THS, WAKE_UP_THS_VAL)
    bus.write_byte_data(LSM6DSOX_ADDR, MD1_CFG,     MD1_CFG_VAL)
    time.sleep(0.05)

def poll_tap_src(bus):
    """Read and decode TAP_SRC. Bit 6 = TAP_IA (any tap detected this cycle)."""
    src = bus.read_byte_data(LSM6DSOX_ADDR, TAP_SRC)
    tap_detected = bool(src & 0x40)
    sign         = 'neg' if (src & 0x08) else 'pos'
    z_tap        = bool(src & 0x04)
    y_tap        = bool(src & 0x02)
    x_tap        = bool(src & 0x01)
    return tap_detected, sign, z_tap, y_tap, x_tap, src

def main():
    with SMBus(I2C_BUS) as bus:
        configure_tap(bus)
        print("Tap detector configured. Threshold = 500 mg per axis.")
        print("Tap the breadboard sharply. Polling TAP_SRC at 50 Hz.")
        print("Watch the Saleae for rising edges on D0.")
        print("Ctrl+C to stop.\n")
        try:
            while True:
                detected, sign, z, y, x, raw = poll_tap_src(bus)
                if detected:
                    axes = []
                    if x: axes.append('X')
                    if y: axes.append('Y')
                    if z: axes.append('Z')
                    print(f"TAP detected: axes={','.join(axes) or '?'}, "
                          f"sign={sign}, raw=0x{raw:02X}")
                time.sleep(0.02)
        except KeyboardInterrupt:
            print("\nStopped.")

if __name__ == '__main__':
    main()

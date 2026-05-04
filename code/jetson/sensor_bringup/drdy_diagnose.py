"""
Diagnose why DRDY isn't pulsing INT1 in B5.

Reads back the registers host_pipeline.c sets, plus STATUS_REG to see
if new accelerometer samples are actually being generated.
"""
import time
from smbus2 import SMBus

I2C_BUS = 7
ADDR = 0x6A

REG_WHO_AM_I  = 0x0F
REG_CTRL1_XL  = 0x10
REG_CTRL3_C   = 0x12
REG_INT1_CTRL = 0x0D
REG_STATUS    = 0x1E
REG_OUTZ_H_A  = 0x2D
REG_TAP_SRC   = 0x1C
REG_MD1_CFG   = 0x5E

with SMBus(I2C_BUS) as bus:
    print("=== Pre-reset state (whatever was left from host_pipeline.c) ===")
    print(f"WHO_AM_I    (0x0F) = 0x{bus.read_byte_data(ADDR, REG_WHO_AM_I):02X} (expect 0x6C)")
    print(f"CTRL1_XL    (0x10) = 0x{bus.read_byte_data(ADDR, REG_CTRL1_XL):02X} (expect 0x60)")
    print(f"CTRL3_C     (0x12) = 0x{bus.read_byte_data(ADDR, REG_CTRL3_C):02X} (expect 0x44)")
    print(f"INT1_CTRL   (0x0D) = 0x{bus.read_byte_data(ADDR, REG_INT1_CTRL):02X} (expect 0x01)")
    print(f"MD1_CFG     (0x5E) = 0x{bus.read_byte_data(ADDR, REG_MD1_CFG):02X} (expect 0x00 = no other INT1 sources)")
    print()

    print("=== Are new samples being produced? ===")
    print("Reading STATUS_REG every 5 ms for 50 ms.")
    print("XLDA bit (bit 0) = 1 means a new accel sample is ready.")
    for i in range(10):
        s = bus.read_byte_data(ADDR, REG_STATUS)
        xlda = s & 0x01
        gda  = (s >> 1) & 0x01
        print(f"  t={i*5:3d}ms  STATUS=0x{s:02X}  XLDA={xlda}  GDA={gda}")
        time.sleep(0.005)
    print()

    print("=== Reconfigure and retry: write the same config host_pipeline does ===")
    bus.write_byte_data(ADDR, REG_CTRL3_C, 0x01)  # SW_RESET
    time.sleep(0.05)
    print(f"After reset: WHO_AM_I = 0x{bus.read_byte_data(ADDR, REG_WHO_AM_I):02X}")
    bus.write_byte_data(ADDR, REG_CTRL3_C,   0x44)
    bus.write_byte_data(ADDR, REG_CTRL1_XL,  0x60)
    bus.write_byte_data(ADDR, REG_INT1_CTRL, 0x01)
    time.sleep(0.05)

    print()
    print("=== After clean config: check registers and STATUS ===")
    print(f"CTRL1_XL    = 0x{bus.read_byte_data(ADDR, REG_CTRL1_XL):02X}")
    print(f"CTRL3_C     = 0x{bus.read_byte_data(ADDR, REG_CTRL3_C):02X}")
    print(f"INT1_CTRL   = 0x{bus.read_byte_data(ADDR, REG_INT1_CTRL):02X}")
    print()
    print("Reading STATUS for 100 ms (should see XLDA cycle 0 -> 1 -> 0 as samples arrive):")
    for i in range(20):
        s = bus.read_byte_data(ADDR, REG_STATUS)
        xlda = s & 0x01
        # Reading OUTZ_H_A clears DRDY in latched mode
        if xlda:
            _ = bus.read_byte_data(ADDR, REG_OUTZ_H_A)
            note = " (read OUTZ_H_A to clear)"
        else:
            note = ""
        print(f"  t={i*5:3d}ms  XLDA={xlda}{note}")
        time.sleep(0.005)

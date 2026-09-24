# SDA/SCL capture plan — 2026-09-24 (committed before first capture)

## Purpose
Direct on-wire evidence for the three-transaction MLC read protocol
(write FUNC_CFG_ACCESS=0x80, read MLC0_SRC=0x70, write FUNC_CFG_ACCESS=0x00)
and decomposition of MLC decision latency into bus time vs. scheduling/gaps.

## Hardware
- Saleae Logic Pro 8, Logic 2, 25 MS/s digital, 3.3 V threshold, glitch filter off
- Ch0=D0 (INT1, header pin 15), Ch1=D1 (decision GPIO, pin 11), Ch2=D2 (servo PWM),
  Ch3=SDA (pin 3), Ch4=SCL (pin 5), GND pin 6
- LSM6DSOX (Adafruit PID 4438) on I2C bus 7, address 0x6A, 400 kHz

## Planned captures
1. Sanity: 10 s, pipeline running, verify decode + transaction triple inside D0->D1 windows
2. Block A: idle, 300 s, latency_test_mlc_w75 alone
3. Block B: i2c-contention, 300 s, pipeline + 3x i2c_hammer on bus 7
4. Block C: stress, 300 s, pipeline + stress-ng --cpu 6 --cpu-method matrixprod
5. Control: short mlc-binary block (negative control)

## Analysis (pre-committed)
- Decode I2C; classify transactions by register:
  0x01 write / 0x70 read = pipeline; all other registers = hammer traffic (NOT deviations)
- Per D0->D1 window: verify exactly one 0x80-write / 0x70-read / 0x00-write triple
- Decompose D0->D1 latency: bus transaction time vs. inter-transaction gaps vs. GPIO path
- Measure SCL/SDA rise times (spot check)
- No on-wire arbitration expected (single master; Linux i2c adapter lock serializes)

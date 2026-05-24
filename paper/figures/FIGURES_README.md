# Apparatus Figures for IEEE Sensors Letters Paper

## Files Included

### 1. apparatus_ai_generated_v2_final.png
**DOWNLOAD THIS IMAGE AND PLACE IN THIS ZIP**

This is the corrected AI-generated diagram showing:
- Jetson Orin Nano (MAXN mode, JetPack 6.2.2)
- Servo rig with ±90° sweep @ 0.5 Hz (scale: 11 cm height, 12.5 cm base)
- LSM6DSOX IMU mounted on servo arm
- PCA9685 servo controller (blue PCB, I2C addr 0x41, A0 bridged)
- Saleae Logic Pro 8 (D0=INT1, D2=ground-truth solenoid)
- Correct pin assignments and signal paths
- GPIO line 112 marked as reserved (NOT used)

**Status**: Publication-ready for paper Methods section

### 2. apparatus_schematic.svg
Vector schematic diagram with:
- Complete wiring annotations
- Color-coded signal paths
- I2C Bus 7 (blue), INT1 (red), PWM (orange), capture (green dashed)
- Legend and notes
- Scale reference

**Status**: Complete, ready for supplementary materials or appendix

### 3. ai_prompt_apparatus_v2_corrected.txt
Detailed AI image generation prompt with:
- Corrected specifications (INA3221 removed, Saleae D0/D2 only)
- Amazon product links
- Wiring signal path descriptions
- Style guidelines

**Usage**: Feed to Claude (claude.ai), Midjourney, or DALL-E to generate 
alternative versions of the apparatus diagram

### 4. README.md
This file with setup instructions

## How to Use (Terminal Commands)

1. **Download the ZIP file** to ~/Downloads/

2. **Extract and copy to repo:**
   ```bash
   cd ~/sensor-mlc-latency
   unzip ~/Downloads/apparatus_figures.zip -d /tmp/apparatus_temp
   cp /tmp/apparatus_temp/apparatus_schematic.svg paper/figures/
   cp /tmp/apparatus_temp/ai_prompt_apparatus_v2_corrected.txt paper/figures/
   cp /tmp/apparatus_temp/README.md paper/figures/FIGURES_README.md
   ```

3. **MANUAL STEP**: Download apparatus_ai_generated_v2_final.png from the chat 
   and save to ~/Downloads/, then:
   ```bash
   cp ~/Downloads/apparatus_ai_generated_v2_final.png \
       ~/sensor-mlc-latency/paper/figures/apparatus_ai_generated_v2_final.png
   ```

4. **Commit to Git:**
   ```bash
   cd ~/sensor-mlc-latency
   git add paper/figures/apparatus_schematic.svg \
           paper/figures/ai_prompt_apparatus_v2_corrected.txt \
           paper/figures/apparatus_ai_generated_v2_final.png \
           paper/figures/FIGURES_README.md
   git commit -m "Add apparatus figures: SVG schematic + AI-generated diagram + prompt

   Three publication-ready apparatus diagrams:
   - apparatus_schematic.svg: vector schematic with complete wiring
   - apparatus_ai_generated_v2_final.png: corrected AI diagram (ChatGPT revision 1)
   - ai_prompt_apparatus_v2_corrected.txt: AI generation prompt with product links
   
   Both diagrams show: Jetson Orin Nano, servo rig (±90° @ 0.5 Hz), LSM6DSOX IMU,
   PCA9685 servo controller (I2C 0x41), Saleae Logic Pro 8 (D0=INT1, D2=ground-truth).
   All signal paths color-coded: I2C blue, INT1 red, PWM orange, capture green dashed."
   git push origin main
   ```

## Paper Usage

**Figure 1 (Methods section, §4–§5):**
Include `apparatus_ai_generated_v2_final.png`

**Caption:**
"Figure 1: Apparatus for Motion-vs-Still Classification on Servo Rig. 
The LSM6DSOX IMU is mounted at the tip of a servo-driven arm oscillating ±90° 
at 0.5 Hz (still state: 0°, motion state: ±90°). A Jetson Orin Nano (MAXN mode) 
runs both on-sensor MLC inference and on-host sliding-window classification. 
The PCA9685 servo controller (I2C addr 0x41) drives the SG90 servo motor. 
A Saleae Logic Pro 8 analyzer captures digital timing edges: D0 (INT1 interrupt 
from sensor, red line 85) marks the start of each inference window; D2 records 
the ground-truth solenoid trigger timing. Wire-level latency is measured as the 
time difference between INT1 rising edge (start of inference) and the inference 
decision edge on GPIO line 112 (Jetson). All GPIO and I2C power from 3.3V Jetson 
rail; separate 5V supply powers the PCA9685 PWM output stage."

**Optional (Supplementary/Appendix):**
Include `apparatus_schematic.svg` for detailed technical reference

## Component Links

- **PCA9685**: https://www.amazon.com/dp/B0DG8QCP58
- **LSM6DSOX**: https://www.amazon.com/dp/B0CRV3MK14
- **Breadboards**: https://www.amazon.com/dp/B0BZJTQ5YP
- **Saleae Logic 8**: https://www.saleae.com/products/logic-8


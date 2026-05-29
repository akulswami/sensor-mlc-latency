#!/usr/bin/env python3
"""
Automated Saleae capture + servo sweep for latency testing.
Runs on Jetson Orin Nano.
- Connects to PCA9685 servo controller
- Starts Saleae capture
- Moves servo ±90° for 30 seconds
- Stops capture and exports to CSV
"""

import time
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Configuration
CAPTURE_DURATION = 30  # seconds
OUTPUT_DIR = Path("data/test_saleae_servo")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def control_servo(duration_sec=30):
    """Control PCA9685 servo: oscillate ±90° at 0.5 Hz."""
    print(f"[Servo] Starting ±90° sweep for {duration_sec} seconds...")
    
    try:
        from board import SCL, SDA
        import busio
        from adafruit_pca9685 import PCA9685
        
        # I2C bus 7, address 0x41 (A0 pad bridged)
        i2c = busio.I2C(SCL, SDA)
        pca = PCA9685(i2c, address=0x41)
        pca.frequency = 50  # 50 Hz for servos
        
        # SG90 servo pulse widths (in microseconds):
        # -90° (left):    1.0 ms = 100 at 50Hz → ~307 on 12-bit
        # 0° (center):    1.5 ms = 150 at 50Hz → ~460 on 12-bit
        # +90° (right):   2.0 ms = 200 at 50Hz → ~614 on 12-bit
        
        LEFT = 307
        CENTER = 460
        RIGHT = 614
        
        start_time = time.time()
        elapsed = 0
        
        while elapsed < duration_sec:
            # Sweep: center → left → center → right → center
            for position in [CENTER, LEFT, CENTER, RIGHT, CENTER]:
                pca.channels[0].duty_cycle = position
                
                # Each position held for 2 seconds (0.5 Hz = 1 sec per half-cycle)
                time.sleep(2)
                elapsed = time.time() - start_time
                
                print(f"  [+{elapsed:.1f}s] Servo at {['CENTER','LEFT','CENTER','RIGHT','CENTER'][[CENTER,LEFT,CENTER,RIGHT,CENTER].index(position)]}")
                
                if elapsed >= duration_sec:
                    break
        
        # Return to center
        pca.channels[0].duty_cycle = CENTER
        print("[Servo] ✓ Sweep complete, servo centered")
        return True
        
    except Exception as e:
        print(f"[Servo] ✗ Error: {e}")
        return False

def start_saleae_capture():
    """Start Saleae Logic 2 capture via libsaleae (if available) or fallback."""
    print("[Saleae] Starting 30-second capture (D0, D2, D3 @ 50 MS/s)...")
    
    # Try using libsaleae Python bindings
    try:
        from saleae import Saleae
        
        # Connect to Saleae (assumes Logic 2 running on localhost:10430)
        s = Saleae()
        
        # Configure capture
        s.set_num_samples(30 * 50_000_000)  # 30 sec × 50 MS/s
        s.set_sample_rate(50_000_000)
        s.set_active_channels([0, 2, 3])  # D0, D2, D3
        
        # Start capture (blocking)
        s.capture_to_file(str(OUTPUT_DIR / "saleae_test.sal"))
        print(f"[Saleae] ✓ Capture complete: {OUTPUT_DIR / 'saleae_test.sal'}")
        return True
        
    except ImportError:
        print("[Saleae] ✗ libsaleae not installed. Install: pip install saleae")
        return False
    except Exception as e:
        print(f"[Saleae] ✗ Error: {e}")
        return False

def export_to_csv():
    """Convert .sal to CSV."""
    sal_file = OUTPUT_DIR / "saleae_test.sal"
    csv_file = OUTPUT_DIR / "saleae_test.csv"
    
    print(f"[Export] Converting {sal_file} to CSV...")
    
    try:
        from saleae import Saleae
        s = Saleae()
        s.export_data_csv(str(sal_file), str(csv_file))
        print(f"[Export] ✓ CSV saved: {csv_file}")
        return True
    except Exception as e:
        print(f"[Export] ✗ Error: {e}")
        return False

def verify_capture():
    """Verify all 3 channels in CSV."""
    csv_file = OUTPUT_DIR / "saleae_test.csv"
    
    if not csv_file.exists():
        print(f"[Verify] ✗ CSV not found: {csv_file}")
        return False
    
    print("[Verify] Checking capture data...")
    
    try:
        import csv
        
        with open(csv_file) as f:
            reader = csv.reader(f)
            header = next(reader)
            
            d0_edges = 0
            d2_edges = 0
            d3_edges = 0
            
            prev_d0, prev_d2, prev_d3 = 0, 0, 0
            
            for row in reader:
                if len(row) < 4:
                    continue
                try:
                    d0 = int(row[1])
                    d2 = int(row[2])
                    d3 = int(row[3])
                except:
                    continue
                
                if d0 != prev_d0:
                    d0_edges += 1
                if d2 != prev_d2:
                    d2_edges += 1
                if d3 != prev_d3:
                    d3_edges += 1
                
                prev_d0, prev_d2, prev_d3 = d0, d2, d3
        
        print(f"[Verify] D0 (INT1) edges: {d0_edges}")
        print(f"[Verify] D2 (PWM) edges: {d2_edges}")
        print(f"[Verify] D3 (Decision) edges: {d3_edges}")
        
        if d0_edges > 100 and d2_edges > 10 and d3_edges > 10:
            print("[Verify] ✓ All channels have sufficient signal!")
            return True
        else:
            print("[Verify] ✗ Insufficient edges detected")
            if d3_edges < 10:
                print("  → D3 (Decision GPIO) not toggling properly")
            return False
    
    except Exception as e:
        print(f"[Verify] ✗ Error: {e}")
        return False

def main():
    print("=" * 60)
    print("Automated Saleae Capture + Servo Sweep Test")
    print("=" * 60)
    print()
    
    # Step 1: Start Saleae capture (non-blocking with threading)
    import threading
    
    print("[Test] Starting Saleae capture in background...")
    saleae_thread = threading.Thread(target=start_saleae_capture, daemon=False)
    saleae_thread.start()
    
    # Give Saleae time to initialize
    time.sleep(2)
    
    # Step 2: Control servo (blocking, 30 seconds)
    print("[Test] Starting servo sweep...")
    servo_ok = control_servo(duration_sec=30)
    
    # Wait for Saleae to finish
    print("[Test] Waiting for Saleae capture to finish...")
    saleae_thread.join(timeout=40)
    
    # Step 3: Export and verify
    if export_to_csv():
        verify_capture()
    
    print()
    print("=" * 60)
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Files: saleae_test.sal, saleae_test.csv")
    print("=" * 60)

if __name__ == "__main__":
    main()

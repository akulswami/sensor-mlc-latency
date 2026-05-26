#!/usr/bin/env bash
# install_maxn_super_jc.sh
# Installs a custom nvpmodel mode "MAXN_SUPER_JC" (ID=3) that pins
# CPU MIN_FREQ to 1728000 (matching MAX_FREQ), defeating nvpmodel's
# normal reassertion of MIN_FREQ to 729600 and making jetson_clocks
# state deterministic.
#
# Why this is needed:
#
# The default Jetson Orin Nano power mode ("25W", ID=1) defines CPU
# MIN_FREQ = 729600. Even after `jetson_clocks` sets scaling_min_freq
# == scaling_max_freq == 1728000, nvpmodel periodically reasserts the
# mode-configured MIN_FREQ, returning CPUs to free-running DVFS. This
# was observed empirically in the 2026-05-25 long-duration smoke run
# (block-701-host-idle, jc_eff = 17.3%). For measurement runs where
# CPU-frequency variability would confound the energy axis, a custom
# mode is required.
#
# Usage:
#   sudo ./install_maxn_super_jc.sh
#
# After install, activate with:
#   sudo nvpmodel -m 3
#
# Verify with:
#   nvpmodel -q                 # should report "MAXN_SUPER_JC, 3"
#   cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq
#                               # should print 1728000
#
# To revert to the default 25W mode:
#   sudo nvpmodel -m 1
#
# Background and reference:
# - /etc/nvpmodel.conf is a symlink to /etc/nvpmodel/nvpmodel_p3767_0003_super.conf
# - Default boot mode is 25W (mode 1), unchanged by this script
# - This script adds mode 3 (MAXN_SUPER_JC) but does NOT change the boot default
# - PM_CONFIG DEFAULT=1 preserved in the modified config
#
# Idempotency:
# - If mode 3 already exists, the script exits without modification
# - The script preserves the existing backup file if one is present

set -euo pipefail

CONFIG="/etc/nvpmodel/nvpmodel_p3767_0003_super.conf"
BACKUP="${CONFIG}.backup-pre-jc-mode-$(date +%Y-%m-%d)"
SNIPPET_PATH="$(dirname "$0")/MAXN_SUPER_JC.snippet"

# 1. Sanity checks
if [[ "$EUID" -ne 0 ]]; then
    echo "ERROR: must run as root (sudo)"
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: config file not found: $CONFIG"
    echo "(This script is specific to Jetson Orin Nano running JetPack 6.x"
    echo " with the p3767_0003_super.conf symlinked at /etc/nvpmodel.conf.)"
    exit 1
fi

if [[ ! -f "$SNIPPET_PATH" ]]; then
    echo "ERROR: snippet not found: $SNIPPET_PATH"
    exit 1
fi

# 2. Idempotency check
if grep -q "POWER_MODEL ID=3 NAME=MAXN_SUPER_JC" "$CONFIG"; then
    echo "MAXN_SUPER_JC mode already installed in $CONFIG"
    echo "(remove it manually if you want to reinstall from snippet)"
    nvpmodel -p --verbose 2>&1 | grep -E "POWER_MODEL: ID=" || true
    exit 0
fi

# 3. Backup
if [[ ! -f "$BACKUP" ]]; then
    cp "$CONFIG" "$BACKUP"
    echo "Created backup: $BACKUP"
else
    echo "Backup already exists, not overwriting: $BACKUP"
fi

# 4. Insert the new mode before the PM_CONFIG line
python3 <<INSERT_PY
config_path = "$CONFIG"
snippet_path = "$SNIPPET_PATH"

with open(config_path) as f:
    content = f.read()

with open(snippet_path) as f:
    snippet = f.read()

marker = "# mandatory section to configure the default power mode"
if marker not in content:
    raise SystemExit("ERROR: PM_CONFIG marker not found in config")

if "POWER_MODEL ID=3 NAME=MAXN_SUPER_JC" in content:
    print("Already installed; not modifying.")
    raise SystemExit(0)

new_content = content.replace(marker, snippet + "\n" + marker)

with open(config_path, "w") as f:
    f.write(new_content)

print(f"Inserted MAXN_SUPER_JC mode into {config_path}")
INSERT_PY

# 5. Verify nvpmodel can parse the new file
echo ""
echo "Verifying nvpmodel can parse the modified config..."
if ! nvpmodel -p --verbose 2>&1 | grep -q "POWER_MODEL: ID=3 NAME=MAXN_SUPER_JC"; then
    echo "ERROR: nvpmodel did not parse MAXN_SUPER_JC after install"
    echo "Restoring backup..."
    cp "$BACKUP" "$CONFIG"
    exit 1
fi

echo ""
echo "Available modes after install:"
nvpmodel -p --verbose 2>&1 | grep "POWER_MODEL: ID="

echo ""
echo "DONE. To activate the new mode, run:"
echo "  sudo nvpmodel -m 3"
echo ""
echo "Then verify with:"
echo "  nvpmodel -q   # should report MAXN_SUPER_JC, ID 3"
echo "  cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq  # should print 1728000"

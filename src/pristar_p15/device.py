"""BlueZ device discovery helpers (no MAC addresses are hard-coded)."""

import os
import re
import subprocess

PREFIXES = ("P15", "P12", "P7", "LP15", "LP90", "M1", "S15", "S12", "P1s",
            "LPC74", "iSPACE_LP15", "OUT_LPC")


def known_devices():
    """Return [(mac, name)] from bluetoothctl and BlueZ's on-disk cache."""
    devices = []
    try:
        r = subprocess.run(["bluetoothctl", "devices"], capture_output=True,
                           text=True, check=False, timeout=10)
        for line in r.stdout.splitlines():
            m = re.match(r"Device\s+([0-9A-Fa-f:]{17})\s+(.+)$", line.strip())
            if m:
                devices.append((m.group(1).upper(), m.group(2).strip()))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    base = "/var/lib/bluetooth"
    if os.path.isdir(base):
        for root, _dirs, files in os.walk(base):
            if "info" not in files:
                continue
            mac = os.path.basename(root)
            if not re.fullmatch(r"[0-9A-Fa-f:]{17}", mac):
                continue
            name = ""
            try:
                with open(os.path.join(root, "info"), encoding="utf-8",
                          errors="replace") as f:
                    for line in f:
                        if line.startswith("Name="):
                            name = line.split("=", 1)[1].strip()
                            break
            except OSError:
                continue
            if name:
                devices.append((mac.upper(), name))

    seen = set()
    unique = []
    for mac, name in devices:
        if mac not in seen:
            seen.add(mac)
            unique.append((mac, name))
    return unique


def find_p15(preferred=None):
    """Return (mac, name) for the requested MAC or the first P15-family device."""
    devices = known_devices()
    if preferred:
        preferred = preferred.upper()
        for mac, name in devices:
            if mac == preferred:
                return mac, name
        return preferred, ""
    for mac, name in devices:
        if any(name.startswith(prefix) for prefix in PREFIXES):
            return mac, name
    return None, None

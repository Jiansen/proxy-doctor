"""launchd daemon management for proxy-doctor.

Provides plist generation, install/uninstall, and status checking.
Zero external dependencies — uses only Python stdlib.
"""

from __future__ import annotations

import os
import plistlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

PLIST_LABEL = "io.proxy-doctor.daemon"
_PROXY_DOCTOR_DIR = os.path.expanduser("~/.proxy-doctor")


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def build_plist(interval: int = 300) -> dict[str, Any]:
    """Build a launchd plist dict for the proxy-doctor daemon.

    The daemon runs `python -m proxy_doctor.daemon_loop` at *interval* seconds.
    """
    log_dir = _PROXY_DOCTOR_DIR
    return {
        "Label": PLIST_LABEL,
        "ProgramArguments": [
            sys.executable,
            "-m",
            "proxy_doctor.daemon_loop",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StartInterval": interval,
        "StandardOutPath": os.path.join(log_dir, "daemon.log"),
        "StandardErrorPath": os.path.join(log_dir, "daemon_err.log"),
    }


def _run_launchctl_list() -> str:
    try:
        r = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def daemon_status() -> dict[str, Any]:
    """Check if the daemon is loaded in launchd."""
    output = _run_launchctl_list()
    running = PLIST_LABEL in output
    return {
        "state": "running" if running else "not_running",
        "plist_path": str(plist_path()),
        "label": PLIST_LABEL,
    }


def install_daemon(interval: int = 300) -> tuple[bool, str]:
    """Write plist and load into launchd."""
    if platform.system() != "Darwin":
        return False, "Daemon mode is only supported on macOS"

    os.makedirs(_PROXY_DOCTOR_DIR, exist_ok=True)

    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    plist = build_plist(interval=interval)
    p.write_bytes(plistlib.dumps(plist))

    try:
        r = subprocess.run(
            ["launchctl", "load", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            return True, f"Daemon installed and loaded ({p})"
        return False, f"launchctl load failed: {r.stderr.strip()}"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, str(exc)


def uninstall_daemon() -> tuple[bool, str]:
    """Unload from launchd and remove plist."""
    p = plist_path()

    if p.exists():
        try:
            subprocess.run(
                ["launchctl", "unload", str(p)],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
        p.unlink(missing_ok=True)

    return True, "Daemon uninstalled"

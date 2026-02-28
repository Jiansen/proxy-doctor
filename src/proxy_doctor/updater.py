"""Auto-Update with rollback — check PyPI for new versions and upgrade safely.

Zero external dependencies — uses only Python stdlib.
Version comparison uses tuple splitting instead of packaging.version.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from urllib.error import URLError

log = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = os.path.expanduser("~/.proxy-doctor")
_STATE_FILE = "update_state.json"
_PYPI_URL = "https://pypi.org/pypi/proxy-doctor/json"
_GITHUB_RELEASES = "https://github.com/Jiansen/proxy-doctor/releases"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Version comparison (no packaging dependency)
# ---------------------------------------------------------------------------

def _parse_version_tuple(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in v.strip().split("."))
    except (ValueError, AttributeError):
        return None


def compare_versions(available: str, current: str) -> bool:
    """Return True if *available* is strictly newer than *current*."""
    a = _parse_version_tuple(available)
    c = _parse_version_tuple(current)
    if a is None or c is None:
        return False
    return a > c


# ---------------------------------------------------------------------------
# PyPI version check
# ---------------------------------------------------------------------------

def _fetch_pypi_version(timeout: int = 10) -> str | None:
    try:
        with urlopen(_PYPI_URL, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("info", {}).get("version")
    except (URLError, json.JSONDecodeError, OSError, KeyError) as exc:
        log.warning("PyPI version check failed: %s", exc)
        return None


@dataclass
class UpdateCheckResult:
    available: bool
    current_version: str
    latest_version: str | None = None
    release_url: str = _GITHUB_RELEASES
    error: str = ""


def check_for_update(current_version: str) -> UpdateCheckResult:
    """Check PyPI for a newer version."""
    latest = _fetch_pypi_version()
    if latest is None:
        return UpdateCheckResult(
            available=False,
            current_version=current_version,
            error="Version check failed — could not reach PyPI",
        )
    is_newer = compare_versions(latest, current_version)
    return UpdateCheckResult(
        available=is_newer,
        current_version=current_version,
        latest_version=latest,
        release_url=f"{_GITHUB_RELEASES}/tag/v{latest}" if is_newer else _GITHUB_RELEASES,
    )


# ---------------------------------------------------------------------------
# Update state persistence
# ---------------------------------------------------------------------------

class UpdateState:
    """Track pre/post update state for rollback."""

    def __init__(self, state_dir: str | None = None) -> None:
        self._dir = Path(state_dir or _DEFAULT_STATE_DIR)

    def _path(self) -> Path:
        return self._dir / _STATE_FILE

    def load(self) -> dict[str, Any]:
        path = self._path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def save_pre_update(self, current_version: str) -> None:
        data = self.load()
        data["previous_version"] = current_version
        data["timestamp"] = _utcnow()
        self._save(data)

    def save_result(
        self,
        success: bool,
        new_version: str,
        error: str = "",
    ) -> None:
        data = self.load()
        data["last_update_success"] = success
        data["updated_to"] = new_version
        data["result_timestamp"] = _utcnow()
        if error:
            data["error"] = error
        elif "error" in data:
            del data["error"]
        self._save(data)


# ---------------------------------------------------------------------------
# Pip operations
# ---------------------------------------------------------------------------

def _run_pip_install(package_spec: str) -> tuple[bool, str]:
    """Run pip install and return (success, stderr)."""
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", package_spec]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            return True, ""
        return False, r.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return False, str(exc)


def _verify_installation() -> bool:
    """Verify proxy-doctor still works after update."""
    cmd = [sys.executable, "-m", "proxy_doctor", "check", "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode in (0, 1)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


# ---------------------------------------------------------------------------
# Perform update with rollback
# ---------------------------------------------------------------------------

@dataclass
class UpdateResult:
    success: bool
    new_version: str
    previous_version: str
    rolled_back: bool = False
    error: str = ""
    release_url: str = ""


def perform_update(
    current_version: str,
    target_version: str,
    state_dir: str | None = None,
) -> UpdateResult:
    """Upgrade proxy-doctor to *target_version* with automatic rollback on failure."""
    state = UpdateState(state_dir=state_dir)
    state.save_pre_update(current_version)

    ok, err = _run_pip_install(f"proxy-doctor=={target_version}")
    if not ok:
        state.save_result(success=False, new_version=target_version,
                          error=f"pip install failed: {err}")
        return UpdateResult(
            success=False,
            new_version=target_version,
            previous_version=current_version,
            error=f"pip install failed: {err}",
        )

    if not _verify_installation():
        log.warning("Post-update verification failed, rolling back to %s", current_version)
        _run_pip_install(f"proxy-doctor=={current_version}")
        state.save_result(success=False, new_version=target_version,
                          error="Post-update verification failed; rolled back")
        return UpdateResult(
            success=False,
            new_version=target_version,
            previous_version=current_version,
            rolled_back=True,
            error="Post-update verification failed; rolled back",
        )

    state.save_result(success=True, new_version=target_version)
    release_url = f"{_GITHUB_RELEASES}/tag/v{target_version}"
    return UpdateResult(
        success=True,
        new_version=target_version,
        previous_version=current_version,
        release_url=release_url,
    )

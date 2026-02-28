"""State Diff Engine — track diagnosis changes between runs.

Zero external dependencies — uses only Python stdlib.
Caches the last report to ~/.proxy-doctor/last_report.json and
compares consecutive runs to detect meaningful state transitions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_DEFAULT_CACHE_DIR = os.path.expanduser("~/.proxy-doctor")
_REPORT_FILE = "last_report.json"


@dataclass
class StateChange:
    """Result of comparing two diagnosis reports."""

    from_status: str | None
    to_status: str
    changed_fields: list[str] = field(default_factory=list)
    summary: str = ""
    is_initial: bool = False

    @property
    def changed(self) -> bool:
        return len(self.changed_fields) > 0


def compare_reports(
    old: dict[str, Any] | None,
    new: dict[str, Any],
) -> StateChange:
    """Compare two report dicts and return what changed.

    *old* may be None on first run.
    """
    if old is None:
        return StateChange(
            from_status=None,
            to_status=new.get("status", "unknown"),
            summary=f"Initial diagnosis: {new.get('status', 'unknown')}",
            is_initial=True,
        )

    changed: list[str] = []

    old_status = old.get("status", "unknown")
    new_status = new.get("status", "unknown")
    if old_status != new_status:
        changed.append("status")

    old_case = old.get("diagnosis", {}).get("case", "")
    new_case = new.get("diagnosis", {}).get("case", "")
    if old_case != new_case:
        changed.append("case")

    old_ev = old.get("evidence", {})
    new_ev = new.get("evidence", {})

    old_ports = _port_fingerprint(old_ev.get("port_statuses", []))
    new_ports = _port_fingerprint(new_ev.get("port_statuses", []))
    if old_ports != new_ports:
        changed.append("port_statuses")

    old_sys = _proxy_fingerprint(old_ev.get("system_proxies", []))
    new_sys = _proxy_fingerprint(new_ev.get("system_proxies", []))
    if old_sys != new_sys:
        changed.append("system_proxies")

    old_env = _proxy_fingerprint(old_ev.get("env_proxies", []))
    new_env = _proxy_fingerprint(new_ev.get("env_proxies", []))
    if old_env != new_env:
        changed.append("env_proxies")

    summary = _build_summary(old_status, new_status, changed)

    return StateChange(
        from_status=old_status,
        to_status=new_status,
        changed_fields=changed,
        summary=summary,
    )


def _port_fingerprint(ports: list[dict]) -> set[tuple[str, int, str]]:
    return {(p.get("host", ""), p.get("port", 0), p.get("status", "")) for p in ports}


def _proxy_fingerprint(proxies: list[dict]) -> set[tuple[str, int, bool]]:
    return {
        (p.get("host", ""), p.get("port", 0), p.get("enabled", False))
        for p in proxies
    }


def _build_summary(old_status: str, new_status: str, changed: list[str]) -> str:
    if not changed:
        return "No changes detected."
    if "status" in changed:
        return f"Status changed: {old_status} -> {new_status}"
    parts = ", ".join(changed)
    return f"Changes detected in: {parts}"


class StateCache:
    """Persist and compare diagnosis reports on disk."""

    def __init__(self, cache_dir: str | None = None) -> None:
        self._dir = Path(cache_dir or _DEFAULT_CACHE_DIR)

    def _report_path(self) -> Path:
        return self._dir / _REPORT_FILE

    def load(self) -> dict[str, Any] | None:
        path = self._report_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def save(self, report: dict[str, Any]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._report_path()
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def compare_and_save(self, new_report: dict[str, Any]) -> StateChange:
        """Load previous, compare, save new, return diff."""
        old = self.load()
        change = compare_reports(old, new_report)
        self.save(new_report)
        return change

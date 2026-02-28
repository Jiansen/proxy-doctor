"""proxy-doctor macOS menu bar application.

Displays proxy health status in the menu bar with periodic refresh.
Integrates state diffing, notifications, and update checks.
Uses the same core diagnostic engine as the CLI and MCP server.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import os
import time

import rumps

REFRESH_SECONDS = 300  # 5 minutes
UPDATE_CHECK_SECONDS = 86400  # 24 hours

STATUS_ICONS = {
    "healthy": "✓",
    "unhealthy": "✗",
    "warning": "!",
    "error": "?",
}


def _ensure_path():
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def _run_diagnosis() -> dict:
    """Run proxy diagnosis using the core library or CLI fallback."""
    _ensure_path()
    try:
        from proxy_doctor.core import run_diagnosis
        report = run_diagnosis()
        return report.to_dict()
    except ImportError:
        pass

    try:
        r = subprocess.run(
            [sys.executable, "-m", "proxy_doctor.cli", "check", "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode in (0, 1) and r.stdout.strip():
            return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return {"status": "error", "diagnosis": {"root_cause": "Could not run diagnosis"}}


class ProxyDoctorApp(rumps.App):
    def __init__(self):
        super().__init__(
            "proxy-doctor",
            title=STATUS_ICONS["error"],
            quit_button=rumps.MenuItem("Quit proxy-doctor"),
        )
        self._last_report: dict = {}
        self._last_check_time: float = 0
        self._last_update_check: float = 0
        self._notifications_enabled = True

        self._status_item = rumps.MenuItem("Loading...")
        self._cause_item = rumps.MenuItem("")
        self._cause_item.set_callback(None)
        self._last_checked_item = rumps.MenuItem("Last checked: —")
        self._last_checked_item.set_callback(None)

        self._notify_toggle = rumps.MenuItem(
            "Notifications: ON",
            callback=self._on_toggle_notify,
        )

        self.menu = [
            self._status_item,
            self._cause_item,
            self._last_checked_item,
            None,
            rumps.MenuItem("Run Full Diagnosis", callback=self._on_diagnose),
            rumps.MenuItem("Copy JSON Report", callback=self._on_copy_json),
            rumps.MenuItem("Check for Updates", callback=self._on_check_update),
            None,
            self._notify_toggle,
            rumps.MenuItem("Report Issue", callback=self._on_report_issue),
            rumps.MenuItem("GitHub", callback=self._on_github),
        ]

        _ensure_path()
        try:
            from proxy_doctor.state import StateCache
            from proxy_doctor.updater import check_for_update
            self._state_cache = StateCache()
        except ImportError:
            self._state_cache = None

        self._timer = rumps.Timer(self._on_refresh, REFRESH_SECONDS)
        self._timer.start()
        self._do_refresh()

    def _do_refresh(self):
        """Run diagnosis in background thread to avoid blocking the UI."""
        def _worker():
            report = _run_diagnosis()
            self._last_report = report
            self._last_check_time = time.time()
            self._update_display(report)
            self._check_state_change(report)
            self._maybe_check_update()
        threading.Thread(target=_worker, daemon=True).start()

    def _check_state_change(self, report: dict):
        if self._state_cache is None:
            return
        try:
            change = self._state_cache.compare_and_save(report)
            if change.changed and "status" in change.changed_fields and self._notifications_enabled:
                rumps.notification(
                    title="Proxy Doctor",
                    subtitle="Status Change",
                    message=f"{change.from_status} → {change.to_status}",
                )
        except Exception:
            pass

    def _maybe_check_update(self):
        now = time.monotonic()
        if now - self._last_update_check < UPDATE_CHECK_SECONDS:
            return
        self._last_update_check = now
        try:
            from proxy_doctor.updater import check_for_update
            from proxy_doctor import __version__
            result = check_for_update(__version__)
            if result.available and self._notifications_enabled:
                rumps.notification(
                    title="Proxy Doctor",
                    subtitle="Update Available",
                    message=f"Version {result.latest_version} is available",
                )
        except Exception:
            pass

    def _update_display(self, report: dict):
        status = report.get("status", "error")
        self.title = STATUS_ICONS.get(status, "?")

        diag = report.get("diagnosis", {})
        root_cause = diag.get("root_cause", "Unknown")

        self._status_item.title = f"Status: {status.upper()}"
        if status == "healthy":
            self._cause_item.title = "No proxy issues detected"
        else:
            short = root_cause[:80] + ("..." if len(root_cause) > 80 else "")
            self._cause_item.title = short

        if self._last_check_time:
            t = time.strftime("%H:%M", time.localtime(self._last_check_time))
            self._last_checked_item.title = f"Last checked: {t}"

    def _on_refresh(self, _sender):
        self._do_refresh()

    def _on_diagnose(self, _sender):
        self._do_refresh()
        report = self._last_report
        status = report.get("status", "error")
        diag = report.get("diagnosis", {})

        lines = [
            f"Status: {status.upper()}",
            f"Root Cause: {diag.get('root_cause', 'Unknown')}",
        ]
        if diag.get("confidence"):
            lines.append(f"Confidence: {diag['confidence']}")
        if diag.get("browser_explanation"):
            lines.append(f"\nWhy browser works: {diag['browser_explanation']}")

        fixes = report.get("fixes", [])
        if fixes:
            lines.append("\nRecommended fixes:")
            for i, f in enumerate(fixes, 1):
                lines.append(f"  {i}. [{f.get('risk', '?')}] {f.get('description', '')}")

        rumps.alert(
            title="proxy-doctor Diagnosis",
            message="\n".join(lines),
        )

    def _on_copy_json(self, _sender):
        if self._last_report:
            text = json.dumps(self._last_report, indent=2, ensure_ascii=False)
            subprocess.run(["pbcopy"], input=text.encode(), check=False)
            rumps.notification(
                title="proxy-doctor",
                subtitle="",
                message="JSON report copied to clipboard",
            )

    def _on_check_update(self, _sender):
        _ensure_path()
        try:
            from proxy_doctor.updater import check_for_update
            from proxy_doctor import __version__
            result = check_for_update(__version__)
            if result.available:
                rumps.alert(
                    title="Update Available",
                    message=(
                        f"Version {result.latest_version} is available.\n"
                        f"Current: {result.current_version}\n\n"
                        f"Run: pip install --upgrade proxy-doctor\n"
                        f"Or visit: {result.release_url}"
                    ),
                )
            else:
                rumps.alert(
                    title="No Update Available",
                    message=f"You are on the latest version ({__version__}).",
                )
        except Exception as exc:
            rumps.alert(title="Update Check Failed", message=str(exc))

    def _on_toggle_notify(self, sender):
        self._notifications_enabled = not self._notifications_enabled
        label = "ON" if self._notifications_enabled else "OFF"
        sender.title = f"Notifications: {label}"

    def _on_report_issue(self, _sender):
        subprocess.run(
            ["open", "https://github.com/Jiansen/proxy-doctor/issues/new"],
            check=False,
        )

    def _on_github(self, _sender):
        subprocess.run(["open", "https://github.com/Jiansen/proxy-doctor"], check=False)


def main():
    ProxyDoctorApp().run()


if __name__ == "__main__":
    main()

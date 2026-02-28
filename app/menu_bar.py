"""proxy-doctor macOS menu bar application.

Displays proxy health status in the menu bar with periodic refresh.
Uses the same core diagnostic engine as the CLI and MCP server.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import os

import rumps


REFRESH_SECONDS = 300  # 5 minutes

STATUS_ICONS = {
    "healthy": "✓",
    "unhealthy": "✗",
    "warning": "!",
    "error": "?",
}

STATUS_COLORS = {
    "healthy": None,
    "unhealthy": None,
    "warning": None,
    "error": None,
}


def _run_diagnosis() -> dict:
    """Run proxy diagnosis using the core library or CLI fallback."""
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
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
        self._status_item = rumps.MenuItem("Loading...")
        self._cause_item = rumps.MenuItem("")
        self._cause_item.set_callback(None)

        self.menu = [
            self._status_item,
            self._cause_item,
            None,
            rumps.MenuItem("Run Full Diagnosis", callback=self._on_diagnose),
            rumps.MenuItem("Copy JSON Report", callback=self._on_copy_json),
            None,
            rumps.MenuItem("GitHub", callback=self._on_github),
        ]

        self._timer = rumps.Timer(self._on_refresh, REFRESH_SECONDS)
        self._timer.start()
        self._do_refresh()

    def _do_refresh(self):
        """Run diagnosis in background thread to avoid blocking the UI."""
        def _worker():
            report = _run_diagnosis()
            self._last_report = report
            self._update_display(report)
        threading.Thread(target=_worker, daemon=True).start()

    def _update_display(self, report: dict):
        status = report.get("status", "error")
        self.title = STATUS_ICONS.get(status, "?")

        diag = report.get("diagnosis", {})
        root_cause = diag.get("root_cause", "Unknown")
        confidence = diag.get("confidence", "")

        self._status_item.title = f"Status: {status.upper()}"
        if status == "healthy":
            self._cause_item.title = "No proxy issues detected"
        else:
            short = root_cause[:80] + ("..." if len(root_cause) > 80 else "")
            self._cause_item.title = short

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

    def _on_github(self, _sender):
        subprocess.run(["open", "https://github.com/Jiansen/proxy-doctor"], check=False)


def main():
    ProxyDoctorApp().run()


if __name__ == "__main__":
    main()

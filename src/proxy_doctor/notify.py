"""macOS notification system with throttling.

Zero external dependencies — uses osascript for CLI fallback.
When running inside a rumps menu bar app, the caller can use
rumps.notification() directly and skip _send_osascript.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = os.path.expanduser("~/.proxy-doctor")
_APP_NAME = "Proxy Doctor"


# ---------------------------------------------------------------------------
# Notification events
# ---------------------------------------------------------------------------

@dataclass
class NotifyEvent:
    """A structured notification to send."""

    title: str
    body: str
    subtitle: str = ""
    key: str = ""  # dedup key for throttling

    @staticmethod
    def status_change(from_status: str, to_status: str) -> NotifyEvent:
        return NotifyEvent(
            title=_APP_NAME,
            subtitle="Status Change",
            body=f"Proxy status changed: {from_status} → {to_status}",
            key=f"status:{to_status}",
        )

    @staticmethod
    def update_available(version: str, url: str) -> NotifyEvent:
        return NotifyEvent(
            title=_APP_NAME,
            subtitle="Update Available",
            body=f"Version {version} is available. See {url}",
            key=f"update:{version}",
        )

    @staticmethod
    def update_result(
        success: bool,
        version: str,
        error: str = "",
    ) -> NotifyEvent:
        if success:
            return NotifyEvent(
                title=_APP_NAME,
                subtitle="Update Complete",
                body=f"Successfully updated to {version}.",
                key=f"updated:{version}",
            )
        return NotifyEvent(
            title=_APP_NAME,
            subtitle="Update Failed",
            body=f"Update to {version} failed: {error}",
            key=f"update-fail:{version}",
        )


# ---------------------------------------------------------------------------
# osascript backend
# ---------------------------------------------------------------------------

def _build_osascript_cmd(
    title: str,
    body: str,
    subtitle: str = "",
) -> list[str]:
    title_esc = title.replace('"', '\\"')
    body_esc = body.replace('"', '\\"')
    sub_esc = subtitle.replace('"', '\\"')
    parts = [f'with title "{title_esc}"']
    if subtitle:
        parts.append(f'subtitle "{sub_esc}"')
    script = f'display notification "{body_esc}" {" ".join(parts)}'
    return ["osascript", "-e", script]


def _send_osascript(event: NotifyEvent) -> bool:
    cmd = _build_osascript_cmd(event.title, event.body, event.subtitle)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        log.warning("osascript notification failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Notifier with throttling
# ---------------------------------------------------------------------------

class Notifier:
    """Send macOS notifications with per-event dedup throttling."""

    def __init__(
        self,
        throttle_seconds: int = 1800,
        state_dir: str | None = None,
    ) -> None:
        self.throttle_seconds = throttle_seconds
        self.muted = False
        self._last_sent: dict[str, float] = {}
        self._state_dir = Path(state_dir or _DEFAULT_STATE_DIR)

    @property
    def enabled(self) -> bool:
        return not self.muted

    def notify(self, event: NotifyEvent) -> bool:
        """Send a notification. Returns True if actually sent."""
        if self.muted:
            return False

        now = time.monotonic()
        if event.key and event.key in self._last_sent:
            elapsed = now - self._last_sent[event.key]
            if elapsed < self.throttle_seconds:
                log.debug("Throttled notification: %s (%.0fs ago)", event.key, elapsed)
                return False

        sent = _send_osascript(event)
        if sent and event.key:
            self._last_sent[event.key] = now
        return sent

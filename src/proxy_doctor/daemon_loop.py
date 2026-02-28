"""Long-running daemon loop for proxy-doctor.

Runs periodic diagnosis, state diffing, notifications, and update checks.
Intended to be launched by launchd or run directly.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

from proxy_doctor import __version__
from proxy_doctor.core import run_diagnosis
from proxy_doctor.notify import Notifier, NotifyEvent
from proxy_doctor.state import StateCache
from proxy_doctor.updater import check_for_update

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

_CHECK_INTERVAL = 300  # 5 minutes
_UPDATE_CHECK_INTERVAL = 86400  # 24 hours


def _run_once(
    cache: StateCache,
    notifier: Notifier,
    editor: str = "cursor",
) -> None:
    """Single diagnosis cycle."""
    report = run_diagnosis(editor)
    report_dict = report.to_dict()
    change = cache.compare_and_save(report_dict)

    if change.is_initial:
        log.info("Initial diagnosis: %s", report_dict.get("status"))
    elif change.changed:
        log.info("State change: %s", change.summary)
        if "status" in change.changed_fields:
            ev = NotifyEvent.status_change(
                change.from_status or "unknown",
                change.to_status,
            )
            notifier.notify(ev)


def _check_update_once(notifier: Notifier) -> None:
    """Single update check cycle."""
    result = check_for_update(__version__)
    if result.available:
        log.info("Update available: %s", result.latest_version)
        ev = NotifyEvent.update_available(
            result.latest_version or "unknown",
            result.release_url,
        )
        notifier.notify(ev)


def main() -> None:
    cache = StateCache()
    notifier = Notifier(throttle_seconds=1800)

    running = True

    def _handle_signal(signum: int, frame: object) -> None:
        nonlocal running
        log.info("Received signal %d, shutting down", signum)
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info("proxy-doctor daemon started (v%s)", __version__)
    last_update_check = 0.0

    while running:
        try:
            _run_once(cache, notifier)
        except Exception:
            log.exception("Diagnosis cycle failed")

        now = time.monotonic()
        if now - last_update_check >= _UPDATE_CHECK_INTERVAL:
            try:
                _check_update_once(notifier)
            except Exception:
                log.exception("Update check failed")
            last_update_check = now

        for _ in range(_CHECK_INTERVAL):
            if not running:
                break
            time.sleep(1)

    log.info("proxy-doctor daemon stopped")


if __name__ == "__main__":
    main()

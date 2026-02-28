"""Tests for proxy_doctor.notify — macOS notifications with throttling."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

from proxy_doctor.notify import (
    Notifier,
    NotifyEvent,
    _build_osascript_cmd,
)


class TestBuildOsascriptCmd(unittest.TestCase):
    def test_basic_notification(self):
        cmd = _build_osascript_cmd("Title", "Body")
        self.assertIn("osascript", cmd[0])
        self.assertIn("Title", cmd[-1])
        self.assertIn("Body", cmd[-1])

    def test_subtitle_included(self):
        cmd = _build_osascript_cmd("Title", "Body", subtitle="Sub")
        script = cmd[-1]
        self.assertIn("Sub", script)

    def test_special_chars_escaped(self):
        cmd = _build_osascript_cmd('Say "hello"', "It's fine")
        script = cmd[-1]
        self.assertIn('\\"', script)


class TestNotifyEvent(unittest.TestCase):
    def test_status_change_event(self):
        ev = NotifyEvent.status_change("healthy", "unhealthy")
        self.assertEqual(ev.title, "Proxy Doctor")
        self.assertIn("unhealthy", ev.body.lower())

    def test_update_available_event(self):
        ev = NotifyEvent.update_available("0.2.0", "https://example.com")
        self.assertIn("0.2.0", ev.body)

    def test_update_result_success(self):
        ev = NotifyEvent.update_result(success=True, version="0.2.0")
        self.assertIn("0.2.0", ev.body)
        self.assertNotIn("failed", ev.body.lower())

    def test_update_result_failure(self):
        ev = NotifyEvent.update_result(success=False, version="0.2.0",
                                       error="pip error")
        self.assertIn("failed", ev.body.lower())


class TestNotifier(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.notifier = Notifier(
            throttle_seconds=2,
            state_dir=self.tmpdir,
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("proxy_doctor.notify._send_osascript")
    def test_sends_notification(self, mock_send):
        mock_send.return_value = True
        ev = NotifyEvent.status_change("healthy", "unhealthy")
        sent = self.notifier.notify(ev)
        self.assertTrue(sent)
        mock_send.assert_called_once()

    @patch("proxy_doctor.notify._send_osascript")
    def test_throttle_blocks_duplicate(self, mock_send):
        mock_send.return_value = True
        ev = NotifyEvent.status_change("healthy", "unhealthy")
        self.notifier.notify(ev)
        sent2 = self.notifier.notify(ev)
        self.assertFalse(sent2)
        self.assertEqual(mock_send.call_count, 1)

    @patch("proxy_doctor.notify._send_osascript")
    def test_different_events_not_throttled(self, mock_send):
        mock_send.return_value = True
        ev1 = NotifyEvent.status_change("healthy", "unhealthy")
        ev2 = NotifyEvent.update_available("0.3.0", "https://example.com")
        self.notifier.notify(ev1)
        sent2 = self.notifier.notify(ev2)
        self.assertTrue(sent2)
        self.assertEqual(mock_send.call_count, 2)

    @patch("proxy_doctor.notify._send_osascript")
    def test_muted_blocks_all(self, mock_send):
        self.notifier.muted = True
        ev = NotifyEvent.status_change("healthy", "unhealthy")
        sent = self.notifier.notify(ev)
        self.assertFalse(sent)
        mock_send.assert_not_called()

    @patch("proxy_doctor.notify._send_osascript")
    def test_throttle_expires(self, mock_send):
        mock_send.return_value = True
        notifier = Notifier(throttle_seconds=0, state_dir=self.tmpdir)
        ev = NotifyEvent.status_change("healthy", "unhealthy")
        notifier.notify(ev)
        sent2 = notifier.notify(ev)
        self.assertTrue(sent2)

    def test_enabled_property(self):
        self.assertTrue(self.notifier.enabled)
        self.notifier.muted = True
        self.assertFalse(self.notifier.enabled)


if __name__ == "__main__":
    unittest.main()

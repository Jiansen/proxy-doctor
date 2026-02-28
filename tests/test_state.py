"""Tests for proxy_doctor.state — State Diff Engine."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from proxy_doctor.state import (
    StateCache,
    StateChange,
    compare_reports,
)


def _make_report_dict(
    status: str = "healthy",
    case: str = "clean",
    port_statuses: list | None = None,
    system_proxies: list | None = None,
) -> dict:
    return {
        "version": "0.2.0",
        "editor": "cursor",
        "platform": "Darwin",
        "status": status,
        "diagnosis": {
            "case": case,
            "root_cause": "test",
            "confidence": "high",
            "source": "all_layers",
            "browser_explanation": "",
        },
        "fixes": [],
        "evidence": {
            "system_proxies": system_proxies or [],
            "residual_proxies": [],
            "port_statuses": port_statuses or [],
            "editor_config": {
                "settings_proxy": {},
                "argv_proxy": {},
                "log_errors": [],
            },
            "launchctl_env": {},
            "env_proxies": [],
        },
    }


class TestCompareReports(unittest.TestCase):
    def test_no_previous_returns_initial(self):
        current = _make_report_dict()
        change = compare_reports(None, current)
        self.assertTrue(change.is_initial)
        self.assertIsNone(change.from_status)
        self.assertEqual(change.to_status, "healthy")

    def test_same_status_no_change(self):
        old = _make_report_dict(status="healthy")
        new = _make_report_dict(status="healthy")
        change = compare_reports(old, new)
        self.assertFalse(change.changed)
        self.assertEqual(change.from_status, "healthy")
        self.assertEqual(change.to_status, "healthy")

    def test_status_change_detected(self):
        old = _make_report_dict(status="healthy")
        new = _make_report_dict(status="unhealthy", case="A")
        change = compare_reports(old, new)
        self.assertTrue(change.changed)
        self.assertEqual(change.from_status, "healthy")
        self.assertEqual(change.to_status, "unhealthy")
        self.assertIn("status", change.changed_fields)

    def test_case_change_detected(self):
        old = _make_report_dict(status="unhealthy", case="A")
        new = _make_report_dict(status="unhealthy", case="B")
        change = compare_reports(old, new)
        self.assertTrue(change.changed)
        self.assertIn("case", change.changed_fields)

    def test_port_status_change_detected(self):
        old_ports = [{"host": "127.0.0.1", "port": 7890, "status": "refused", "detail": ""}]
        new_ports = [{"host": "127.0.0.1", "port": 7890, "status": "listening", "detail": ""}]
        old = _make_report_dict(port_statuses=old_ports)
        new = _make_report_dict(port_statuses=new_ports)
        change = compare_reports(old, new)
        self.assertTrue(change.changed)
        self.assertIn("port_statuses", change.changed_fields)

    def test_new_proxy_detected(self):
        old = _make_report_dict(system_proxies=[])
        new_proxies = [
            {"layer": "system_proxy", "source": "Wi-Fi (http)", "protocol": "http",
             "host": "127.0.0.1", "port": 7890, "enabled": True, "raw": ""}
        ]
        new = _make_report_dict(system_proxies=new_proxies)
        change = compare_reports(old, new)
        self.assertTrue(change.changed)
        self.assertIn("system_proxies", change.changed_fields)

    def test_summary_healthy_to_unhealthy(self):
        old = _make_report_dict(status="healthy")
        new = _make_report_dict(status="unhealthy", case="A")
        change = compare_reports(old, new)
        self.assertIn("healthy", change.summary)
        self.assertIn("unhealthy", change.summary)

    def test_summary_initial(self):
        change = compare_reports(None, _make_report_dict())
        self.assertIn("Initial", change.summary)


class TestStateChange(unittest.TestCase):
    def test_changed_is_false_when_no_fields(self):
        sc = StateChange(from_status="healthy", to_status="healthy", changed_fields=[])
        self.assertFalse(sc.changed)

    def test_changed_is_true_when_fields_present(self):
        sc = StateChange(from_status="healthy", to_status="unhealthy",
                         changed_fields=["status"])
        self.assertTrue(sc.changed)

    def test_is_initial_true_when_from_none(self):
        sc = StateChange(from_status=None, to_status="healthy",
                         changed_fields=[], is_initial=True)
        self.assertTrue(sc.is_initial)


class TestStateCache(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.cache = StateCache(cache_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_empty_returns_none(self):
        self.assertIsNone(self.cache.load())

    def test_save_and_load_roundtrip(self):
        report = _make_report_dict()
        self.cache.save(report)
        loaded = self.cache.load()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["status"], "healthy")

    def test_save_creates_directory(self):
        nested = os.path.join(self.tmpdir, "sub", "dir")
        cache = StateCache(cache_dir=nested)
        cache.save(_make_report_dict())
        self.assertTrue(os.path.isdir(nested))

    def test_load_corrupted_file_returns_none(self):
        path = os.path.join(self.tmpdir, "last_report.json")
        with open(path, "w") as f:
            f.write("not valid json{{{")
        self.assertIsNone(self.cache.load())

    def test_save_and_compare(self):
        old = _make_report_dict(status="healthy")
        self.cache.save(old)
        new = _make_report_dict(status="unhealthy", case="A")
        change = self.cache.compare_and_save(new)
        self.assertTrue(change.changed)
        self.assertEqual(change.from_status, "healthy")
        self.assertEqual(change.to_status, "unhealthy")
        reloaded = self.cache.load()
        self.assertEqual(reloaded["status"], "unhealthy")

    def test_compare_and_save_first_run(self):
        report = _make_report_dict()
        change = self.cache.compare_and_save(report)
        self.assertTrue(change.is_initial)


if __name__ == "__main__":
    unittest.main()

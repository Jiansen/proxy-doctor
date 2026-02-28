"""Tests for proxy_doctor.daemon — launchd integration and daemon CLI."""

from __future__ import annotations

import os
import plistlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from proxy_doctor.daemon import (
    PLIST_LABEL,
    build_plist,
    plist_path,
    daemon_status,
)


class TestBuildPlist(unittest.TestCase):
    def test_returns_valid_plist_dict(self):
        plist = build_plist(interval=300)
        self.assertEqual(plist["Label"], PLIST_LABEL)
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])
        self.assertEqual(plist["StartInterval"], 300)
        self.assertIn("ProgramArguments", plist)

    def test_program_arguments_uses_python(self):
        plist = build_plist()
        args = plist["ProgramArguments"]
        self.assertTrue(any("python" in a.lower() or "proxy_doctor" in a for a in args))

    def test_log_paths_under_proxy_doctor(self):
        plist = build_plist()
        self.assertIn(".proxy-doctor", plist["StandardOutPath"])
        self.assertIn(".proxy-doctor", plist["StandardErrorPath"])

    def test_custom_interval(self):
        plist = build_plist(interval=60)
        self.assertEqual(plist["StartInterval"], 60)

    def test_plist_serializable(self):
        plist = build_plist()
        data = plistlib.dumps(plist)
        self.assertIsInstance(data, bytes)
        roundtrip = plistlib.loads(data)
        self.assertEqual(roundtrip["Label"], PLIST_LABEL)


class TestPlistPath(unittest.TestCase):
    def test_returns_path_in_launch_agents(self):
        p = plist_path()
        self.assertIn("LaunchAgents", str(p))
        self.assertTrue(str(p).endswith(".plist"))
        self.assertIn(PLIST_LABEL, str(p))


class TestDaemonStatus(unittest.TestCase):
    @patch("proxy_doctor.daemon._run_launchctl_list")
    def test_running(self, mock_list):
        mock_list.return_value = f"some output with {PLIST_LABEL}"
        status = daemon_status()
        self.assertEqual(status["state"], "running")

    @patch("proxy_doctor.daemon._run_launchctl_list")
    def test_not_running(self, mock_list):
        mock_list.return_value = ""
        status = daemon_status()
        self.assertEqual(status["state"], "not_running")

    @patch("proxy_doctor.daemon._run_launchctl_list")
    def test_status_includes_plist_path(self, mock_list):
        mock_list.return_value = ""
        status = daemon_status()
        self.assertIn("plist_path", status)


if __name__ == "__main__":
    unittest.main()

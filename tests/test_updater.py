"""Tests for proxy_doctor.updater — Auto-Update + rollback."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from proxy_doctor.updater import (
    UpdateResult,
    UpdateState,
    check_for_update,
    compare_versions,
    perform_update,
)


class TestCompareVersions(unittest.TestCase):
    def test_newer_available(self):
        self.assertTrue(compare_versions("0.2.0", "0.1.1"))

    def test_same_version(self):
        self.assertFalse(compare_versions("0.1.1", "0.1.1"))

    def test_older_available(self):
        self.assertFalse(compare_versions("0.1.0", "0.1.1"))

    def test_major_bump(self):
        self.assertTrue(compare_versions("1.0.0", "0.9.9"))

    def test_patch_bump(self):
        self.assertTrue(compare_versions("0.1.2", "0.1.1"))

    def test_malformed_version_returns_false(self):
        self.assertFalse(compare_versions("not.a.version", "0.1.1"))

    def test_empty_version_returns_false(self):
        self.assertFalse(compare_versions("", "0.1.1"))


class TestCheckForUpdate(unittest.TestCase):
    @patch("proxy_doctor.updater._fetch_pypi_version")
    def test_update_available(self, mock_fetch):
        mock_fetch.return_value = "0.3.0"
        result = check_for_update("0.2.0")
        self.assertTrue(result.available)
        self.assertEqual(result.latest_version, "0.3.0")
        self.assertEqual(result.current_version, "0.2.0")

    @patch("proxy_doctor.updater._fetch_pypi_version")
    def test_no_update(self, mock_fetch):
        mock_fetch.return_value = "0.2.0"
        result = check_for_update("0.2.0")
        self.assertFalse(result.available)

    @patch("proxy_doctor.updater._fetch_pypi_version")
    def test_fetch_fails(self, mock_fetch):
        mock_fetch.return_value = None
        result = check_for_update("0.2.0")
        self.assertFalse(result.available)
        self.assertIn("check failed", result.error)


class TestUpdateState(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state = UpdateState(state_dir=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_initial_state_empty(self):
        data = self.state.load()
        self.assertIsNone(data.get("previous_version"))

    def test_save_pre_update_state(self):
        self.state.save_pre_update("0.1.1")
        data = self.state.load()
        self.assertEqual(data["previous_version"], "0.1.1")
        self.assertIn("timestamp", data)

    def test_save_update_result(self):
        self.state.save_pre_update("0.1.1")
        self.state.save_result(success=True, new_version="0.2.0")
        data = self.state.load()
        self.assertTrue(data["last_update_success"])
        self.assertEqual(data["updated_to"], "0.2.0")

    def test_save_failed_result(self):
        self.state.save_pre_update("0.1.1")
        self.state.save_result(success=False, new_version="0.2.0",
                               error="pip install failed")
        data = self.state.load()
        self.assertFalse(data["last_update_success"])
        self.assertEqual(data["error"], "pip install failed")


class TestPerformUpdate(unittest.TestCase):
    @patch("proxy_doctor.updater._run_pip_install")
    @patch("proxy_doctor.updater._verify_installation")
    def test_successful_update(self, mock_verify, mock_pip):
        mock_pip.return_value = (True, "")
        mock_verify.return_value = True
        tmpdir = tempfile.mkdtemp()
        try:
            result = perform_update(
                current_version="0.1.1",
                target_version="0.2.0",
                state_dir=tmpdir,
            )
            self.assertTrue(result.success)
            self.assertEqual(result.new_version, "0.2.0")
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("proxy_doctor.updater._run_pip_install")
    def test_pip_failure(self, mock_pip):
        mock_pip.return_value = (False, "pip error")
        tmpdir = tempfile.mkdtemp()
        try:
            result = perform_update(
                current_version="0.1.1",
                target_version="0.2.0",
                state_dir=tmpdir,
            )
            self.assertFalse(result.success)
            self.assertIn("pip", result.error)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    @patch("proxy_doctor.updater._run_pip_install")
    @patch("proxy_doctor.updater._verify_installation")
    def test_verification_failure_triggers_rollback(self, mock_verify, mock_pip):
        mock_pip.return_value = (True, "")
        mock_verify.return_value = False

        tmpdir = tempfile.mkdtemp()
        try:
            result = perform_update(
                current_version="0.1.1",
                target_version="0.2.0",
                state_dir=tmpdir,
            )
            self.assertFalse(result.success)
            self.assertTrue(result.rolled_back)
            # pip should be called twice: upgrade then rollback
            self.assertEqual(mock_pip.call_count, 2)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

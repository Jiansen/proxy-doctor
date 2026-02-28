"""Tests for proxy_doctor.cli — CLI entry point."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


class TestCLIHelp(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "proxy_doctor.cli", *args],
            capture_output=True, text=True, timeout=30,
            env={"PYTHONPATH": str(SRC_DIR), "PATH": "/usr/bin:/bin"},
        )

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("proxy-doctor", r.stdout)

    def test_version(self):
        r = self._run("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn("0.1.1", r.stdout)

    def test_editors(self):
        r = self._run("editors")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertIn("cursor", data["supported_editors"])

    def test_check_json(self):
        r = self._run("check", "--json")
        data = json.loads(r.stdout)
        self.assertIn(data["status"], ("healthy", "unhealthy", "warning"))
        self.assertIn("diagnosis", data)
        self.assertIn("evidence", data)

    def test_check_human(self):
        r = self._run("check", "--human")
        self.assertIn("proxy-doctor v", r.stdout)
        self.assertIn("Status:", r.stdout)

    def test_fix_json(self):
        r = self._run("fix")
        data = json.loads(r.stdout)
        self.assertIn("status", data)
        self.assertIn("fixes", data)

    def test_no_command_shows_help(self):
        r = self._run()
        self.assertEqual(r.returncode, 0)
        self.assertIn("proxy-doctor", r.stdout)

    def test_check_exit_code_matches_status(self):
        r = self._run("check", "--json")
        data = json.loads(r.stdout)
        if data["status"] == "healthy":
            self.assertEqual(r.returncode, 0)
        else:
            self.assertEqual(r.returncode, 1)

    def test_check_markdown_output(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            md_path = f.name
        try:
            r = self._run("check", "--human", "--markdown", md_path)
            self.assertIn("proxy-doctor v", r.stdout)
            content = Path(md_path).read_text(encoding="utf-8")
            self.assertIn("# proxy-doctor report", content)
            self.assertIn("Evidence (JSON)", content)
        finally:
            Path(md_path).unlink(missing_ok=True)

    def test_check_editor_flag(self):
        r = self._run("check", "--json", "--editor", "vscode")
        data = json.loads(r.stdout)
        self.assertEqual(data["editor"], "vscode")

    def test_fix_exit_code_matches_status(self):
        r = self._run("fix")
        data = json.loads(r.stdout)
        if data["status"] == "healthy":
            self.assertEqual(r.returncode, 0)
        else:
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main()

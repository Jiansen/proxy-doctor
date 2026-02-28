"""Tests for proxy_doctor.mcp_server — MCP tool schemas and responses."""

from __future__ import annotations

import unittest

try:
    from proxy_doctor.mcp_server import diagnose_proxy, list_fixes, supported_editors
    HAS_MCP = True
except ImportError:
    HAS_MCP = False


@unittest.skipUnless(HAS_MCP, "fastmcp not installed")
class TestMCPTools(unittest.TestCase):
    def test_diagnose_proxy_returns_dict(self):
        result = diagnose_proxy(editor="cursor")
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("diagnosis", result)
        self.assertIn("fixes", result)
        self.assertIn("evidence", result)

    def test_list_fixes_returns_dict(self):
        result = list_fixes(editor="cursor")
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)
        self.assertIn("fixes", result)

    def test_supported_editors_returns_list(self):
        result = supported_editors()
        self.assertIsInstance(result, dict)
        self.assertIn("supported_editors", result)
        self.assertIn("cursor", result["supported_editors"])

    def test_diagnose_invalid_editor(self):
        result = diagnose_proxy(editor="nonexistent")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "healthy")


if __name__ == "__main__":
    unittest.main()

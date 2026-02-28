"""Tests for proxy_doctor.editors — editor path registry."""

from __future__ import annotations

import platform
import unittest

from proxy_doctor.editors import EditorPaths, get_editor, list_editors


class TestGetEditor(unittest.TestCase):
    def test_cursor_returns_editor(self):
        editor = get_editor("cursor")
        if platform.system() in ("Darwin", "Linux"):
            self.assertIsNotNone(editor)
            self.assertEqual(editor.name, "Cursor")
        else:
            self.assertIsNone(editor)

    def test_vscode_returns_editor(self):
        editor = get_editor("vscode")
        if platform.system() in ("Darwin", "Linux"):
            self.assertIsNotNone(editor)
            self.assertEqual(editor.name, "VS Code")

    def test_windsurf_returns_editor_macos(self):
        editor = get_editor("windsurf")
        if platform.system() == "Darwin":
            self.assertIsNotNone(editor)
            self.assertEqual(editor.name, "Windsurf")
        elif platform.system() == "Linux":
            self.assertIsNone(editor)

    def test_nonexistent_returns_none(self):
        self.assertIsNone(get_editor("nonexistent"))

    def test_case_insensitive(self):
        editor = get_editor("Cursor")
        if platform.system() in ("Darwin", "Linux"):
            self.assertIsNotNone(editor)

    def test_empty_string_returns_none(self):
        self.assertIsNone(get_editor(""))


class TestListEditors(unittest.TestCase):
    def test_returns_list(self):
        editors = list_editors()
        self.assertIsInstance(editors, list)

    def test_contains_cursor(self):
        editors = list_editors()
        if platform.system() in ("Darwin", "Linux"):
            self.assertIn("cursor", editors)

    def test_contains_vscode(self):
        editors = list_editors()
        if platform.system() in ("Darwin", "Linux"):
            self.assertIn("vscode", editors)

    def test_macos_has_windsurf(self):
        editors = list_editors()
        if platform.system() == "Darwin":
            self.assertIn("windsurf", editors)


class TestEditorPaths(unittest.TestCase):
    def test_cursor_has_settings_json(self):
        editor = get_editor("cursor")
        if editor:
            self.assertIsNotNone(editor.settings_json)
            self.assertTrue(str(editor.settings_json).endswith("settings.json"))

    def test_cursor_has_argv_json(self):
        editor = get_editor("cursor")
        if editor and platform.system() == "Darwin":
            self.assertIsNotNone(editor.argv_json)

    def test_cursor_has_logs_dir(self):
        editor = get_editor("cursor")
        if editor:
            self.assertIsNotNone(editor.logs_dir)

    def test_proxy_keys_are_tuples(self):
        editor = get_editor("cursor")
        if editor:
            self.assertIsInstance(editor.proxy_keys, tuple)
            self.assertTrue(len(editor.proxy_keys) > 0)

    def test_log_error_patterns_not_empty(self):
        editor = get_editor("cursor")
        if editor:
            self.assertIsInstance(editor.log_error_patterns, tuple)
            self.assertTrue(len(editor.log_error_patterns) > 0)

    def test_cursor_has_extra_keys(self):
        editor = get_editor("cursor")
        if editor and platform.system() == "Darwin":
            self.assertTrue(len(editor.extra_keys) > 0)
            self.assertTrue(any("Http2" in k or "http2" in k for k in editor.extra_keys))

    def test_frozen_dataclass(self):
        editor = get_editor("cursor")
        if editor:
            with self.assertRaises(AttributeError):
                editor.name = "Modified"


if __name__ == "__main__":
    unittest.main()

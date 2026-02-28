"""Tests for proxy_doctor.core — parsing, diagnosis logic, and port detection."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proxy_doctor.core import (
    Diagnosis,
    EditorConfigFindings,
    Fix,
    LayerResults,
    PortStatus,
    ProxyEntry,
    Report,
    _fixes_case_a,
    _fixes_case_b,
    _fixes_case_c,
    _is_local_address,
    _parse_proxy_output,
    _parse_proxy_url,
    _probe_port,
    check_editor_config,
    check_launchctl_env,
    check_port_health,
    check_system_proxy,
    diagnose,
)
from proxy_doctor.editors import EditorPaths


class TestParseProxyOutput(unittest.TestCase):
    def test_enabled_proxy(self):
        output = "Enabled: Yes\nServer: 127.0.0.1\nPort: 7890\nAuthenticated Proxy Enabled: 0"
        result = _parse_proxy_output(output)
        self.assertEqual(result["Enabled"], "Yes")
        self.assertEqual(result["Server"], "127.0.0.1")
        self.assertEqual(result["Port"], "7890")

    def test_disabled_proxy(self):
        output = "Enabled: No\nServer: 127.0.0.1\nPort: 10903\nAuthenticated Proxy Enabled: 0"
        result = _parse_proxy_output(output)
        self.assertEqual(result["Enabled"], "No")
        self.assertEqual(result["Server"], "127.0.0.1")

    def test_empty_output(self):
        result = _parse_proxy_output("")
        self.assertEqual(result, {})

    def test_null_server(self):
        output = "Enabled: No\nServer: (null)\nPort: 0"
        result = _parse_proxy_output(output)
        self.assertEqual(result["Server"], "(null)")


class TestParseProxyUrl(unittest.TestCase):
    def test_http_url(self):
        host, port = _parse_proxy_url("http://127.0.0.1:7890")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 7890)

    def test_socks_url(self):
        host, port = _parse_proxy_url("socks5://localhost:1080")
        self.assertEqual(host, "localhost")
        self.assertEqual(port, 1080)

    def test_url_with_auth(self):
        host, port = _parse_proxy_url("http://user:pass@proxy.example.com:8080")
        self.assertEqual(host, "proxy.example.com")
        self.assertEqual(port, 8080)

    def test_bare_host_port(self):
        host, port = _parse_proxy_url("127.0.0.1:3128")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 3128)

    def test_empty_string(self):
        host, port = _parse_proxy_url("")
        self.assertEqual(host, "")
        self.assertEqual(port, 0)

    def test_no_port_url(self):
        host, port = _parse_proxy_url("http://proxy.example.com")
        self.assertEqual(host, "proxy.example.com")
        self.assertEqual(port, 0)

    def test_socks4_url(self):
        host, port = _parse_proxy_url("socks4://127.0.0.1:1080")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 1080)

    def test_just_hostname_no_port(self):
        host, port = _parse_proxy_url("proxy.example.com")
        self.assertEqual(host, "")
        self.assertEqual(port, 0)

    def test_url_with_path(self):
        host, port = _parse_proxy_url("http://127.0.0.1:8080/path")
        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 8080)


class TestIsLocalAddress(unittest.TestCase):
    def test_localhost_variants(self):
        self.assertTrue(_is_local_address("127.0.0.1"))
        self.assertTrue(_is_local_address("localhost"))
        self.assertTrue(_is_local_address("::1"))

    def test_remote_address(self):
        self.assertFalse(_is_local_address("192.168.1.1"))
        self.assertFalse(_is_local_address("proxy.example.com"))


class TestPortProbe(unittest.TestCase):
    def test_listening_port(self):
        """Open a real TCP socket and verify detection."""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            result = _probe_port("127.0.0.1", port, timeout=2.0)
            self.assertEqual(result.status, "listening")
        finally:
            srv.close()

    def test_refused_port(self):
        """Use a likely-unused high port to test connection refused."""
        result = _probe_port("127.0.0.1", 19999, timeout=1.0)
        self.assertEqual(result.status, "refused")


class TestCheckPortHealth(unittest.TestCase):
    def test_deduplication(self):
        """Same host:port from multiple entries should be probed only once."""
        entries = [
            ProxyEntry("a", "s1", "http", "127.0.0.1", 19999, True),
            ProxyEntry("b", "s2", "https", "127.0.0.1", 19999, True),
        ]
        results = check_port_health(entries)
        self.assertEqual(len(results), 1)

    def test_skips_pac(self):
        """PAC protocol entries should be skipped."""
        entries = [
            ProxyEntry("a", "s1", "pac", "http://example.com/proxy.pac", 0, True),
        ]
        results = check_port_health(entries)
        self.assertEqual(len(results), 0)

    def test_skips_port_zero(self):
        """Entries with port=0 are skipped."""
        entries = [
            ProxyEntry("a", "s1", "http", "127.0.0.1", 0, True),
        ]
        results = check_port_health(entries)
        self.assertEqual(len(results), 0)

    def test_remote_address_ports_probed(self):
        """Remote address ports are still probed (not skipped)."""
        entries = [
            ProxyEntry("a", "s1", "http", "192.168.1.1", 3128, True),
        ]
        results = check_port_health(entries)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].host, "192.168.1.1")
        self.assertEqual(results[0].port, 3128)

    def test_multiple_different_ports(self):
        """Multiple different ports produce multiple results."""
        entries = [
            ProxyEntry("a", "s1", "http", "127.0.0.1", 19998, True),
            ProxyEntry("b", "s2", "https", "127.0.0.1", 19999, True),
        ]
        results = check_port_health(entries)
        self.assertEqual(len(results), 2)


class TestDiagnoseLogic(unittest.TestCase):
    def _entry(self, host="127.0.0.1", port=10903, enabled=True, layer="system_proxy"):
        return ProxyEntry(layer, f"Wi-Fi ({layer})", "http", host, port, enabled)

    def test_case_a_dead_port(self):
        """Proxy reference + dead port = Case A, high confidence."""
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "A")
        self.assertEqual(d.status, "unhealthy")
        self.assertEqual(d.confidence, "high")
        self.assertTrue(len(d.fixes) > 0)

    def test_case_b_live_port_with_buffering(self):
        """Proxy alive + buffering log errors = Case B."""
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "listening")],
            editor_config=EditorConfigFindings(
                log_errors=["[renderer.log] Streaming responses are being buffered by a proxy"],
            ),
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "B")
        self.assertEqual(d.status, "unhealthy")
        self.assertEqual(d.confidence, "medium")

    def test_case_c_residual(self):
        """Residual proxy values = Case C, warning."""
        ev = LayerResults(
            residual_proxies=[self._entry(enabled=False)],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "C")
        self.assertEqual(d.status, "warning")

    def test_clean(self):
        """No proxy issues = clean."""
        ev = LayerResults()
        d = diagnose(ev)
        self.assertEqual(d.case, "clean")
        self.assertEqual(d.status, "healthy")

    def test_log_errors_only(self):
        """Log errors without proxy reference = warning/low confidence."""
        ev = LayerResults(
            editor_config=EditorConfigFindings(
                log_errors=["[renderer.log] PROXY 127.0.0.1:10903 failed"],
            ),
        )
        d = diagnose(ev)
        self.assertEqual(d.status, "warning")
        self.assertEqual(d.confidence, "low")


class TestReport(unittest.TestCase):
    def test_to_json_is_valid(self):
        report = Report(
            diagnosis=Diagnosis(
                status="healthy", case="clean", root_cause="No issues.",
                confidence="high", source="all", browser_explanation="",
            ),
            evidence=LayerResults(),
            editor="cursor",
            platform="Darwin",
        )
        data = json.loads(report.to_json())
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["editor"], "cursor")

    def test_to_human_contains_status(self):
        report = Report(
            diagnosis=Diagnosis(
                status="unhealthy", case="A",
                root_cause="Port dead.",
                confidence="high", source="system_proxy",
                browser_explanation="Different path.",
                fixes=[Fix("f1", "Fix it", "cmd", "low", "system")],
            ),
            evidence=LayerResults(),
            editor="cursor",
            platform="Darwin",
        )
        text = report.to_human()
        self.assertIn("UNHEALTHY", text)
        self.assertIn("Port dead.", text)
        self.assertIn("Fix it", text)


class TestCheckSystemProxy(unittest.TestCase):
    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run")
    def test_multi_service_mixed_enabled_disabled(self, mock_run, _mock_system):
        def run_side_effect(cmd, timeout=5):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "-listallnetworkservices" in cmd_str:
                return "Wi-Fi\nEthernet\n*"
            if "Wi-Fi" in cmd_str:
                if "-getwebproxy" in cmd_str:
                    return "Enabled: Yes\nServer: 127.0.0.1\nPort: 7890"
                if "-getsecurewebproxy" in cmd_str:
                    return "Enabled: No\nServer: 127.0.0.1\nPort: 7890"
                if "-getsocksfirewallproxy" in cmd_str:
                    return "Enabled: No\nServer: (null)\nPort: 0"
                if "-getautoproxyurl" in cmd_str:
                    return "Enabled: No\nURL: (null)"
            if "Ethernet" in cmd_str:
                if "-getwebproxy" in cmd_str:
                    return "Enabled: No\nServer: 192.168.1.1\nPort: 3128"
                if "-getsecurewebproxy" in cmd_str or "-getsocksfirewallproxy" in cmd_str:
                    return "Enabled: No\nServer: (null)\nPort: 0"
                if "-getautoproxyurl" in cmd_str:
                    return "Enabled: No\nURL: (null)"
            return ""

        mock_run.side_effect = run_side_effect
        active, residual = check_system_proxy()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].host, "127.0.0.1")
        self.assertEqual(active[0].port, 7890)
        self.assertEqual(active[0].enabled, True)

    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run")
    def test_null_server_skipped(self, mock_run, _mock_system):
        def run_side_effect(cmd, timeout=5):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "-listallnetworkservices" in cmd_str:
                return "Wi-Fi\n"
            if "-getwebproxy" in cmd_str:
                return "Enabled: Yes\nServer: (null)\nPort: 0"
            if "-getsecurewebproxy" in cmd_str or "-getsocksfirewallproxy" in cmd_str:
                return "Enabled: No\nServer: (null)\nPort: 0"
            if "-getautoproxyurl" in cmd_str:
                return "Enabled: No\nURL: (null)"
            return ""

        mock_run.side_effect = run_side_effect
        active, residual = check_system_proxy()
        self.assertEqual(len(active), 0)
        self.assertEqual(len(residual), 0)

    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run")
    def test_pac_url_detection(self, mock_run, _mock_system):
        def run_side_effect(cmd, timeout=5):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "-listallnetworkservices" in cmd_str:
                return "Wi-Fi\n"
            if "-getwebproxy" in cmd_str or "-getsecurewebproxy" in cmd_str:
                return "Enabled: No\nServer: (null)\nPort: 0"
            if "-getsocksfirewallproxy" in cmd_str:
                return "Enabled: No\nServer: (null)\nPort: 0"
            if "-getautoproxyurl" in cmd_str:
                return "Enabled: Yes\nURL: http://example.com/proxy.pac"
            return ""

        mock_run.side_effect = run_side_effect
        active, residual = check_system_proxy()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].protocol, "pac")
        self.assertEqual(active[0].host, "http://example.com/proxy.pac")
        self.assertEqual(active[0].port, 0)

    @patch("proxy_doctor.core.platform.system", return_value="Linux")
    def test_non_darwin_returns_empty(self, _mock_system):
        active, residual = check_system_proxy()
        self.assertEqual(active, [])
        self.assertEqual(residual, [])

    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run")
    def test_residual_proxy_disabled_localhost(self, mock_run, _mock_system):
        def run_side_effect(cmd, timeout=5):
            cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "-listallnetworkservices" in cmd_str:
                return "Wi-Fi\n"
            if "-getwebproxy" in cmd_str:
                return "Enabled: No\nServer: 127.0.0.1\nPort: 10903"
            if "-getsecurewebproxy" in cmd_str or "-getsocksfirewallproxy" in cmd_str:
                return "Enabled: No\nServer: (null)\nPort: 0"
            if "-getautoproxyurl" in cmd_str:
                return "Enabled: No\nURL: (null)"
            return ""

        mock_run.side_effect = run_side_effect
        active, residual = check_system_proxy()
        self.assertEqual(len(active), 0)
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0].host, "127.0.0.1")
        self.assertEqual(residual[0].enabled, False)


class TestCheckEditorConfig(unittest.TestCase):
    def test_settings_json_proxy_keys_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text(
                '{"http.proxy": "http://127.0.0.1:7890", "other": "x"}',
                encoding="utf-8",
            )
            editor = EditorPaths(
                name="Test",
                settings_json=settings,
                argv_json=None,
                logs_dir=None,
            )
            findings = check_editor_config(editor)
            self.assertIn("http.proxy", findings.settings_proxy)
            self.assertEqual(
                findings.settings_proxy["http.proxy"],
                "http://127.0.0.1:7890",
            )

    def test_malformed_json_no_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Path(tmp) / "settings.json"
            settings.write_text("{ invalid json }", encoding="utf-8")
            editor = EditorPaths(
                name="Test",
                settings_json=settings,
                argv_json=None,
                logs_dir=None,
            )
            findings = check_editor_config(editor)
            self.assertEqual(findings.settings_proxy, {})
            self.assertEqual(findings.argv_proxy, {})

    def test_argv_json_proxy_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv = Path(tmp) / "argv.json"
            argv.write_text(
                '{"--proxy-server": "127.0.0.1:3128"}',
                encoding="utf-8",
            )
            editor = EditorPaths(
                name="Test",
                settings_json=None,
                argv_json=argv,
                logs_dir=None,
            )
            findings = check_editor_config(editor)
            self.assertIn("--proxy-server", findings.argv_proxy)
            self.assertEqual(findings.argv_proxy["--proxy-server"], "127.0.0.1:3128")

    def test_log_files_error_patterns_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            log_dir.mkdir()
            (log_dir / "renderer.log").write_text(
                "Some line\n[renderer] PROXY 127.0.0.1 failed\n",
                encoding="utf-8",
            )
            editor = EditorPaths(
                name="Test",
                settings_json=None,
                argv_json=None,
                logs_dir=log_dir,
                log_error_patterns=("PROXY 127.0.0.1",),
            )
            findings = check_editor_config(editor)
            self.assertGreater(len(findings.log_errors), 0)
            self.assertTrue(
                any("PROXY 127.0.0.1" in e for e in findings.log_errors)
            )

    def test_missing_files_empty_findings(self):
        editor = EditorPaths(
            name="Test",
            settings_json=Path("/nonexistent/settings.json"),
            argv_json=Path("/nonexistent/argv.json"),
            logs_dir=Path("/nonexistent/logs"),
        )
        findings = check_editor_config(editor)
        self.assertEqual(findings.settings_proxy, {})
        self.assertEqual(findings.argv_proxy, {})
        self.assertEqual(findings.log_errors, [])


class TestCheckLaunchctlEnv(unittest.TestCase):
    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run")
    def test_present_env_vars(self, mock_run, _mock_system):
        def run_side_effect(cmd, timeout=5):
            if "http_proxy" in " ".join(cmd):
                return "http://127.0.0.1:7890"
            if "https_proxy" in " ".join(cmd):
                return "http://127.0.0.1:7890"
            return ""

        mock_run.side_effect = run_side_effect
        env, entries = check_launchctl_env()
        self.assertIn("http_proxy", env)
        self.assertEqual(env["http_proxy"], "http://127.0.0.1:7890")
        self.assertGreater(len(entries), 0)
        self.assertTrue(any(e.host == "127.0.0.1" for e in entries))

    @patch("proxy_doctor.core.platform.system", return_value="Darwin")
    @patch("proxy_doctor.core._run", return_value="")
    def test_no_env_vars_empty(self, _mock_run, _mock_system):
        env, entries = check_launchctl_env()
        self.assertEqual(env, {})
        self.assertEqual(entries, [])

    @patch("proxy_doctor.core.platform.system", return_value="Linux")
    def test_non_darwin_empty(self, _mock_system):
        env, entries = check_launchctl_env()
        self.assertEqual(env, {})
        self.assertEqual(entries, [])


class TestDiagnoseEdgeCases(unittest.TestCase):
    def _entry(self, host="127.0.0.1", port=10903, enabled=True, layer="system_proxy"):
        return ProxyEntry(layer, f"Wi-Fi ({layer})", "http", host, port, enabled)

    def test_multiple_dead_ports_takes_first(self):
        ev = LayerResults(
            system_proxies=[
                self._entry(port=10903),
                self._entry(port=10904),
            ],
            port_statuses=[
                PortStatus("127.0.0.1", 10903, "refused"),
                PortStatus("127.0.0.1", 10904, "refused"),
            ],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "A")
        self.assertIn("10903", d.root_cause)

    def test_active_proxy_residual_case_a_wins(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            residual_proxies=[self._entry(port=10904, enabled=False)],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "A")
        self.assertEqual(d.status, "unhealthy")

    def test_timeout_port_status(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "timeout")],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "C")
        self.assertEqual(d.status, "warning")

    def test_all_entries_port_zero_case_c(self):
        ev = LayerResults(
            system_proxies=[
                ProxyEntry("a", "s1", "http", "127.0.0.1", 0, True),
            ],
            port_statuses=[],
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "C")
        self.assertEqual(d.status, "warning")

    def test_err_http2_triggers_case_b(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "listening")],
            editor_config=EditorConfigFindings(
                log_errors=["[renderer.log] ERR_HTTP2_PROTOCOL_ERROR occurred"],
            ),
        )
        d = diagnose(ev)
        self.assertEqual(d.case, "B")
        self.assertEqual(d.status, "unhealthy")


class TestFixGenerators(unittest.TestCase):
    def _entry(self, host="127.0.0.1", port=10903, enabled=True, layer="system_proxy"):
        return ProxyEntry(layer, f"Wi-Fi ({layer})", "http", host, port, enabled)

    def test_case_a_networksetup_commands(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        fixes = _fixes_case_a(ev, PortStatus("127.0.0.1", 10903, "refused"), "cursor")
        networksetup_fixes = [f for f in fixes if "networksetup" in f.command]
        self.assertGreater(len(networksetup_fixes), 0)
        self.assertIn("-setwebproxystate", networksetup_fixes[0].command)
        self.assertIn("off", networksetup_fixes[0].command)

    def test_case_a_launchctl_unsetenv(self):
        ev = LayerResults(
            env_proxies=[
                ProxyEntry(
                    "launchctl_env",
                    "launchctl getenv http_proxy",
                    "http",
                    "127.0.0.1",
                    10903,
                    True,
                    raw="http_proxy=http://127.0.0.1:10903",
                ),
            ],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        fixes = _fixes_case_a(ev, PortStatus("127.0.0.1", 10903, "refused"), "cursor")
        launchctl_fixes = [f for f in fixes if "launchctl unsetenv" in f.command]
        self.assertGreater(len(launchctl_fixes), 0)
        self.assertIn("launchctl unsetenv http_proxy", launchctl_fixes[0].command)

    def test_case_a_restart_editor_always_present(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        fixes = _fixes_case_a(ev, PortStatus("127.0.0.1", 10903, "refused"), "cursor")
        restart_fixes = [f for f in fixes if f.fix_id == "restart-editor"]
        self.assertEqual(len(restart_fixes), 1)

    @patch("proxy_doctor.core.get_editor")
    def test_case_b_http2_disable_when_cursor_has_key(self, mock_get_editor):
        mock_get_editor.return_value = EditorPaths(
            name="Cursor",
            settings_json=None,
            argv_json=None,
            logs_dir=None,
            extra_keys=("cursor.general.disableHttp2",),
        )
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "listening")],
        )
        fixes = _fixes_case_b(
            ev, PortStatus("127.0.0.1", 10903, "listening"), "cursor"
        )
        h2_fixes = [f for f in fixes if f.fix_id == "disable-http2"]
        self.assertGreater(len(h2_fixes), 0)

    def test_case_c_residual_cleanup_commands(self):
        ev = LayerResults(
            residual_proxies=[self._entry(enabled=False)],
        )
        fixes = _fixes_case_c(ev, "cursor")
        residual_fixes = [f for f in fixes if "clear-residual" in f.fix_id]
        self.assertGreater(len(residual_fixes), 0)
        self.assertIn("-setwebproxystate", residual_fixes[0].command)

    def test_all_fixes_risk_valid(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        fixes = _fixes_case_a(ev, PortStatus("127.0.0.1", 10903, "refused"), "cursor")
        for f in fixes:
            self.assertIn(f.risk, ("low", "medium", "high"))

    def test_all_fixes_unique_id(self):
        ev = LayerResults(
            system_proxies=[self._entry()],
            env_proxies=[
                ProxyEntry(
                    "launchctl_env",
                    "launchctl getenv http_proxy",
                    "http",
                    "127.0.0.1",
                    10903,
                    True,
                    raw="http_proxy=http://127.0.0.1:10903",
                ),
            ],
            port_statuses=[PortStatus("127.0.0.1", 10903, "refused")],
        )
        fixes = _fixes_case_a(ev, PortStatus("127.0.0.1", 10903, "refused"), "cursor")
        ids = [f.fix_id for f in fixes]
        self.assertEqual(len(ids), len(set(ids)))


class TestProbePortEdge(unittest.TestCase):
    @patch("proxy_doctor.core.socket.create_connection")
    def test_socket_timeout_status_timeout(self, mock_connect):
        mock_connect.side_effect = socket.timeout("timed out")
        result = _probe_port("127.0.0.1", 7890)
        self.assertEqual(result.status, "timeout")

    @patch("proxy_doctor.core.socket.create_connection")
    def test_oserror_status_error(self, mock_connect):
        mock_connect.side_effect = OSError("Connection failed")
        result = _probe_port("127.0.0.1", 7890)
        self.assertEqual(result.status, "error")


if __name__ == "__main__":
    unittest.main()

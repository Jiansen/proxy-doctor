"""Tests for proxy_doctor.core — parsing, diagnosis logic, and port detection."""

from __future__ import annotations

import json
import socket
import unittest

from proxy_doctor.core import (
    Diagnosis,
    EditorConfigFindings,
    Fix,
    LayerResults,
    PortStatus,
    ProxyEntry,
    Report,
    _is_local_address,
    _parse_proxy_output,
    _parse_proxy_url,
    _probe_port,
    check_port_health,
    diagnose,
)


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


if __name__ == "__main__":
    unittest.main()

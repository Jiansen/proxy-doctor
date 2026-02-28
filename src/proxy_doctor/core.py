"""Core diagnostic engine for proxy-doctor.

Zero external dependencies — uses only Python stdlib.
Checks 5 layers of proxy configuration on macOS and produces
a structured diagnosis with ranked remediation steps.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any

from proxy_doctor.editors import EditorPaths, get_editor

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ProxyEntry:
    """A single proxy reference found in any layer."""

    layer: str
    source: str
    protocol: str
    host: str
    port: int
    enabled: bool
    raw: str = ""


@dataclass
class PortStatus:
    host: str
    port: int
    status: str  # "listening" | "refused" | "timeout" | "error"
    detail: str = ""


@dataclass
class EditorConfigFindings:
    settings_proxy: dict[str, Any] = field(default_factory=dict)
    argv_proxy: dict[str, str] = field(default_factory=dict)
    log_errors: list[str] = field(default_factory=list)


@dataclass
class LayerResults:
    system_proxies: list[ProxyEntry] = field(default_factory=list)
    residual_proxies: list[ProxyEntry] = field(default_factory=list)
    port_statuses: list[PortStatus] = field(default_factory=list)
    editor_config: EditorConfigFindings = field(default_factory=EditorConfigFindings)
    launchctl_env: dict[str, str] = field(default_factory=dict)
    env_proxies: list[ProxyEntry] = field(default_factory=list)


@dataclass
class Fix:
    fix_id: str
    description: str
    command: str
    risk: str  # "low" | "medium" | "high"
    layer: str


@dataclass
class Diagnosis:
    status: str  # "healthy" | "unhealthy" | "warning"
    case: str  # "A" | "B" | "C" | "clean"
    root_cause: str
    confidence: str  # "high" | "medium" | "low"
    source: str
    browser_explanation: str
    fixes: list[Fix] = field(default_factory=list)


@dataclass
class Report:
    diagnosis: Diagnosis
    evidence: LayerResults
    editor: str
    platform: str
    version: str = "0.2.1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "editor": self.editor,
            "platform": self.platform,
            "status": self.diagnosis.status,
            "diagnosis": {
                "case": self.diagnosis.case,
                "root_cause": self.diagnosis.root_cause,
                "confidence": self.diagnosis.confidence,
                "source": self.diagnosis.source,
                "browser_explanation": self.diagnosis.browser_explanation,
            },
            "fixes": [asdict(f) for f in self.diagnosis.fixes],
            "evidence": _evidence_to_dict(self.evidence),
            "feedback": {
                "report_issue": "https://github.com/Jiansen/proxy-doctor/issues/new",
                "hint": "Include this JSON output when reporting issues.",
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    def to_human(self) -> str:
        d = self.diagnosis
        lines = [
            f"proxy-doctor v{self.version}",
            f"Editor: {self.editor} | Platform: {self.platform}",
            "",
            f"Status: {d.status.upper()}",
        ]
        if d.case != "clean":
            lines += [
                f"Root Cause: {d.root_cause}",
                f"Confidence: {d.confidence.capitalize()}",
                f"Source: {d.source}",
                "",
                "Why browser may still work:",
                f"  {d.browser_explanation}",
            ]
        if d.fixes:
            lines += ["", "Recommended fixes (lowest risk first):"]
            for i, f in enumerate(d.fixes, 1):
                lines.append(f"  {i}. [{f.risk}] {f.description}")
                if f.command:
                    lines.append(f"     $ {f.command}")
        if d.case == "clean":
            lines += ["", "No proxy contamination detected."]
        return "\n".join(lines)


def _evidence_to_dict(ev: LayerResults) -> dict[str, Any]:
    return {
        "system_proxies": [asdict(p) for p in ev.system_proxies],
        "residual_proxies": [asdict(p) for p in ev.residual_proxies],
        "port_statuses": [asdict(p) for p in ev.port_statuses],
        "editor_config": asdict(ev.editor_config),
        "launchctl_env": ev.launchctl_env,
        "env_proxies": [asdict(p) for p in ev.env_proxies],
    }


# ---------------------------------------------------------------------------
# Layer 1: System proxy state (macOS networksetup)
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: int = 5) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _list_network_services() -> list[str]:
    out = _run(["networksetup", "-listallnetworkservices"])
    services = []
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("An asterisk"):
            services.append(line)
    return services


def _parse_proxy_output(output: str) -> dict[str, str]:
    """Parse networksetup proxy output into key-value pairs."""
    result: dict[str, str] = {}
    for line in output.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


_PROXY_CHECKS = [
    ("-getwebproxy", "http"),
    ("-getsecurewebproxy", "https"),
    ("-getsocksfirewallproxy", "socks"),
]


def check_system_proxy() -> tuple[list[ProxyEntry], list[ProxyEntry]]:
    """Layer 1+2: Check system proxy settings across all network services.

    Returns (active_proxies, residual_proxies).
    """
    if platform.system() != "Darwin":
        return [], []

    active: list[ProxyEntry] = []
    residual: list[ProxyEntry] = []
    services = _list_network_services()

    for svc in services:
        for flag, protocol in _PROXY_CHECKS:
            out = _run(["networksetup", flag, svc])
            parsed = _parse_proxy_output(out)
            server = parsed.get("Server", "").strip()
            port_str = parsed.get("Port", "0").strip()
            enabled_str = parsed.get("Enabled", "No").strip()
            enabled = enabled_str.lower() == "yes"

            if not server or server == "(null)":
                continue

            try:
                port = int(port_str)
            except ValueError:
                port = 0

            entry = ProxyEntry(
                layer="system_proxy",
                source=f"{svc} ({protocol})",
                protocol=protocol,
                host=server,
                port=port,
                enabled=enabled,
                raw=out.strip(),
            )

            if enabled:
                active.append(entry)
            elif _is_local_address(server):
                residual.append(entry)

        # Auto proxy URL
        out = _run(["networksetup", "-getautoproxyurl", svc])
        parsed = _parse_proxy_output(out)
        url = parsed.get("URL", "").strip()
        enabled_str = parsed.get("Enabled", "No").strip()
        if url and url != "(null)":
            entry = ProxyEntry(
                layer="system_proxy",
                source=f"{svc} (pac)",
                protocol="pac",
                host=url,
                port=0,
                enabled=enabled_str.lower() == "yes",
                raw=out.strip(),
            )
            if entry.enabled:
                active.append(entry)

    return active, residual


def _is_local_address(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


# ---------------------------------------------------------------------------
# Layer 3: Port health
# ---------------------------------------------------------------------------

def check_port_health(entries: list[ProxyEntry]) -> list[PortStatus]:
    """Test whether referenced proxy ports are actually listening."""
    seen: set[tuple[str, int]] = set()
    results: list[PortStatus] = []

    for entry in entries:
        if entry.protocol == "pac":
            continue
        key = (entry.host, entry.port)
        if key in seen or entry.port == 0:
            continue
        seen.add(key)

        status = _probe_port(entry.host, entry.port)
        results.append(status)

    return results


def _probe_port(host: str, port: int, timeout: float = 3.0) -> PortStatus:
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return PortStatus(host=host, port=port, status="listening")
    except ConnectionRefusedError:
        return PortStatus(
            host=host, port=port, status="refused",
            detail="No process is listening on this port",
        )
    except socket.timeout:
        return PortStatus(
            host=host, port=port, status="timeout",
            detail="Connection timed out (possible firewall or unreachable host)",
        )
    except OSError as e:
        return PortStatus(
            host=host, port=port, status="error",
            detail=str(e),
        )


# ---------------------------------------------------------------------------
# Layer 4: Editor config
# ---------------------------------------------------------------------------

def check_editor_config(editor: EditorPaths) -> EditorConfigFindings:
    """Read editor settings/argv for proxy configuration."""
    findings = EditorConfigFindings()

    # settings.json
    if editor.settings_json and editor.settings_json.exists():
        try:
            data = json.loads(editor.settings_json.read_text(encoding="utf-8"))
            all_keys = list(editor.proxy_keys) + list(editor.extra_keys)
            for key in all_keys:
                if key in data:
                    findings.settings_proxy[key] = data[key]
        except (json.JSONDecodeError, OSError):
            pass

    # argv.json
    if editor.argv_json and editor.argv_json.exists():
        try:
            data = json.loads(editor.argv_json.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for flag in editor.argv_proxy_flags:
                    clean = flag.lstrip("-").replace("-", "_")
                    for variant in (flag, clean, flag.lstrip("-")):
                        if variant in data:
                            findings.argv_proxy[flag] = str(data[variant])
        except (json.JSONDecodeError, OSError):
            pass

    # Recent log errors
    if editor.logs_dir and editor.logs_dir.exists():
        findings.log_errors = _scan_editor_logs(editor)

    return findings


def _scan_editor_logs(editor: EditorPaths, max_files: int = 5, max_lines: int = 500) -> list[str]:
    """Scan recent log files for proxy-related error patterns."""
    errors: list[str] = []
    if not editor.logs_dir or not editor.logs_dir.exists():
        return errors

    log_files = sorted(
        editor.logs_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
    )

    for log_file in log_files[:max_files]:
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
            for line in lines[-max_lines:]:
                for pattern in editor.log_error_patterns:
                    if pattern in line:
                        snippet = line.strip()[:200]
                        errors.append(f"[{log_file.name}] {snippet}")
                        break
        except OSError:
            continue

    return errors[:20]


# ---------------------------------------------------------------------------
# Layer 5: GUI app environment (launchctl)
# ---------------------------------------------------------------------------

_ENV_VARS = (
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY",
)


def check_launchctl_env() -> tuple[dict[str, str], list[ProxyEntry]]:
    """Check launchctl environment for proxy variables.

    Returns (env_dict, proxy_entries_extracted).
    """
    env: dict[str, str] = {}
    entries: list[ProxyEntry] = []

    if platform.system() != "Darwin":
        return env, entries

    for var in _ENV_VARS:
        out = _run(["launchctl", "getenv", var])
        val = out.strip()
        if val:
            env[var] = val
            host, port = _parse_proxy_url(val)
            if host:
                entries.append(ProxyEntry(
                    layer="launchctl_env",
                    source=f"launchctl getenv {var}",
                    protocol="http" if "http" in var.lower() else "all",
                    host=host,
                    port=port,
                    enabled=True,
                    raw=f"{var}={val}",
                ))

    return env, entries


_PROXY_URL_RE = re.compile(
    r"(?:https?|socks[45]?)://(?:[^@]+@)?([^:/]+)(?::(\d+))?",
    re.IGNORECASE,
)


def _parse_proxy_url(url: str) -> tuple[str, int]:
    """Extract host and port from a proxy URL."""
    m = _PROXY_URL_RE.match(url)
    if m:
        host = m.group(1)
        port = int(m.group(2)) if m.group(2) else 0
        return host, port
    # Bare host:port
    if ":" in url and not url.startswith("/"):
        parts = url.rsplit(":", 1)
        try:
            return parts[0], int(parts[1])
        except (ValueError, IndexError):
            pass
    return "", 0


# ---------------------------------------------------------------------------
# Diagnosis engine
# ---------------------------------------------------------------------------

def collect_evidence(editor_name: str = "cursor") -> LayerResults:
    """Run all 5 layers and return raw evidence."""
    editor = get_editor(editor_name)
    results = LayerResults()

    # Layer 1+2: System proxy
    active, residual = check_system_proxy()
    results.system_proxies = active
    results.residual_proxies = residual

    # Layer 4: Editor config
    if editor:
        results.editor_config = check_editor_config(editor)

    # Layer 5: launchctl env
    env_dict, env_proxies = check_launchctl_env()
    results.launchctl_env = env_dict
    results.env_proxies = env_proxies

    # Layer 3: Port health — probe all discovered proxy endpoints
    all_proxy_entries = active + residual + env_proxies
    # Also extract from editor config
    if editor:
        for key, val in results.editor_config.settings_proxy.items():
            if isinstance(val, str) and (":" in val or "//" in val):
                host, port = _parse_proxy_url(val)
                if host:
                    all_proxy_entries.append(ProxyEntry(
                        layer="editor_config",
                        source=f"settings.json [{key}]",
                        protocol="http",
                        host=host,
                        port=port,
                        enabled=True,
                    ))
        for flag, val in results.editor_config.argv_proxy.items():
            host, port = _parse_proxy_url(val)
            if host:
                all_proxy_entries.append(ProxyEntry(
                    layer="editor_config",
                    source=f"argv.json [{flag}]",
                    protocol="http",
                    host=host,
                    port=port,
                    enabled=True,
                ))

    results.port_statuses = check_port_health(all_proxy_entries)

    return results


def diagnose(evidence: LayerResults, editor_name: str = "cursor") -> Diagnosis:
    """Analyze evidence and produce a diagnosis."""
    all_entries = (
        evidence.system_proxies
        + evidence.residual_proxies
        + evidence.env_proxies
    )
    dead_ports = [p for p in evidence.port_statuses if p.status == "refused"]
    live_ports = [p for p in evidence.port_statuses if p.status == "listening"]

    has_proxy_ref = len(all_entries) > 0
    has_dead_port = len(dead_ports) > 0
    has_live_port = len(live_ports) > 0
    has_log_errors = len(evidence.editor_config.log_errors) > 0
    has_buffering = any(
        "buffered" in e.lower() or "ERR_HTTP2" in e
        for e in evidence.editor_config.log_errors
    )
    has_residual = len(evidence.residual_proxies) > 0

    # Case A: Proxy reference exists but port is dead
    if has_proxy_ref and has_dead_port:
        dead = dead_ports[0]
        sources = _identify_sources(evidence, dead.host, dead.port)
        return Diagnosis(
            status="unhealthy",
            case="A",
            root_cause=(
                f"Editor is configured to use proxy at {dead.host}:{dead.port}, "
                f"but no process is listening on that port."
            ),
            confidence="high",
            source=", ".join(sources),
            browser_explanation=(
                "Browser may use a different proxy path (e.g. browser-only mode) "
                "or fall back to a direct connection."
            ),
            fixes=_fixes_case_a(evidence, dead, editor_name),
        )

    # Case B: Proxy port alive, but streaming issues
    if has_proxy_ref and has_live_port and (has_buffering or has_log_errors):
        live = live_ports[0]
        return Diagnosis(
            status="unhealthy",
            case="B",
            root_cause=(
                f"Proxy at {live.host}:{live.port} is running, but streaming/SSE connections "
                f"appear to be buffered or interrupted."
            ),
            confidence="medium",
            source="editor_logs + proxy_config",
            browser_explanation=(
                "Browser uses standard HTTP request-response which proxies handle well. "
                "AI editors require long-lived streaming (SSE) connections that some "
                "proxy configurations buffer or break."
            ),
            fixes=_fixes_case_b(evidence, live, editor_name),
        )

    # Case C: Residual proxy values or env mismatch
    if has_residual or (has_proxy_ref and not has_dead_port and not has_live_port):
        return Diagnosis(
            status="warning",
            case="C",
            root_cause=(
                "Residual proxy configuration detected. System proxy may be disabled "
                "but stale values remain, or proxy environment variables point to "
                "a different path than the system proxy."
            ),
            confidence="medium",
            source="residual_config",
            browser_explanation=(
                "Browser respects the 'Enabled' flag and ignores residual values. "
                "Some Electron apps may still pick up stale proxy addresses."
            ),
            fixes=_fixes_case_c(evidence, editor_name),
        )

    # Case: Log errors but no proxy detected — could be transient
    if has_log_errors and not has_proxy_ref:
        return Diagnosis(
            status="warning",
            case="C",
            root_cause=(
                "Proxy-related errors found in editor logs, but no active proxy "
                "configuration detected. This may indicate a recently cleared proxy "
                "or intermittent issue."
            ),
            confidence="low",
            source="editor_logs",
            browser_explanation="No active proxy mismatch detected.",
            fixes=[Fix(
                fix_id="restart-editor",
                description=f"Restart {editor_name}",
                command="",
                risk="low",
                layer="editor",
            )],
        )

    # Clean
    return Diagnosis(
        status="healthy",
        case="clean",
        root_cause="No proxy contamination detected.",
        confidence="high",
        source="all_layers",
        browser_explanation="",
    )


def _identify_sources(evidence: LayerResults, host: str, port: int) -> list[str]:
    sources: list[str] = []
    for e in evidence.system_proxies + evidence.residual_proxies:
        if e.host == host and e.port == port:
            sources.append(f"system proxy ({e.source})")
    for e in evidence.env_proxies:
        if e.host == host and e.port == port:
            sources.append(f"launchctl env ({e.source})")
    ec = evidence.editor_config
    for key, val in ec.settings_proxy.items():
        if isinstance(val, str) and host in val and str(port) in val:
            sources.append(f"editor settings.json [{key}]")
    for flag, val in ec.argv_proxy.items():
        if host in val and str(port) in val:
            sources.append(f"editor argv.json [{flag}]")
    return sources or ["unknown"]


# ---------------------------------------------------------------------------
# Fix generators
# ---------------------------------------------------------------------------

def _fixes_case_a(evidence: LayerResults, dead: PortStatus, editor_name: str) -> list[Fix]:
    fixes: list[Fix] = []

    # Clear system proxy for affected services
    for entry in evidence.system_proxies:
        if entry.host == dead.host and entry.port == dead.port:
            svc = entry.source.split(" (")[0]
            proto_flag = {
                "http": "-setwebproxystate",
                "https": "-setsecurewebproxystate",
                "socks": "-setsocksfirewallproxystate",
            }.get(entry.protocol, "-setwebproxystate")
            fixes.append(Fix(
                fix_id=f"clear-system-{entry.protocol}-{svc.lower().replace(' ', '-')}",
                description=f"Disable {entry.protocol} proxy on {svc}",
                command=f'networksetup {proto_flag} "{svc}" off',
                risk="low",
                layer="system_proxy",
            ))

    # Clear launchctl env
    for entry in evidence.env_proxies:
        if entry.host == dead.host and entry.port == dead.port:
            var = entry.raw.split("=")[0] if "=" in entry.raw else ""
            if var:
                fixes.append(Fix(
                    fix_id=f"unset-launchctl-{var}",
                    description=f"Unset {var} from GUI environment",
                    command=f"launchctl unsetenv {var}",
                    risk="low",
                    layer="launchctl_env",
                ))

    # Clear editor proxy settings
    ec = evidence.editor_config
    for key, val in ec.settings_proxy.items():
        if isinstance(val, str) and dead.host in val:
            fixes.append(Fix(
                fix_id=f"remove-editor-setting-{key.replace('.', '-')}",
                description=f"Remove {key} from editor settings.json",
                command=f"(open editor settings and delete the \"{key}\" line)",
                risk="low",
                layer="editor_config",
            ))

    # Restart editor
    fixes.append(Fix(
        fix_id="restart-editor",
        description=f"Restart {editor_name}",
        command="",
        risk="low",
        layer="editor",
    ))

    return fixes


def _fixes_case_b(evidence: LayerResults, live: PortStatus, editor_name: str) -> list[Fix]:
    fixes: list[Fix] = []

    editor = get_editor(editor_name)
    disable_h2_key = None
    if editor:
        for k in editor.extra_keys:
            if "Http2" in k or "http2" in k:
                disable_h2_key = k
                break

    if disable_h2_key:
        current = evidence.editor_config.settings_proxy.get(disable_h2_key)
        if current is not True:
            fixes.append(Fix(
                fix_id="disable-http2",
                description="Disable HTTP/2 in editor settings (may help with buffered streams)",
                command=f'(add "{disable_h2_key}": true to editor settings.json)',
                risk="low",
                layer="editor_config",
            ))

    fixes.append(Fix(
        fix_id="switch-full-tunnel",
        description=(
            "Switch your network tool to full-tunnel/global mode "
            "instead of browser-only mode"
        ),
        command="",
        risk="medium",
        layer="external",
    ))

    fixes.append(Fix(
        fix_id="bypass-proxy-for-editor",
        description=f"Configure proxy bypass for {editor_name} AI endpoints",
        command="",
        risk="medium",
        layer="external",
    ))

    return fixes


def _fixes_case_c(evidence: LayerResults, editor_name: str) -> list[Fix]:
    fixes: list[Fix] = []

    for entry in evidence.residual_proxies:
        svc = entry.source.split(" (")[0]
        proto_flag = {
            "http": "-setwebproxy",
            "https": "-setsecurewebproxy",
            "socks": "-setsocksfirewallproxy",
        }.get(entry.protocol, "-setwebproxy")
        # Clear residual by setting to empty and disabling
        state_flag = proto_flag + "state"
        fixes.append(Fix(
            fix_id=f"clear-residual-{entry.protocol}-{svc.lower().replace(' ', '-')}",
            description=(
                f"Clear residual {entry.protocol} proxy on {svc} "
                f"(disabled but address still set)"
            ),
            command=f'networksetup {state_flag} "{svc}" off',
            risk="low",
            layer="system_proxy",
        ))

    for var in evidence.launchctl_env:
        fixes.append(Fix(
            fix_id=f"unset-launchctl-{var}",
            description=f"Unset {var} from GUI environment",
            command=f"launchctl unsetenv {var}",
            risk="low",
            layer="launchctl_env",
        ))

    fixes.append(Fix(
        fix_id="restart-editor",
        description=f"Restart {editor_name}",
        command="",
        risk="low",
        layer="editor",
    ))

    return fixes


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_diagnosis(editor_name: str = "cursor") -> Report:
    """Run full diagnosis and return a complete report."""
    evidence = collect_evidence(editor_name)
    diag = diagnose(evidence, editor_name)
    return Report(
        diagnosis=diag,
        evidence=evidence,
        editor=editor_name,
        platform=platform.system(),
    )

"""Editor configuration path registry.

Maps AI coding editors to their config/log paths on each platform.
MVP: Cursor on macOS. Extensible to VS Code, Windsurf, etc.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EditorPaths:
    name: str
    settings_json: Path | None = None
    argv_json: Path | None = None
    logs_dir: Path | None = None
    proxy_keys: tuple[str, ...] = field(default_factory=lambda: (
        "http.proxy",
        "http.proxySupport",
        "http.proxyStrictSSL",
    ))
    extra_keys: tuple[str, ...] = ()
    argv_proxy_flags: tuple[str, ...] = (
        "--proxy-server",
        "--proxy-pac-url",
        "--proxy-bypass-list",
    )
    log_error_patterns: tuple[str, ...] = (
        "Failed to establish a socket connection to proxies",
        "Streaming responses are being buffered",
        "PROXY 127.0.0.1",
        "ERR_HTTP2_PROTOCOL_ERROR",
        "ERR_PROXY_CONNECTION_FAILED",
    )


def _home() -> Path:
    return Path.home()


def _macos_app_support() -> Path:
    return _home() / "Library" / "Application Support"


_EDITORS_MACOS: dict[str, EditorPaths] = {
    "cursor": EditorPaths(
        name="Cursor",
        settings_json=_macos_app_support() / "Cursor" / "User" / "settings.json",
        argv_json=_macos_app_support() / "Cursor" / "User" / "argv.json",
        logs_dir=_macos_app_support() / "Cursor" / "logs",
        extra_keys=("cursor.general.disableHttp2",),
    ),
    "vscode": EditorPaths(
        name="VS Code",
        settings_json=_macos_app_support() / "Code" / "User" / "settings.json",
        argv_json=_macos_app_support() / "Code" / "User" / "argv.json",
        logs_dir=_macos_app_support() / "Code" / "logs",
    ),
    "windsurf": EditorPaths(
        name="Windsurf",
        settings_json=_macos_app_support() / "Windsurf" / "User" / "settings.json",
        argv_json=_macos_app_support() / "Windsurf" / "User" / "argv.json",
        logs_dir=_macos_app_support() / "Windsurf" / "logs",
    ),
}

_EDITORS_LINUX: dict[str, EditorPaths] = {
    "cursor": EditorPaths(
        name="Cursor",
        settings_json=_home() / ".config" / "Cursor" / "User" / "settings.json",
        logs_dir=_home() / ".config" / "Cursor" / "logs",
    ),
    "vscode": EditorPaths(
        name="VS Code",
        settings_json=_home() / ".config" / "Code" / "User" / "settings.json",
        logs_dir=_home() / ".config" / "Code" / "logs",
    ),
}


def get_editor(name: str) -> EditorPaths | None:
    """Return editor paths for the current platform, or None if unsupported."""
    system = platform.system()
    if system == "Darwin":
        return _EDITORS_MACOS.get(name.lower())
    if system == "Linux":
        return _EDITORS_LINUX.get(name.lower())
    return None


def list_editors() -> list[str]:
    """Return names of editors supported on the current platform."""
    system = platform.system()
    if system == "Darwin":
        return list(_EDITORS_MACOS.keys())
    if system == "Linux":
        return list(_EDITORS_LINUX.keys())
    return []

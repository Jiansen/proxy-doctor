"""MCP Server for proxy-doctor.

Exposes proxy diagnostic capabilities as MCP tools that AI agents can call.

Usage:
    # Run as standalone MCP server (stdio transport)
    python -m proxy_doctor.mcp_server

    # Or via fastmcp CLI
    fastmcp run proxy_doctor.mcp_server:mcp
"""

from __future__ import annotations

try:
    from fastmcp import FastMCP
except ImportError:
    raise ImportError(
        "MCP server requires fastmcp. Install with: pip install proxy-doctor[mcp]"
    )

from proxy_doctor.core import run_diagnosis
from proxy_doctor.editors import list_editors

mcp = FastMCP(
    "proxy-doctor",
    instructions=(
        "Diagnose proxy misconfigurations that break AI coding tools. "
        "Checks system proxy settings, residual proxy values, port health, "
        "editor configuration, and GUI environment variables."
    ),
)


@mcp.tool()
def diagnose_proxy(editor: str = "cursor") -> dict:
    """Run a full proxy diagnostic for an AI coding editor.

    Checks 5 layers:
    1. System proxy state (macOS networksetup)
    2. Residual proxy values (disabled but still set)
    3. Port health (is the proxy actually listening?)
    4. Editor config (settings.json, argv.json, recent logs)
    5. GUI app environment (launchctl proxy env vars)

    Returns a structured report with:
    - status: "healthy", "unhealthy", or "warning"
    - diagnosis: root cause, confidence level, and explanation
    - fixes: ranked remediation steps (lowest risk first)
    - evidence: raw data from each layer

    Args:
        editor: Editor to diagnose. Options: cursor, vscode, windsurf. Default: cursor.
    """
    report = run_diagnosis(editor)
    return report.to_dict()


@mcp.tool()
def list_fixes(editor: str = "cursor") -> dict:
    """Get recommended fixes for proxy issues affecting an AI editor.

    Returns only the diagnosis summary and fix list, without full evidence.
    Each fix includes a command to run and its risk level.

    Args:
        editor: Editor to diagnose. Options: cursor, vscode, windsurf. Default: cursor.
    """
    report = run_diagnosis(editor)
    return {
        "status": report.diagnosis.status,
        "case": report.diagnosis.case,
        "root_cause": report.diagnosis.root_cause,
        "fixes": [
            {
                "fix_id": f.fix_id,
                "description": f.description,
                "command": f.command,
                "risk": f.risk,
                "layer": f.layer,
            }
            for f in report.diagnosis.fixes
        ],
    }


@mcp.tool()
def supported_editors() -> dict:
    """List AI coding editors supported by proxy-doctor on this platform."""
    return {"supported_editors": list_editors()}


if __name__ == "__main__":
    mcp.run()

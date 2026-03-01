<p align="center">
  <img src="assets/logo.svg" width="120" alt="proxy-doctor logo">
</p>

<h1 align="center">proxy-doctor</h1>

<p align="center">
  <a href="https://pypi.org/project/proxy-doctor/"><img src="https://img.shields.io/pypi/v/proxy-doctor" alt="PyPI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Jiansen/proxy-doctor" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-macOS-blue" alt="Platform">
  <img src="https://img.shields.io/badge/python-%3E%3D3.9-blue" alt="Python">
  <a href="https://github.com/Jiansen/proxy-doctor/stargazers"><img src="https://img.shields.io/github/stars/Jiansen/proxy-doctor?style=social" alt="GitHub Stars"></a>
</p>

**Diagnose proxy misconfigurations that break AI coding tools.**

When your browser works fine but Cursor / VS Code / Windsurf AI features don't — proxy-doctor tells you exactly why and how to fix it.

## The Problem

AI coding tools (Cursor, VS Code with Copilot, Windsurf) rely on long-lived streaming connections (SSE/HTTP2) that break when:

- Your system proxy points to a localhost port where nothing is listening
- A VPN/proxy app was closed but its settings linger in macOS system preferences
- Your editor inherited stale proxy environment variables from `launchctl`
- The proxy is running but buffers streaming responses, breaking AI completions

The result: **"browser works, AI editor doesn't"** — the most common and frustrating developer experience.

## What It Checks

proxy-doctor inspects 5 layers of your macOS proxy configuration:

| Layer | What | How |
|-------|------|-----|
| 1. System Proxy | Web/HTTPS/SOCKS proxy across all network services | `networksetup` |
| 2. Residual Values | Disabled proxies with stale localhost addresses | Parse disabled-but-set entries |
| 3. Port Health | Whether referenced proxy ports are actually listening | `socket.connect()` |
| 4. Editor Config | `settings.json`, `argv.json`, recent error logs | File read + pattern match |
| 5. GUI Environment | `http_proxy`/`https_proxy` in GUI app context | `launchctl getenv` |

## Quick Start

### CLI

```bash
# Install
pip install proxy-doctor

# Run diagnosis (JSON output — default, optimized for AI agents)
proxy-doctor check

# Run diagnosis (human-readable output)
proxy-doctor check --human

# Show recommended fixes
proxy-doctor fix

# Check a different editor
proxy-doctor check --editor vscode
```

### As an MCP Tool (for AI agents)

proxy-doctor ships as an MCP server that AI agents can call directly:

```bash
# Install with MCP support
pip install proxy-doctor[mcp]

# Run MCP server
python -m proxy_doctor.mcp_server
```

Add to your MCP configuration (e.g., Cursor `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "proxy-doctor": {
      "command": "python3",
      "args": ["-m", "proxy_doctor.mcp_server"]
    }
  }
}
```

> **Note:** `"command"` must point to the Python where `proxy-doctor[mcp]` is installed. If `python3` doesn't work, use the full path (run `which python3` or `python3 -c "import sys; print(sys.executable)"` to find it).

Your AI agent can then call:
- `diagnose_proxy(editor="cursor")` — full 5-layer diagnosis with evidence
- `list_fixes(editor="cursor")` — recommended fixes with executable commands
- `supported_editors()` — list available editors

### For AI Agents: Quick Install

**One-liner** (paste this to your AI agent):

> Install proxy-doctor (`pip install proxy-doctor[mcp]`) and add it to your MCP config with command `python -m proxy_doctor.mcp_server`. Then use the `diagnose_proxy` tool to check proxy health.

If you are an AI agent setting up proxy-doctor for your user:

```bash
# 1. Install
pip install proxy-doctor[mcp]

# 2. Find the Python path
python3 -c "import sys; print(sys.executable)"

# 3. Add to ~/.cursor/mcp.json (use the path from step 2)
# {
#   "mcpServers": {
#     "proxy-doctor": {
#       "command": "<python-path-from-step-2>",
#       "args": ["-m", "proxy_doctor.mcp_server"]
#     }
#   }
# }

# 4. If MCP is not available, use CLI directly (zero dependencies):
proxy-doctor check          # JSON output
proxy-doctor check --human  # human-readable
proxy-doctor fix            # show fixes (read-only)
proxy-doctor fix --apply    # apply fixes (asks for confirmation)
```

### Daemon Mode (v0.2+)

Run proxy-doctor as a persistent background service with automatic health monitoring:

```bash
# Start daemon (installs as macOS launchd service)
proxy-doctor daemon start

# Check daemon status
proxy-doctor daemon status

# Stop daemon
proxy-doctor daemon stop

# Check for updates
proxy-doctor update
```

The daemon runs every 5 minutes, compares results with the previous check, and sends a macOS notification when status changes (e.g. healthy → unhealthy).

### Menu Bar (SwiftBar)

```bash
# If SwiftBar is installed
cp plugins/swiftbar/proxy-doctor.5m.sh ~/Library/Application\ Support/SwiftBar/Plugins/
chmod +x ~/Library/Application\ Support/SwiftBar/Plugins/proxy-doctor.5m.sh
```

Shows a green/red/orange indicator in your menu bar with one-click diagnosis.

## Example Output

### Unhealthy (Case A: dead proxy port)

```json
{
  "status": "unhealthy",
  "diagnosis": {
    "case": "A",
    "root_cause": "Editor is configured to use proxy at 127.0.0.1:10903, but no process is listening on that port.",
    "confidence": "high",
    "source": "system proxy (Wi-Fi (http))",
    "browser_explanation": "Browser may use a different proxy path (e.g. browser-only mode) or fall back to a direct connection."
  },
  "fixes": [
    {
      "fix_id": "clear-system-http-wi-fi",
      "description": "Disable http proxy on Wi-Fi",
      "command": "networksetup -setwebproxystate \"Wi-Fi\" off",
      "risk": "low"
    }
  ]
}
```

### Healthy

```
proxy-doctor v0.2.0
Editor: cursor | Platform: Darwin

Status: HEALTHY

No proxy contamination detected.
```

## Supported Editors

| Editor | Config Detection | Log Scanning | Status |
|--------|-----------------|-------------|--------|
| Cursor | yes | yes | **supported** |
| VS Code | yes | yes | supported |
| Windsurf | yes | yes | supported |
| Claude Desktop | planned | — | future |
| Zed | planned | planned | future |

## How It Works

proxy-doctor identifies three failure patterns:

**Case A — Dead proxy port (high confidence):** Your system or editor points to `127.0.0.1:port` but nothing is listening. This happens when a VPN/proxy app is closed but its settings remain.

**Case B — Streaming broken (medium confidence):** A proxy is running, but it buffers SSE/streaming connections that AI editors depend on. Common with browser-only proxy modes.

**Case C — Path mismatch (medium confidence):** Browser and editor use different proxy paths. Browser works via a dedicated proxy route; editor inherits a stale or incompatible one.

## Platform Support

- **macOS**: Full support (system proxy, launchctl, networksetup)
- **Linux**: Partial (editor config + environment variables; no networksetup)
- **Windows**: Not yet supported

## Trust & Permissions

proxy-doctor follows a **read-only by default** design. No system changes are made unless you explicitly opt in.

### Default Behavior (read-only)

| Access | What | Why |
|--------|------|-----|
| **Reads** | System proxy settings, editor config files, launchctl env vars, local port status | Core diagnostic functionality |
| **Writes** | `~/.proxy-doctor/` only (cache, logs, update state) | Daemon state persistence |
| **Network** | `pypi.org` (version check only) | Auto-update feature |
| **Does NOT** | Modify proxy settings, change editor config, send telemetry, access credentials | By design |

### Opt-in Fix Application

`proxy-doctor fix` shows the recommended commands but **does not execute them**.

To apply fixes, use `proxy-doctor fix --apply`:
- Each fix is shown with its command and risk level
- You are prompted **individually** for each fix (`[y/N]`)
- Default is **No** — nothing runs unless you type `y`
- You can abort at any time with Ctrl+C

This two-step model lets AI agents safely call `list_fixes()` via MCP to see what needs fixing, then present the commands to users for approval.

## Feedback

Found a bug? Have a suggestion? Diagnosis didn't help?

- **GitHub Issues**: https://github.com/Jiansen/proxy-doctor/issues/new
- **For AI agents**: The JSON output includes a `feedback.report_issue` URL — include the full JSON when filing issues.

For AI agents providing feedback programmatically (zero dependencies):

```bash
# Create a GitHub issue via CLI (requires gh)
proxy-doctor check | gh issue create --repo Jiansen/proxy-doctor \
  --title "Diagnosis report: [describe issue]" --body-file -

# Or simply: copy the JSON output into a new issue at
# https://github.com/Jiansen/proxy-doctor/issues/new
```

## Development

```bash
git clone https://github.com/Jiansen/proxy-doctor.git
cd proxy-doctor

# Install in development mode
pip install -e ".[dev,mcp]"

# Run tests
make test

# Run linter
make lint
```

---

If proxy-doctor helped you fix a proxy issue, consider giving it a star on GitHub — it helps others discover the tool.

[![Star on GitHub](https://img.shields.io/github/stars/Jiansen/proxy-doctor?style=social)](https://github.com/Jiansen/proxy-doctor)

## License

MIT

<!-- mcp-name: io.github.Jiansen/proxy-doctor -->

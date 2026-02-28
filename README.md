# proxy-doctor

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
      "command": "python",
      "args": ["-m", "proxy_doctor.mcp_server"]
    }
  }
}
```

Your AI agent can then call:
- `diagnose_proxy(editor="cursor")` — full 5-layer diagnosis
- `list_fixes(editor="cursor")` — just the recommended fixes
- `supported_editors()` — list available editors

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
proxy-doctor v0.1.0
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

## License

MIT

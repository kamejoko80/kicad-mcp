# kicad-mcp

Kicad MCP server for HW design review and report

# Setup

```
uv sync
uv run python src/server.py
```

On windows powershell, to kill the MCP server:

```
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8500).OwningProcess -Force
```

Add MCP server:

```
{
  "mcpServers": {
    "kicad-hardware-agent": {
      "url": "http://localhost:8500/mcp"
    }
  }
}
```

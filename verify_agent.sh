#!/usr/bin/env bash

TARGET_DIR="D:\\Workspace\\HW\\KiCad\\Projects\\kicad_hw_design\\cardinal_bes2800_rev2.0"

echo "=== STEP 1: Handshaking with MCP Server ==="
curl -s -D headers.txt -X POST http://localhost:8500/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "verify-script", "version": "1.0"}}}' > /dev/null

SESSION_ID=$(grep -Fi "mcp-session-id:" headers.txt | awk '{print $2}' | tr -d '\r')
rm headers.txt

if [ -z "$SESSION_ID" ]; then
    echo "❌ Error: Failed to extract a valid Session ID."
    exit 1
fi
echo "✔ Handshake complete. Working Session ID: $SESSION_ID"

echo -e "\n=== STEP 2: Querying Project Component Inventory ==="

# Create a temporary JSON body file to completely avoid Windows escape bugs
cat << EOF > mcp_payload.json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_clean_component_list",
    "arguments": {
      "project_dir": "D:\\\\Workspace\\\\HW\\\\KiCad\\\\Projects\\\\kicad_hw_design\\\\cardinal_bes2800_rev2.0"
    }
  }
}
EOF

# Call the tool using the file reference
curl -X POST http://localhost:8500/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SESSION_ID" \
  -d @mcp_payload.json

# Clean up temp payload
rm mcp_payload.json

echo -e "\n\n=== Verification Test Sequence Finished ==="
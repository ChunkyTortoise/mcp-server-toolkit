#!/usr/bin/env bash
# One-command Claude Desktop setup for mcp-server-toolkit
# Usage: bash examples/claude_desktop_app/setup.sh
set -euo pipefail

PYTHON="${PYTHON:-python3}"
TOOLKIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "=== mcp-server-toolkit Claude Desktop Setup ==="
echo "Toolkit root: $TOOLKIT_DIR"

# 1. Resolve Claude Desktop config path
if [[ "$OSTYPE" == "darwin"* ]]; then
    CONFIG_DIR="$HOME/Library/Application Support/Claude"
elif [[ "$OSTYPE" == "linux"* ]]; then
    CONFIG_DIR="$HOME/.config/claude"
else
    echo "Unsupported OS: $OSTYPE" >&2
    exit 1
fi

CONFIG_FILE="$CONFIG_DIR/claude_desktop_config.json"

# 2. Locate the Python interpreter that has mcp-server-toolkit installed
PYTHON_BIN="$($PYTHON -c 'import sys; print(sys.executable)')"
echo "Python: $PYTHON_BIN"

# Verify toolkit is importable
if ! "$PYTHON_BIN" -c "import mcp_toolkit" 2>/dev/null; then
    echo "mcp-server-toolkit not found. Installing from $TOOLKIT_DIR ..."
    "$PYTHON_BIN" -m pip install -e "$TOOLKIT_DIR[auth]" --quiet
fi

# 3. Build the server entries
WEB_SERVER="$TOOLKIT_DIR/mcp_toolkit/servers/web_scraping/server.py"
FILE_SERVER="$TOOLKIT_DIR/mcp_toolkit/servers/file_processing/server.py"
MULTI_LLM_SERVER="$TOOLKIT_DIR/mcp_toolkit/servers/multi_llm/server.py"

NEW_SERVERS=$(cat <<JSONEOF
{
    "web-scraping": {
        "command": "$PYTHON_BIN",
        "args": ["$WEB_SERVER"],
        "description": "Web scraping + search tools"
    },
    "file-processing": {
        "command": "$PYTHON_BIN",
        "args": ["$FILE_SERVER"],
        "description": "File reading, writing, PDF/DOCX/CSV parsing"
    },
    "multi-llm": {
        "command": "$PYTHON_BIN",
        "args": ["$MULTI_LLM_SERVER"],
        "description": "Multi-LLM routing (GPT, Gemini, Claude, Grok)"
    }
}
JSONEOF
)

# 4. Merge with existing config (if present)
mkdir -p "$CONFIG_DIR"

if [[ -f "$CONFIG_FILE" ]]; then
    echo "Merging into existing config: $CONFIG_FILE"
    EXISTING=$(cat "$CONFIG_FILE")
    # Use Python to merge JSON (handles nested mcpServers key safely)
    "$PYTHON_BIN" - <<PYEOF
import json, sys

existing = json.loads("""$EXISTING""")
new_servers = json.loads("""$NEW_SERVERS""")

mcp_servers = existing.setdefault("mcpServers", {})
mcp_servers.update(new_servers)

print(json.dumps(existing, indent=2))
PYEOF
    "$PYTHON_BIN" - > "$CONFIG_FILE.tmp" <<PYEOF
import json, sys

existing = json.loads(open("$CONFIG_FILE").read())
new_servers = json.loads("""$NEW_SERVERS""")

mcp_servers = existing.setdefault("mcpServers", {})
mcp_servers.update(new_servers)

print(json.dumps(existing, indent=2))
PYEOF
    mv "$CONFIG_FILE.tmp" "$CONFIG_FILE"
else
    echo "Creating new config: $CONFIG_FILE"
    cat > "$CONFIG_FILE" <<JSONEOF
{
    "mcpServers": $NEW_SERVERS
}
JSONEOF
fi

echo ""
echo "Done. Config written to: $CONFIG_FILE"
echo ""
echo "Next steps:"
echo "  1. Quit Claude Desktop (if running)"
echo "  2. Reopen Claude Desktop"
echo "  3. You should see tools from: web-scraping, file-processing, multi-llm"
echo ""
echo "Verify with: cat '$CONFIG_FILE'"

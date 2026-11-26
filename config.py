"""Central config + the MCP server registry (the 'marketplace' allow-list)."""
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_env = ROOT / ".env"
if _env.exists():                                   # tiny .env loader (no extra dependency)
    for _l in _env.read_text().splitlines():
        if "=" in _l and not _l.strip().startswith("#"):
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.split("#")[0].strip())
DATA_DIR = Path(os.environ.get("SENTINEL_DATA", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Only servers listed here with trusted=True are ever connected. A marketplace server must be
# reviewed by a human, then added with a PINNED tool list. If the server later exposes a tool
# that is not pinned (tool poisoning / "rug pull"), the gateway refuses to use it.
MCP_REGISTRY = {
    "market": {
        "command": sys.executable,
        "args": [str(ROOT / "mcp_servers" / "market_server.py")],
        "trusted": True,
        "pinned_tools": {"get_history", "get_quote", "render_chart"},
    },
    # "some_marketplace_server": {"command": "npx", "args": ["-y", "pkg"], "trusted": False,
    #                             "pinned_tools": {"tool_a"}},   # stays disabled until reviewed
}

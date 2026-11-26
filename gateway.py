"""The ONLY door agents have to tools. Every call is contract-checked, kill-switch-checked and audited."""
import asyncio, json, os, sys
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .contracts import ContractViolation


class MCPGateway:
    def __init__(self, registry, audit, store):
        self.registry, self.audit, self.store = registry, audit, store
        self.sessions, self.local, self.stack = {}, {}, AsyncExitStack()

    def register_local(self, server, tools: dict):
        self.local[server] = tools

    async def start(self):
        await self.stack.__aenter__()
        for name, cfg in self.registry.items():
            if not cfg.get("trusted"):
                self.audit.append("mcp_server_skipped", "gateway", {"server": name, "reason": "untrusted"})
                continue
            # secrets are NOT forwarded to tool servers
            env = {k: os.environ[k] for k in ("PATH", "PYTHONPATH", "MARKET_PROVIDER", "MARKET_DRIFT", "HOME") if k in os.environ}
            params = StdioServerParameters(command=cfg["command"], args=cfg["args"], env=env)
            r, w = await self.stack.enter_async_context(stdio_client(params))
            s = await self.stack.enter_async_context(ClientSession(r, w))
            await s.initialize()
            exposed = {t.name for t in (await s.list_tools()).tools}
            extra = exposed - set(cfg["pinned_tools"])
            if extra:  # tool poisoning / rug-pull defence
                self.audit.append("mcp_server_rejected", "gateway", {"server": name, "unpinned_tools": sorted(extra)})
                raise ContractViolation(f"MCP server '{name}' exposes unpinned tools {sorted(extra)}")
            self.sessions[name] = s
            self.audit.append("mcp_server_connected", "gateway", {"server": name, "tools": sorted(exposed)})

    async def stop(self):
        await self.stack.aclose()

    async def call(self, rt, server, tool, args, run_id=""):
        agent = rt.c.agent_id
        key = f"{server}:{tool}"
        try:
            if self.store.kill_switch().get("engaged"):
                raise ContractViolation("kill switch engaged: all tool calls blocked")
            rt.authorize_tool(key)
        except ContractViolation as e:
            self.audit.append("tool_denied", agent, {"tool": key, "run": run_id, "why": str(e)})
            raise
        self.audit.append("tool_call", agent, {"tool": key, "args": args, "run": run_id})
        if server in self.local:
            res = self.local[server][tool](**args)
        else:
            raw = await asyncio.wait_for(self.sessions[server].call_tool(tool, args), 30)
            if raw.isError:
                raise RuntimeError(f"{key} failed: {raw.content[0].text if raw.content else ''}")
            res = json.loads(raw.content[0].text)
        shown = {k: ("<image omitted>" if k == "png_base64" else v) for k, v in res.items()} if isinstance(res, dict) else res
        self.audit.append("tool_result", agent, {"tool": key, "run": run_id, "result": _trim(shown)})
        return res


def _trim(obj, n=300):
    s = json.dumps(obj, default=str)
    return {"preview": s[:n], "truncated": len(s) > n}

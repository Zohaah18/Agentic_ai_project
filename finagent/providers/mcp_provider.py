"""OPTIONAL: pull stock data from any MCP server (stdio transport).

UNTESTED against a live server in the course sandbox. MCP servers differ in tool names and
output shape, so you must set MCP_COMMAND / MCP_ARGS / MCP_TOOL_NAME / MCP_TICKER_ARG in .env
after reading that server's documentation. Output is treated as UNTRUSTED text/JSON.
"""
import asyncio
import json
import shlex

from ..models import FinancialSnapshot, Metric
from .base import FinanceProvider


class MCPFinance(FinanceProvider):
    name = "mcp"

    def __init__(self, settings):
        if not (settings.mcp_command and settings.mcp_tool):
            raise ValueError("MCP_COMMAND and MCP_TOOL_NAME must be set to use the MCP provider")
        self.s = settings

    async def _call(self, ticker):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.s.mcp_command, args=shlex.split(self.s.mcp_args))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                res = await session.call_tool(self.s.mcp_tool, {self.s.mcp_ticker_arg: ticker})
                return "".join(getattr(c, "text", "") for c in res.content)

    def get_snapshot(self, ticker):
        text = asyncio.run(self._call(ticker))
        metrics, warnings = [], []
        try:  # accept flat JSON objects of scalar values; anything else is kept as a warning
            data = json.loads(text)
            for k, v in (data if isinstance(data, dict) else {}).items():
                if isinstance(v, (int, float, str)) and len(str(v)) < 80:
                    metrics.append(Metric(str(k), v, "", f"mcp:{self.s.mcp_tool}"))
        except json.JSONDecodeError:
            pass
        if not metrics:
            warnings.append("MCP server returned data in an unrecognised format; no figures could be extracted.")
            from ..resilience import TickerNotFound
            raise TickerNotFound(f"MCP output not parseable for '{ticker}'")
        return FinancialSnapshot(ticker, ticker, self.name, metrics, warnings)

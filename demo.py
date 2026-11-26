"""End-to-end demo (no server needed): agents -> governance -> human approval -> protection -> audit."""
import asyncio, os, tempfile
os.environ["MARKET_PROVIDER"] = "synthetic"   # offline demo only; real runs use real data
os.environ.setdefault("MARKET_DRIFT", "0.004")  # bullish synthetic market so the demo shows a trade
from pathlib import Path
from sentinel.contracts import ContractViolation, ContractRuntime, CONTRACTS
from sentinel.orchestrator import Sentinel
from sentinel.governance import RiskPolicy

def h(t): print(f"\n=== {t} ===")

async def main():
    async with Sentinel(data_dir=Path(tempfile.mkdtemp()), policy=RiskPolicy(allow_synthetic=True)) as s:
        h("1. Multi-agent run over MCP (operator: trader_ops)")
        res = await s.run(["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"], "trader_ops")
        for r in res:
            d = r.get("decision") or {}
            print(r["symbol"], r["status"], r.get("reason", ""), d.get("exposure", ""), d.get("reasons", ""))

        pending = s.store.list_proposals("PENDING_HUMAN")
        if pending:
            p = pending[0]; pid = p["id"]
            h(f"2. Governance on {p['payload']['symbol']}: worst-case loss & protections")
            print(p["payload"]["decision"]["exposure"]); print(p["payload"]["decision"]["protections"])
            h("3. Four-eyes: requester tries to self-approve")
            try: await s.approve(pid, "trader_ops")
            except PermissionError as e: print("BLOCKED:", e)
            h("4. Independent approver (risk_officer) approves -> paper order")
            print(await s.approve(pid, "risk_officer", "reviewed rationale + exposure"))

        h("5. Contract enforcement")
        rt = ContractRuntime(CONTRACTS["stock_predictor_agent"])
        for tool in ("market:get_quote",):
            try: await s.gw.call(rt, "market", "get_quote", {"symbol": "AAPL"})
            except ContractViolation as e: print("DENIED:", e)

        h("6. Kill switch (admin) blocks every agent")
        s.trip_kill_switch("admin", "demo")
        print(await s.run(["AAPL"], "trader_ops"))
        s.release_kill_switch("admin", "demo over")

        h("7. Tamper-evident audit")
        print("chain ok:", s.audit.verify(), "| entries:", s.audit.seq)
        for e in s.audit.tail(6): print(e["seq"], e["type"], e["actor"])

asyncio.run(main())

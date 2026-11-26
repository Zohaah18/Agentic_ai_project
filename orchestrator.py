"""Sentinel: wires MCP gateway + contracts + governance + human approvals into one controlled system."""
import time, uuid
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from .graph import build_graph
from .agents import TradeExecutionAgent
from .audit import AuditLog
from .config import DATA_DIR, MCP_REGISTRY
from .contracts import CONTRACTS, ContractRuntime, ContractViolation
from .gateway import MCPGateway
from .governance import Governance, RiskPolicy
from .store import Store


class Sentinel:
    def __init__(self, data_dir=DATA_DIR, policy=None, registry=MCP_REGISTRY):
        self.data_dir = data_dir
        self.audit = AuditLog(data_dir / "audit.jsonl")
        self.store = Store(data_dir / "state.db")
        self.policy = policy or RiskPolicy()
        self.gov = Governance(self.policy, self.store)
        self.gw = MCPGateway(registry, self.audit, self.store)
        self.gw.register_local("broker", {"paper_order": TradeExecutionAgent(self.store).paper_order})

    async def __aenter__(self):
        await self.gw.start()
        self._cp = AsyncSqliteSaver.from_conn_string(str(self.data_dir / "graph.db"))   # durable pauses
        self.graph = build_graph(self, await self._cp.__aenter__())
        return self

    async def __aexit__(self, *a):
        await self._cp.__aexit__(*a)
        await self.gw.stop()

    def rt(self, name):
        return ContractRuntime(CONTRACTS[name])

    # ---------- analysis pipeline (operator) ----------
    @staticmethod
    def _cfg(pid):
        return {"configurable": {"thread_id": pid}}

    async def run(self, symbols, requested_by):
        results = []
        for sym in symbols:
            pid = "P-" + uuid.uuid4().hex[:8]
            self.audit.append("run_start", requested_by, {"pid": pid, "symbol": sym})
            out = await self.graph.ainvoke({"pid": pid, "symbol": sym, "requested_by": requested_by}, self._cfg(pid))
            if out.get("__interrupt__"):
                results.append({"symbol": sym, "status": "PENDING_HUMAN", "proposal_id": pid, "decision": out["decision"]})
            else:
                results.append({"symbol": sym, "status": out.get("outcome"), "reason": out.get("reason"),
                                "proposal_id": pid if out.get("proposal") else None, "decision": out.get("decision")})
        return results

    # ---------- human decisions (approver) ----------
    def _pending(self, pid, approver):
        p = self.store.get_proposal(pid)
        if not p:
            raise ValueError("unknown proposal")
        if p["status"] != "PENDING_HUMAN":
            raise ValueError(f"proposal is {p['status']}")
        if time.time() > p["expires"]:
            self.store.set_status(pid, "EXPIRED")
            raise ValueError("proposal expired")
        return p

    async def approve(self, pid, approver, note=""):
        p = self._pending(pid, approver)
        if approver == p["requested_by"]:
            self.audit.append("approval_denied", approver, {"id": pid, "why": "four-eyes violation"})
            raise PermissionError("four-eyes rule: requester cannot approve their own proposal")
        out = await self.graph.ainvoke(Command(resume={"decision": "approve", "approver": approver, "note": note}), self._cfg(pid))
        if out.get("outcome") != "EXECUTED":
            raise ValueError(out.get("reason", "not executed"))
        return out["fill"]

    async def reject(self, pid, approver, note=""):
        self._pending(pid, approver)
        await self.graph.ainvoke(Command(resume={"decision": "reject", "approver": approver, "note": note}), self._cfg(pid))

    # ---------- protection loop ----------
    async def monitor(self, actor="system"):
        """Enforce stops / take-profits and trip the circuit breaker when the daily loss limit is hit."""
        events = []
        for pos in self.store.open_positions():
            q = await self.gw.call(self.rt("market_data_agent"), "market", "get_quote", {"symbol": pos["symbol"]}, "monitor")
            px = q["price"]
            if px <= pos["stop"] or px >= pos["tp"]:
                pnl = self.store.close_position(pos["id"], px)
                events.append({"symbol": pos["symbol"], "exit": px, "pnl": pnl, "reason": "stop" if px <= pos["stop"] else "take_profit"})
                self.audit.append("position_closed", actor, events[-1])
        limit = self.policy.capital * self.policy.daily_loss_limit_pct
        if -self.store.realized_pnl_today() >= limit:
            self.trip_kill_switch("circuit-breaker", f"daily loss limit ${limit:,.0f} reached")
            events.append({"circuit_breaker": "TRIPPED"})
        return events

    def trip_kill_switch(self, by, reason):
        self.store.set_kill_switch(True, by, reason)
        self.audit.append("kill_switch_engaged", by, {"reason": reason})

    def release_kill_switch(self, by, reason):
        self.store.set_kill_switch(False, by, reason)
        self.audit.append("kill_switch_released", by, {"reason": reason})

"""L3 Orchestration: the LangGraph workflow.
   market_data -> stock_prediction -> chart_vision -> risk_assessment+governance -> [HUMAN INTERRUPT] -> trade_execution
Every node runs under an agent contract; contract violations and errors route to a halted outcome + escalation.
The graph pauses at the human node (state persisted in SQLite) and resumes only via an approver's API call."""
import numpy as np
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt
from .agents import StockPredictorAgent, MarketDataAgent, RiskAssessmentAgent, ChartVisionAgent
from .contracts import ContractViolation


class G(TypedDict, total=False):
    pid: str
    symbol: str
    requested_by: str
    bundle: dict
    view: dict
    vision: dict
    proposal: dict
    decision: dict
    approver: str
    fill: dict
    outcome: str      # set => graph ends
    reason: str


def build_graph(S, checkpointer):
    def guard(fn):
        async def wrapped(state):
            try:
                return await fn(state)
            except Exception as e:                      # contract violation OR provider/network failure
                kind = "HALTED" if isinstance(e, ContractViolation) else "ERROR"
                S.audit.append("escalation", "orchestrator", {"pid": state["pid"], "symbol": state["symbol"],
                               "kind": kind, "why": str(e), "action": "halted; human review required"})
                p = S.store.get_proposal(state["pid"])
                if p and p["status"] == "PENDING_HUMAN":
                    S.store.set_status(state["pid"], kind)
                return {"outcome": kind, "reason": str(e)}
        return wrapped

    async def data(s):
        return {"bundle": await MarketDataAgent().run(S.gw, S.rt("market_data_agent"), s["symbol"], s["pid"])}

    async def analyst(s):
        v = StockPredictorAgent().run(S.rt("stock_predictor_agent"), s["bundle"])
        if v["direction"] != "BUY":
            why = "SELL signal ignored (no-short policy)" if v["direction"] == "SELL" else "no edge"
            S.audit.append("no_trade", "stock_predictor_agent", {"pid": s["pid"], "symbol": s["symbol"], "view": v["direction"]})
            return {"view": v, "outcome": "NO_TRADE", "reason": why}
        return {"view": v}

    async def vision(s):
        vis = await ChartVisionAgent().run(S.rt("chart_vision_agent"), s["bundle"])
        b = {k: v for k, v in s["bundle"].items() if k != "chart_png_b64"}   # keep checkpoints small
        return {"vision": vis, "bundle": b}

    async def risk(s):
        prop = RiskAssessmentAgent().run(S.rt("risk_assessment_agent"), s["bundle"], s["view"], s["vision"], s["requested_by"])
        dec = S.gov.evaluate(prop, np.diff(np.log(s["bundle"]["closes"])).tolist())
        prop.update(decision=dec.to_dict(), quantity=dec.quantity, run_id=s["pid"])
        status = "REJECTED" if dec.verdict == "REJECTED" else "PENDING_HUMAN"
        S.store.add_proposal(s["pid"], s["requested_by"], status, prop, S.policy.proposal_ttl_seconds)
        S.audit.append("proposal", "risk_assessment_agent", {"id": s["pid"], "status": status, "verdict": dec.verdict,
                                                  "qty": dec.quantity, "reasons": dec.reasons})
        out = {"proposal": prop, "decision": dec.to_dict()}
        if status == "REJECTED":
            out.update(outcome="REJECTED", reason="; ".join(dec.reasons))
        return out

    async def human(s):                                  # the ONLY thing in this node is the pause
        ans = interrupt({"proposal_id": s["pid"], "symbol": s["symbol"],
                         "exposure": s["decision"]["exposure"], "protections": s["decision"]["protections"]})
        if ans["decision"] != "approve":
            S.store.set_status(s["pid"], "REJECTED_BY_HUMAN")
            S.audit.append("human_rejected", ans["approver"], {"id": s["pid"], "note": ans.get("note", "")})
            return {"outcome": "REJECTED_BY_HUMAN", "approver": ans["approver"]}
        S.audit.append("human_approved", ans["approver"], {"id": s["pid"], "note": ans.get("note", "")})
        return {"approver": ans["approver"]}

    async def execute(s):
        pid, pl = s["pid"], s["proposal"]
        q = await S.gw.call(S.rt("market_data_agent"), "market", "get_quote", {"symbol": pl["symbol"]}, pid)
        drift = abs(q["price"] - pl["price"]) / pl["price"]
        if drift > S.policy.max_price_drift_at_approval:
            S.store.set_status(pid, "STALE")
            S.audit.append("approval_blocked", s["approver"], {"id": pid, "why": f"price drift {drift:.2%}"})
            return {"outcome": "STALE", "reason": f"price drifted {drift:.2%}; re-run analysis"}
        redo = S.gov.evaluate(dict(pl, price=q["price"]), [])          # fresh governance: kill switch, budget, limits
        if redo.verdict == "REJECTED":
            S.store.set_status(pid, "REJECTED")
            S.audit.append("approval_blocked", s["approver"], {"id": pid, "why": redo.reasons})
            return {"outcome": "REJECTED", "reason": f"governance re-check: {redo.reasons}"}
        fill = await S.gw.call(S.rt("trade_execution_agent"), "broker", "paper_order", {
            "proposal_id": pid, "symbol": pl["symbol"], "qty": min(redo.quantity, pl["quantity"]), "price": q["price"],
            "stop": redo.protections["stop_price"], "take_profit": redo.protections["take_profit_price"]}, pid)
        S.store.set_status(pid, "EXECUTED", dict(pl, approved_by=s["approver"], fill=fill))
        return {"outcome": "EXECUTED", "fill": fill}

    def go(nxt):
        return lambda s: END if s.get("outcome") else nxt

    g = StateGraph(G)
    for name, fn in [("market_data", data), ("stock_prediction", analyst), ("chart_vision", vision), ("risk_assessment", risk), ("trade_execution", execute)]:
        g.add_node(name, guard(fn))
    g.add_node("human_approval", human)
    g.add_edge(START, "market_data")
    for a, b in [("market_data", "stock_prediction"), ("stock_prediction", "chart_vision"), ("chart_vision", "risk_assessment"), ("risk_assessment", "human_approval"), ("human_approval", "trade_execution")]:
        g.add_conditional_edges(a, go(b), [b, END])
    g.add_edge("trade_execution", END)
    return g.compile(checkpointer=checkpointer)

import asyncio, json, os, sys, tempfile, time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sentinel.audit import AuditLog
from sentinel.contracts import CONTRACTS, ContractRuntime, ContractViolation, AgentContract, grounding_risk
from sentinel.governance import Governance, RiskPolicy
from sentinel.security import AuthError, RateLimiter, UserStore, issue_token, require, verify_token
from sentinel.store import Store

SECRET = b"x" * 40
def tmp(): return Path(tempfile.mkdtemp())
def prop(**k):
    d = dict(symbol="AAPL", side="BUY", price=100.0, confidence=0.8, hallucination_risk=0.1, data_source="yfinance",
             rationale="r", evidence={"a": 1}, requested_qty=1000)
    return {**d, **k}
def gov(**pk):
    st = Store(tmp() / "s.db"); return Governance(RiskPolicy(**pk), st), st

# ---- contracts ----
def test_tool_allowlist():
    rt = ContractRuntime(CONTRACTS["stock_predictor_agent"])
    with pytest.raises(ContractViolation): rt.authorize_tool("market:get_quote")

def test_lifetime_expiry():
    t = [0.0]; rt = ContractRuntime(CONTRACTS["market_data_agent"], clock=lambda: t[0])
    rt.authorize_tool("market:get_quote"); t[0] = 999
    with pytest.raises(ContractViolation, match="lifetime"): rt.authorize_tool("market:get_quote")

def test_call_and_cost_budget():
    rt = ContractRuntime(CONTRACTS["trade_execution_agent"]); rt.authorize_tool("broker:paper_order")
    with pytest.raises(ContractViolation, match="budget"): rt.authorize_tool("broker:paper_order")

def test_certification_expiry():
    c = AgentContract("x", "1", "p", "o", frozenset(), 10, "2020-01-01", 1, 1.0)
    with pytest.raises(ContractViolation, match="certification"): ContractRuntime(c)

def test_hallucination_detection():
    ok, _ = grounding_risk({"p": 100.0}, {"p": 100.5}, 0.6, 120)
    bad, ungrounded = grounding_risk({"p": 100.0, "hi": 900.0}, {"p": 100.0, "hi": 120.0}, 0.9, 20)
    assert ok < 0.1 and bad > 0.3 and ungrounded == ["hi"]
    rt = ContractRuntime(CONTRACTS["chart_vision_agent"])
    with pytest.raises(ContractViolation, match="hallucination"):
        rt.enforce_output({"hi": 900.0}, {"hi": 120.0}, 0.9, 20)

# ---- governance ----
def test_size_clipped_to_loss_limits():
    g, _ = gov(); d = g.evaluate(prop(), [0.01, -0.01] * 20)
    assert d.verdict == "NEEDS_HUMAN" and d.exposure["max_loss_stress"] <= 500 and d.exposure["notional"] <= 5000
    assert d.protections["stop_price"] == 97.0

def test_kill_switch_rejects():
    g, st = gov(); st.set_kill_switch(True, "admin", "test")
    assert g.evaluate(prop(), []).verdict == "REJECTED"

def test_rejects_low_confidence_high_hallucination_unknown_symbol_short():
    g, _ = gov()
    for bad in (prop(confidence=0.3), prop(hallucination_risk=0.9), prop(symbol="GME"), prop(side="SELL"), prop(rationale="")):
        assert g.evaluate(bad, []).verdict == "REJECTED"

def test_daily_loss_budget_shrinks_then_blocks():
    g, st = gov()
    pid = st.open_position("p", "AAPL", 10, 100, 97, 106); st.close_position(pid, 5.0)   # realized -950
    assert g.evaluate(prop(), []).quantity < 83          # budget left 1050 -> order shrunk
    pid = st.open_position("p", "AAPL", 10, 100, 97, 106); st.close_position(pid, -5.0)  # realized -2000 total
    assert g.daily_budget() <= 0 and g.evaluate(prop(), []).verdict == "REJECTED"

def test_synthetic_blocked_by_default():
    g, _ = gov(); assert g.evaluate(prop(data_source="synthetic"), []).verdict == "REJECTED"

# ---- audit ----
def test_audit_tamper_detected():
    p = tmp() / "a.jsonl"; a = AuditLog(p)
    for i in range(5): a.append("e", "x", {"i": i})
    assert a.verify() == (True, None)
    lines = p.read_text().splitlines(); e = json.loads(lines[2]); e["data"]["i"] = 99; lines[2] = json.dumps(e)
    p.write_text("\n".join(lines) + "\n")
    assert a.verify() == (False, 3)

# ---- security ----
def test_token_signature_expiry_roles():
    t = issue_token(SECRET, "trader_ops", "operator")
    c = verify_token(SECRET, t); require(c, "run")
    with pytest.raises(AuthError): require(c, "approve")
    with pytest.raises(AuthError): require(c, "kill_switch")
    with pytest.raises(AuthError, match="signature"): verify_token(b"y" * 40, t)
    with pytest.raises(AuthError, match="expired"): verify_token(SECRET, issue_token(SECRET, "b", "viewer", ttl=1, now=time.time() - 10))
    head, body, sig = t.split("."); forged = issue_token(SECRET, "trader_ops", "admin").split(".")[1]
    with pytest.raises(AuthError): verify_token(SECRET, f"{head}.{forged}.{sig}")

def test_login_lockout():
    u = UserStore(tmp() / "u.json"); u.create("a", "correct-horse-battery", "approver")
    assert u.authenticate("a", "correct-horse-battery") == "approver"
    for _ in range(5):
        with pytest.raises(AuthError): u.authenticate("a", "wrong")
    with pytest.raises(AuthError, match="locked"): u.authenticate("a", "correct-horse-battery")

def test_rate_limit():
    r = RateLimiter(limit=3, window=60)
    for _ in range(3): r.check("k")
    with pytest.raises(AuthError): r.check("k")

# ---- end to end over a real MCP server ----
def test_pipeline_four_eyes_and_stop_loss():
    os.environ["MARKET_DRIFT"] = "0.004"; os.environ["MARKET_PROVIDER"] = "synthetic"
    from sentinel.orchestrator import Sentinel
    async def go():
        async with Sentinel(data_dir=tmp(), policy=RiskPolicy(allow_synthetic=True)) as s:
            res = await s.run(["MSFT", "GOOGL", "NVDA", "TSLA", "AMZN", "AAPL"], "trader_ops")
            pend = s.store.list_proposals("PENDING_HUMAN"); assert pend, res
            pid = pend[0]["id"]
            with pytest.raises(PermissionError): await s.approve(pid, "trader_ops")
            fill = await s.approve(pid, "risk_officer"); assert fill["mode"] == "paper"
            pos = s.store.open_positions()[0]; assert pos["stop"] < pos["entry"] < pos["tp"]
            # a trade that executed is on the audit chain, chain intact
            assert any(e["type"] == "human_approved" and e["actor"] == "risk_officer" for e in s.audit.tail(200))
            assert s.audit.verify()[0]
            s.trip_kill_switch("admin", "t")
            out = await s.run(["AAPL"], "trader_ops"); assert out[0]["status"] == "HALTED"
    asyncio.run(go())


def test_pause_survives_restart():
    """Approval pause is durable: kill the whole system, restart, approve the same proposal."""
    os.environ["MARKET_DRIFT"] = "0.004"; os.environ["MARKET_PROVIDER"] = "synthetic"
    from sentinel.orchestrator import Sentinel
    d = tmp(); pol = RiskPolicy(allow_synthetic=True)
    async def go():
        async with Sentinel(data_dir=d, policy=pol) as s:
            res = await s.run(["MSFT", "GOOGL", "NVDA", "TSLA", "AMZN", "AAPL"], "trader_ops")
            pid = next(r["proposal_id"] for r in res if r["status"] == "PENDING_HUMAN")
        async with Sentinel(data_dir=d, policy=pol) as s2:          # fresh process state, same disk
            assert (await s2.approve(pid, "risk_officer"))["mode"] == "paper"
            assert s2.store.get_proposal(pid)["status"] == "EXECUTED" and s2.audit.verify()[0]
    asyncio.run(go())

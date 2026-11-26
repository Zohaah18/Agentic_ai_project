"""Agentic contracts: what an agent is for, what it may touch, how long it lives,
how much it may spend, and how likely it is to be wrong. Enforced in code, not just documented."""
import time
from dataclasses import dataclass, asdict
from datetime import date


class ContractViolation(Exception):
    """Raised when an agent steps outside its contract. Callers must halt + escalate."""


@dataclass(frozen=True)
class AgentContract:
    agent_id: str
    version: str
    purpose: str
    owner: str
    allowed_tools: frozenset          # "server:tool" strings; anything else is denied
    ttl_seconds: int                  # lifetime of ONE session of this agent
    certified_until: str              # ISO date; after this the agent must be re-certified
    max_tool_calls: int
    max_cost_usd: float
    max_hallucination_risk: float = 1.0   # outputs above this are rejected
    min_confidence: float = 0.0
    known_failure_modes: tuple = ()
    on_violation: str = "halt_and_escalate_to_human"

    def to_dict(self):
        d = asdict(self)
        d["allowed_tools"] = sorted(self.allowed_tools)
        return d


def _close(a, b, tol):
    try:
        return abs(a - b) <= tol * max(abs(b), 1e-9)
    except TypeError:
        return a == b


def grounding_risk(claims: dict, evidence: dict, confidence: float, n_points: int, tol=0.02):
    """Heuristic hallucination-risk score in [0,1] with the list of ungrounded claims.
    risk = 0.6*(share of claims NOT reproducible from raw data)
         + 0.25*(thin-data penalty) + 0.15*(overconfidence on little data)."""
    if not claims:
        return 0.5, ["no_verifiable_claims"]
    bad = [k for k, v in claims.items() if k not in evidence or not _close(v, evidence[k], tol)]
    thin = 1 - min(1.0, n_points / 60)
    overconf = 1.0 if (confidence > 0.8 and n_points < 30) else 0.0
    return round(0.6 * len(bad) / len(claims) + 0.25 * thin + 0.15 * overconf, 3), bad


class ContractRuntime:
    """One live session of an agent under its contract."""

    def __init__(self, contract: AgentContract, clock=time.time):
        self.c, self.clock = contract, clock
        if date.fromisoformat(contract.certified_until) < date.today():
            raise ContractViolation(f"{contract.agent_id}: certification expired {contract.certified_until}")
        self.started, self.calls, self.cost = clock(), 0, 0.0

    @property
    def age(self):
        return self.clock() - self.started

    def check_alive(self):
        if self.age > self.c.ttl_seconds:
            raise ContractViolation(f"{self.c.agent_id}: lifetime exceeded ({self.c.ttl_seconds}s)")

    def authorize_tool(self, tool: str, est_cost: float = 0.001):
        self.check_alive()
        if tool not in self.c.allowed_tools:
            raise ContractViolation(f"{self.c.agent_id}: tool '{tool}' not permitted by contract")
        if self.calls + 1 > self.c.max_tool_calls:
            raise ContractViolation(f"{self.c.agent_id}: tool-call budget exhausted ({self.c.max_tool_calls})")
        self.charge(est_cost)
        self.calls += 1

    def charge(self, usd: float):
        if self.cost + usd > self.c.max_cost_usd:
            raise ContractViolation(f"{self.c.agent_id}: cost budget exceeded (${self.c.max_cost_usd})")
        self.cost += usd

    def enforce_output(self, claims, evidence, confidence, n_points):
        """Returns hallucination risk; raises if above the contract ceiling or confidence too low."""
        self.check_alive()
        risk, bad = grounding_risk(claims, evidence, confidence, n_points)
        if risk > self.c.max_hallucination_risk:
            raise ContractViolation(f"{self.c.agent_id}: hallucination risk {risk} > "
                                    f"{self.c.max_hallucination_risk}; ungrounded={bad}")
        if confidence < self.c.min_confidence:
            raise ContractViolation(f"{self.c.agent_id}: confidence {confidence:.2f} < {self.c.min_confidence}")
        return risk

    def summary(self):
        return {"agent": self.c.agent_id, "age_s": round(self.age, 2), "calls": self.calls, "cost_usd": round(self.cost, 4)}


_CERT = "2027-03-31"
CONTRACTS = {
    "market_data_agent": AgentContract(
        "market_data_agent", "1.0.0", "Fetch and validate market data via MCP. Never interprets or trades.", "data-platform",
        frozenset({"market:get_history", "market:get_quote", "market:render_chart"}),
        ttl_seconds=120, certified_until=_CERT, max_tool_calls=6, max_cost_usd=0.05,
        known_failure_modes=("stale or synthetic data", "provider outage", "poisoned tool output")),
    "stock_predictor_agent": AgentContract(
        "stock_predictor_agent", "1.0.0", "Produce a probabilistic 5-day directional view from price history.", "quant-research",
        frozenset(), ttl_seconds=60, certified_until=_CERT, max_tool_calls=0, max_cost_usd=0.01,
        max_hallucination_risk=0.30, min_confidence=0.50,
        known_failure_modes=("regime change", "overconfidence on short history", "momentum whipsaw")),
    "chart_vision_agent": AgentContract(
        "chart_vision_agent", "1.0.0", "Read the chart IMAGE and cross-check the analyst. Advisory only.", "quant-research",
        frozenset({"llm:vision"}), ttl_seconds=60, certified_until=_CERT, max_tool_calls=1, max_cost_usd=0.10,
        max_hallucination_risk=0.30,
        known_failure_modes=("misreads axis values", "invents levels", "prompt injection via image text")),
    "risk_assessment_agent": AgentContract(
        "risk_assessment_agent", "1.0.0", "Size positions and submit proposals to the governance engine.", "risk-office",
        frozenset(), ttl_seconds=30, certified_until=_CERT, max_tool_calls=0, max_cost_usd=0.01,
        known_failure_modes=("ignoring correlation between positions",)),
    "trade_execution_agent": AgentContract(
        "trade_execution_agent", "1.0.0", "Place PAPER orders ONLY after explicit human approval.", "trading-ops",
        frozenset({"broker:paper_order"}), ttl_seconds=30, certified_until=_CERT, max_tool_calls=1,
        max_cost_usd=0.01, known_failure_modes=("slippage", "stale price at execution")),
}

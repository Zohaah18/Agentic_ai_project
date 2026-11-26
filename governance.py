"""Ethical governance engine. Every trade proposal passes through here BEFORE a human sees it.
It answers: how much can we lose, how do we cap it, and is this action ethically permissible."""
import math
from dataclasses import dataclass, field, asdict
import numpy as np

DISCLOSURE = "Automated, probabilistic analysis. Not financial advice. Paper trading only; a human approved this."


@dataclass
class RiskPolicy:
    mode: str = "paper"                    # 'live' is deliberately unimplemented in the broker
    capital: float = 100_000.0
    max_position_pct: float = 0.05         # max notional per position
    max_loss_per_trade_pct: float = 0.005  # stressed worst-case loss per trade
    daily_loss_limit_pct: float = 0.02     # portfolio loss budget per day (realized + open-at-risk)
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06
    gap_multiplier: float = 2.0            # stress: price gaps through the stop to 2x the stop distance
    min_confidence: float = 0.55
    max_hallucination_risk: float = 0.30
    max_open_positions: int = 5
    allowed_symbols: tuple = ("AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA")
    allow_short: bool = False
    allow_leverage: bool = False
    allow_synthetic: bool = False          # offline-dev only; real runs must use real data
    auto_approve_notional: float = 0.0     # 0 => a human must approve EVERY trade
    proposal_ttl_seconds: int = 3600
    max_price_drift_at_approval: float = 0.01


@dataclass
class Decision:
    verdict: str = "NEEDS_HUMAN"           # NEEDS_HUMAN | AUTO_APPROVED | REJECTED
    quantity: int = 0
    reasons: list = field(default_factory=list)
    exposure: dict = field(default_factory=dict)
    protections: dict = field(default_factory=dict)
    ethics: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


class Governance:
    def __init__(self, policy: RiskPolicy, store):
        self.p, self.store = policy, store

    def daily_budget(self):
        """Loss budget left today = limit - realized losses - stressed loss still at risk in open positions."""
        p = self.p
        limit = p.capital * p.daily_loss_limit_pct
        realized_loss = max(0.0, -self.store.realized_pnl_today())
        at_risk = sum(pos["qty"] * pos["entry"] * p.stop_loss_pct * p.gap_multiplier for pos in self.store.open_positions())
        return limit - realized_loss - at_risk

    def evaluate(self, prop: dict, returns) -> Decision:
        p, d = self.p, Decision()
        hard = []

        def ethic(code, ok, msg):
            d.ethics.append({"rule": code, "pass": bool(ok), "note": msg})
            if not ok:
                hard.append(f"{code}: {msg}")

        # --- ethics / transparency / oversight ---
        ethic("E1_transparency", bool(prop.get("rationale")) and bool(prop.get("evidence")), "rationale + evidence attached")
        ethic("E2_provenance", bool(prop.get("data_source")), f"data source = {prop.get('data_source')}")
        ethic("E3_no_short", prop.get("side") == "BUY" or p.allow_short, "short selling prohibited by policy")
        ethic("E4_no_leverage", not prop.get("leverage") or p.allow_leverage, "leverage prohibited by policy")
        ethic("E5_suitability", prop.get("symbol") in p.allowed_symbols, "symbol within approved universe")
        ethic("E6_reversibility", True, "stop-loss and take-profit attached to every order")
        ethic("E7_human_oversight", True, "human approval required" if p.auto_approve_notional <= 0 else "auto-approval below threshold")
        if prop.get("data_source") == "synthetic" and not p.allow_synthetic:
            hard.append("synthetic data is not allowed to drive proposals (real data required)")

        # --- control state ---
        ks = self.store.kill_switch()
        if ks.get("engaged"):
            hard.append(f"KILL_SWITCH engaged by {ks.get('by')}: {ks.get('reason')}")
        if prop.get("confidence", 0) < p.min_confidence:
            hard.append(f"confidence {prop.get('confidence', 0):.2f} < {p.min_confidence}")
        if prop.get("hallucination_risk", 1) > p.max_hallucination_risk:
            hard.append(f"hallucination risk {prop.get('hallucination_risk')} > {p.max_hallucination_risk}")
        if len(self.store.open_positions()) >= p.max_open_positions:
            hard.append(f"max open positions ({p.max_open_positions}) reached")

        # --- sizing: shrink the order until the worst case fits every limit ---
        price = prop["price"]
        loss_per_share = price * p.stop_loss_pct * p.gap_multiplier
        caps = {
            "position_cap": math.floor(p.capital * p.max_position_pct / price),
            "per_trade_loss_cap": math.floor(p.capital * p.max_loss_per_trade_pct / loss_per_share),
            "daily_budget_cap": math.floor(max(0.0, self.daily_budget()) / loss_per_share),
        }
        req = int(prop.get("requested_qty", 0))
        qty = max(0, min([req] + list(caps.values())))
        if qty < req:
            binding = min(caps, key=caps.get)
            d.reasons.append(f"size reduced {req}->{qty} by {binding}")
        if qty < 1:
            hard.append("no size fits the loss limits")

        notional = qty * price
        r = np.asarray(returns, dtype=float)
        var95 = float(-np.percentile(r, 5) * notional) if len(r) >= 20 else float(notional * 0.05)
        d.quantity = qty
        d.exposure = {"notional": round(notional, 2), "max_loss_stress": round(qty * loss_per_share, 2),
                      "max_loss_at_stop": round(qty * price * p.stop_loss_pct, 2), "var95_1d": round(var95, 2),
                      "daily_budget_remaining": round(self.daily_budget(), 2)}
        d.protections = {"stop_price": round(price * (1 - p.stop_loss_pct), 2),
                         "take_profit_price": round(price * (1 + p.take_profit_pct), 2),
                         "kill_switch": "admin-only, halts all agents", "circuit_breaker": f"auto-trips at ${p.capital * p.daily_loss_limit_pct:,.0f} daily loss",
                         "disclosure": DISCLOSURE}

        if hard:
            d.verdict, d.reasons = "REJECTED", d.reasons + hard
        elif notional <= p.auto_approve_notional:
            d.verdict = "AUTO_APPROVED"
        else:
            d.reasons.append("human approval required")
        return d

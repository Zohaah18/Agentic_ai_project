import pytest
from dataclasses import replace

from finagent import guardrails as g
from finagent.config import get_settings
from finagent.factory import build
from finagent.resilience import CircuitBreaker


@pytest.fixture
def orch(tmp_path):
    s = replace(get_settings(), log_dir=tmp_path, retries=1, kill_switch_env=False, max_qpm=1000)
    return build(s, demo=True, mode="pipeline")


def test_normal_query_ok(orch):
    r = orch.answer("Tell me about AAPL")
    assert r.status == "OK" and r.ticker == "AAPL" and r.sources
    assert "DEMO DATA" in r.markdown and "not personalised" in r.markdown.lower()


def test_company_name_resolves(orch):
    assert orch.answer("How is Microsoft doing?").ticker == "MSFT"


def test_no_ticker_needs_input(orch):
    assert orch.answer("tell me about the market").status == "NEEDS_INPUT"


def test_unknown_ticker_unavailable(orch):
    assert orch.answer("$ZZZZ").status == "UNAVAILABLE"


def test_provider_outage_degrades_not_crashes(orch):
    r = orch.answer("FAIL")
    assert r.status in {"DEGRADED", "UNAVAILABLE"} and any("unavailable" in w.lower() for w in r.warnings)


def test_trade_request_refused(orch):
    assert orch.answer("Place an order to buy AAPL for me").status == "REFUSED"


def test_advice_gets_facts_plus_notice(orch):
    r = orch.answer("Should I buy AAPL?")
    assert r.status == "OK" and any("can't give one" in w for w in r.warnings)


def test_prompt_injection_withheld(orch):
    r = orch.answer("TSLA news")
    assert "Ignore all previous" not in r.markdown and any("suspicious" in w for w in r.warnings)


def test_kill_switch(tmp_path):
    s = replace(get_settings(), log_dir=tmp_path, kill_switch_env=True)
    assert build(s, demo=True, mode="pipeline").answer("AAPL").status == "STOPPED"


def test_rate_limit(tmp_path):
    s = replace(get_settings(), log_dir=tmp_path, max_qpm=2, kill_switch_env=False)
    o = build(s, demo=True, mode="pipeline")
    assert [o.answer("AAPL").status for _ in range(3)][-1] == "STOPPED"


def test_circuit_breaker_opens_and_recovers(monkeypatch):
    b = CircuitBreaker(2, 0.05)
    b.failure(); b.failure()
    assert not b.allow()
    import time; time.sleep(0.06)
    assert b.allow()


def test_number_verifier_catches_invented_figures():
    ev = "Last price: 189.30 USD"
    assert g.unsupported_numbers("Price is 189.30 USD", ev) == []
    assert g.unsupported_numbers("Price is 250.00 USD", ev) == [250.0]


def test_plausibility_flags_bad_data():
    from finagent.models import Metric
    w = g.plausibility_warnings([Metric("Last price", 500, "USD"), Metric("52-week high", 200), Metric("52-week low", 100)])
    assert w


def test_audit_log_redacts_secrets(orch):
    orch.answer("AAPL api_key=sk-abcdefghijklmnop")
    txt = orch.audit.path.read_text()
    assert "sk-abcdefghijklmnop" not in txt

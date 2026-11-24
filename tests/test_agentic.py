import json
import pytest
from dataclasses import replace

from finagent.agentic import AgenticOrchestrator, Toolbox, EvidenceStore, safe_calc
from finagent.config import get_settings
from finagent.factory import build
from finagent.llm_clients import ScriptedLLM
from finagent.providers.mock_provider import MockFinance, MockSearch
from finagent.resilience import ProviderChain


def settings(tmp_path, **kw):
    return replace(get_settings(), log_dir=tmp_path, retries=1, kill_switch_env=False, max_qpm=1000, **kw)


def make(tmp_path, llm, **kw):
    s = settings(tmp_path, **kw)
    return AgenticOrchestrator(s, ProviderChain([MockFinance()], "get_snapshot", s),
                               ProviderChain([MockSearch()], "search", s), llm, demo=True)


def tools_used(r):
    return {(st["agent"], st["tool"]) for st in r.trace["steps"] if st["type"] == "tool_call"}


def test_multi_agent_delegation_and_tool_use(tmp_path):
    r = make(tmp_path, ScriptedLLM()).answer("Tell me about AAPL")
    assert r.status == "OK" and r.trace["summary"] == "agent_verified"
    assert {("orchestrator", "delegate_finance"), ("orchestrator", "delegate_research"),
            ("finance_agent", "get_quote"), ("finance_agent", "calculate"),
            ("research_agent", "search_web"), ("research_agent", "fetch_page")} <= tools_used(r)


def test_hallucinated_number_is_caught_and_revised(tmp_path):
    r = make(tmp_path, ScriptedLLM(hallucinate_once=True)).answer("Tell me about MSFT")
    assert r.trace.get("revisions") and "87.65" not in r.markdown and r.trace["summary"] == "agent_verified"


def test_persistent_hallucination_falls_back_to_deterministic(tmp_path):
    class Liar(ScriptedLLM):
        def _compose(self, tool_msgs, bad):
            return "Shares rose 87.65% last year."
    r = make(tmp_path, Liar()).answer("Tell me about AAPL")
    assert "87.65" not in r.markdown and r.trace["summary"] == "deterministic"
    assert any("failed verification" in w for w in r.warnings)


def test_llm_crash_falls_back_to_pipeline(tmp_path):
    class Dead:
        def chat(self, m, t):
            raise ConnectionError("ollama down")
    r = make(tmp_path, Dead()).answer("Tell me about AAPL")
    assert r.status == "OK" and r.trace["fallback"] == "pipeline" and any("Agent system failed" in w for w in r.warnings)


def test_lazy_model_that_never_calls_tools_still_gets_data(tmp_path):
    class Lazy:
        def chat(self, m, t):
            return {"content": "Looks fine.", "tool_calls": []}
    r = make(tmp_path, Lazy()).answer("Tell me about AAPL")
    assert r.snapshot is not None and any("did not call the finance tool" in w for w in r.warnings)


def test_unknown_tool_and_bad_args_do_not_crash(tmp_path):
    class Confused:
        n = 0
        def chat(self, m, t):
            Confused.n += 1
            if Confused.n == 1:
                return {"content": "", "tool_calls": [{"name": "delete_everything", "arguments": {}}, {"name": "delegate_finance", "arguments": {"wrong": 1}}]}
            return {"content": "No data.", "tool_calls": []}
    r = make(tmp_path, Confused()).answer("Tell me about AAPL")
    assert r.status in {"OK", "DEGRADED", "UNAVAILABLE"}


def test_step_budget_enforced(tmp_path):
    class Loop:
        def chat(self, m, t):
            return {"content": "", "tool_calls": [{"name": "delegate_finance", "arguments": {"task": "again"}}]} if t else {"content": "Done.", "tool_calls": []}
    r = make(tmp_path, Loop(), max_agent_steps=3).answer("Tell me about AAPL")
    assert sum(1 for s in r.trace["steps"] if s["agent"] == "orchestrator" and s["type"] == "tool_call") <= 3


def test_toolbox_scope_and_ssrf_controls(tmp_path):
    o = make(tmp_path, ScriptedLLM()); store = EvidenceStore()
    tb = Toolbox(o, "AAPL", store, lambda u: "x")
    assert "out of scope" in tb.get_quote("TSLA")
    assert "not allowed" in tb.fetch_page("http://169.254.169.254/latest/meta-data")
    assert "not allowed" in tb.fetch_page("file:///etc/passwd")


def test_calculator_is_safe():
    assert safe_calc("(10-5)/2*100") == 250
    for bad in ["__import__('os').system('ls')", "9**999", "a+1"]:
        with pytest.raises(Exception):
            safe_calc(bad)


def test_injected_source_is_withheld_and_not_fetchable(tmp_path):
    r = make(tmp_path, ScriptedLLM()).answer("TSLA news")
    assert "Ignore all previous" not in r.markdown and any("suspicious" in w for w in r.warnings)


def test_factory_auto_falls_back_when_ollama_missing(tmp_path):
    o = build(settings(tmp_path, ollama_host="http://127.0.0.1:9"), demo=False, mode="auto")
    assert o.mode == "pipeline" and "Agentic mode unavailable" in o.mode_note
    with pytest.raises(Exception):
        build(settings(tmp_path, ollama_host="http://127.0.0.1:9"), demo=False, mode="agentic")

from .agentic import AgenticOrchestrator
from .agents import Orchestrator
from .config import get_settings
from .resilience import ProviderChain


def build(settings=None, demo=False, mode=None):
    """mode: 'agentic' (LLM agents), 'pipeline' (no LLM), 'auto' (agentic if Ollama works, else pipeline)."""
    s = settings or get_settings()
    mode = mode or s.mode
    if demo:
        from .providers.mock_provider import MockFinance, MockSearch
        fin, srch = [MockFinance()], [MockSearch()]
    else:
        from .providers.web_search import DuckDuckGoSearch
        fin = []
        for name in s.finance_providers:
            if name == "yfinance":
                from .providers.yfinance_provider import YFinanceProvider
                fin.append(YFinanceProvider())
            elif name == "mcp":
                from .providers.mcp_provider import MCPFinance
                fin.append(MCPFinance(s))
            else:
                raise ValueError(f"Unknown finance provider '{name}'")
        srch = [DuckDuckGoSearch()]
    fchain, schain = ProviderChain(fin, "get_snapshot", s), ProviderChain(srch, "search", s)
    if mode == "pipeline":
        return Orchestrator(s, fchain, schain, demo)
    try:
        if demo:
            from .llm_clients import ScriptedLLM
            llm = ScriptedLLM()
        else:
            from .llm_clients import OllamaClient
            llm = OllamaClient(s.ollama_model, s.ollama_host)
            llm.check()
        return AgenticOrchestrator(s, fchain, schain, llm, demo)
    except Exception as e:  # noqa: BLE001
        if mode == "agentic":
            raise
        o = Orchestrator(s, fchain, schain, demo)
        o.mode_note = f"Agentic mode unavailable ({e}); pipeline mode used."
        return o

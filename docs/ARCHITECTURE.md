# Architecture

```mermaid
flowchart TD
  U[User query] --> G[Guardrails: clean, kill switch, rate limit, intent, ticker]
  G -->|trade request| R[Refuse]
  G -->|ok| O[Orchestrator agent - LLM]
  O -->|delegate_finance| F[Finance agent - LLM]
  O -->|delegate_research| W[Research agent - LLM]
  F -->|get_quote| FP[Finance provider chain: timeout, retry, breaker, fallback]
  F -->|calculate| C[Safe calculator]
  W -->|search_web| SP[Search provider chain]
  W -->|fetch_page| PF[Page fetcher: URL allow-list, SSRF block, sanitiser]
  FP --> E[(Evidence store)]
  C --> E
  SP --> E
  PF --> E
  O --> D[Draft answer]
  D --> V{Verifier: numbers in evidence? no advice?}
  V -->|fail, max 2x| O
  V -->|still fails| T[Deterministic summary]
  V -->|pass| OUT[Rendered answer + table + sources + warnings]
  T --> OUT
  OUT --> A[(Audit log, secrets redacted)]
```

## Safety nets
- LLM unreachable or crashes -> whole request falls back to deterministic pipeline (visible warning).
- A tool never called by a weak model -> orchestrator calls it directly (visible warning).
- Provider down -> retry, breaker, fallback provider, else DEGRADED/UNAVAILABLE. Never fake data.

## File map
| File | Role |
|---|---|
| `finagent/agentic.py` | Agent loop, tools, evidence store, orchestrator with reflection |
| `finagent/llm_clients.py` | OllamaClient (real), ScriptedLLM (offline test double) |
| `finagent/agents.py` | Pipeline mode, rendering, shared orchestration base |
| `finagent/guardrails.py` | Intent, ticker, injection filter, plausibility, number verifier |
| `finagent/resilience.py` | Timeout, retry, breaker, cache, rate limit, provider chain |
| `finagent/providers/` | yfinance, DuckDuckGo, MCP (optional), demo data |
| `finagent/audit.py` | Redacted JSONL audit log |
| `app.py` | Streamlit UI with agent trace |
| `evaluate.py` | Fixed 10-case matrix, both modes |
| `tests/` | 25 tests |

# Multi-Agent Financial Research Assistant (agentic, 100% free / open-source)
Educational, **read-only** prototype. Three LLM agents (orchestrator, finance, research) plan, choose tools,
delegate, and have their answer verified against retrieved evidence. No trades, no advice, no paid APIs.

## 1. Install
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Try it offline first (no internet, no model)
```bash
python -m finagent --demo --trace "Tell me about AAPL"   # scripted test LLM + clearly labelled DEMO data
pytest -q                                                # 25 tests
python evaluate.py --demo --mode agentic                 # writes EVAL_REPORT.md + eval_results.csv
streamlit run app.py                                     # tick "Demo mode" in the sidebar
```
`--demo` uses a **scripted** stand-in for the LLM so the agent loop can be tested deterministically.
It is a test double, not intelligence. Real agent behaviour comes from step 3.

## 3. Real agents with a free open-source model (Ollama)
1. Install Ollama from https://ollama.com and start it (`ollama serve`, or just open the app).
2. `ollama pull qwen2.5:7b` (about 4-5 GB download; needs roughly 8 GB RAM). Low-spec laptop: `ollama pull qwen2.5:3b`
   and set `OLLAMA_MODEL=qwen2.5:3b` in `.env` (smaller models call tools less reliably; the safety net below helps).
3. `cp .env.example .env`, then:
```bash
python -m finagent --trace "Tell me about MSFT"          # live data + local LLM agents
streamlit run app.py                                     # web UI showing every agent step
python evaluate.py --live --mode agentic                 # your real evaluation numbers for the report
```
Live providers (yfinance, DuckDuckGo) are free and unofficial: fine for a class demo, not for public/commercial use.
**We could not test Ollama or live providers in the build sandbox (network restricted).** Run steps 2-3 yourselves
and fix small provider-specific issues (field names, model tool-calling quirks) before submitting.

## What makes it agentic
| Capability | Where |
|---|---|
| Orchestrator LLM decides what to delegate, can re-delegate | `agentic.py` `AgenticOrchestrator` |
| Specialist agents choose their own tools (`get_quote`, `calculate`, `search_web`, `fetch_page`) | `agentic.py` `run_agent`, `Toolbox` |
| Tool errors are fed back to the model so it can recover | `run_agent` |
| Reflection: draft checked against evidence; revision requested up to 2 times | `_collect` / `_check_draft` |
| Excessive-agency limits: allow-listed tools, one-ticker scope, step budget, URL allow-list, SSRF block, safe calculator | `Toolbox`, `safe_calc`, `_public_http_url` |
| Graceful degradation: if a tool is never called -> direct retrieval; if the LLM crashes -> deterministic pipeline | `_collect` |

## Modes
`agentic` (LLM agents) | `pipeline` (fixed workflow, no LLM, fastest, most predictable) | `auto` (agentic if Ollama works, else pipeline with a visible notice).
Comparing the two modes in your evaluation is a good report section.

## Files
See `docs/ARCHITECTURE.md` (diagram + file map) and `docs/GOVERNANCE_AND_RISK.md` (ethics, risks, malfunction playbook, consequences, MCP vetting).

## Emergency stop
Create an empty file named `KILL_SWITCH` in this folder (or set `KILL_SWITCH=1`). All requests return STOPPED.

## MCP (optional)
Set `MCP_*` in `.env`, then `FINANCE_PROVIDERS=mcp,yfinance`. Untested against a live server; read governance section 5 first.

## Disclaimer
Educational research summaries only. Not financial advice. Verify with primary sources.

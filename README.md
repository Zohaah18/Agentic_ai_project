# Sentinel — governed multi-agent system on MCP + LangGraph (paper trading)

## Layered architecture
```
L1  Interface        Approver dashboard (GET /) + REST control plane (FastAPI, localhost)
L2  Identity/Access  PBKDF2 login, expiring signed tokens, RBAC (viewer/operator/approver/admin), lockout, rate limit
L3  Orchestration    LangGraph: market_data -> stock_prediction -> chart_vision -> risk_assessment -> [HUMAN INTERRUPT] -> trade_execution  (SQLite checkpoints)
L4  Agents           MarketDataAgent, StockPredictorAgent, ChartVisionAgent (multimodal), RiskAssessmentAgent, TradeExecutionAgent
L5  Contracts+Ethics Agent contracts (tools, TTL, budgets, hallucination ceiling) + governance (loss limits, ethics rules)
L6  MCP Gateway      Contract + kill-switch check + audit on EVERY tool call; pinned tool lists; untrusted servers blocked
L7  Tool servers     MCP market-data server (real data via yfinance); marketplace servers via `cli inspect` onboarding
L8  Evidence         Hash-chained audit log, SQLite state, durable graph checkpoints
```

## Run it (real data)
```bash
pip install -r requirements.txt
cp .env.example .env && python -c "import secrets;print('SENTINEL_SECRET='+secrets.token_hex(32))"   # paste into .env
python -m sentinel.cli create-user trader_ops operator
python -m sentinel.cli create-user risk_officer approver
python -m sentinel.cli create-user platform_admin admin
python -m sentinel.cli serve            # open http://127.0.0.1:8443
```
Sign in as trader_ops -> Run agents -> sign out -> sign in as risk_officer -> approve. The pause survives restarts.

## Onboard an MCP marketplace server
`python -m sentinel.cli inspect <command> <args...>` lists its tools. Review them, then add to `MCP_REGISTRY`
with `trusted=True` and `pinned_tools`. Any tool outside the pinned list makes the gateway refuse the server.

## Honest limits
- Real-data path (yfinance) was written but not run in the build sandbox (no internet). First live run is yours: expect to tune it.
- yfinance is an unofficial Yahoo wrapper: fine for a demo, not for production. History and quote share one source, so the
  quote-vs-history check is weak; onboard a second marketplace server for an independent cross-check.
- The predictor is a transparent baseline, not a profitable model. Paper trading only.
- Hallucination risk is a heuristic. TLS, token revocation and OIDC are deployment work.

# Governance, Risk and Failure-Consequence Plan
**Project:** Multi-Agent Financial Research Assistant (FAST-NUCES, Agentic AI)
**Status of this document:** a student-team planning and risk document, not legal advice. Where it names laws,
regulators or provider terms, verify the current text yourselves or ask your instructor / university legal office.

---
## 1. What we are, and what we are not
| We are | We are NOT |
|---|---|
| A read-only educational research demo | An investment adviser, broker, signal service or trading bot |
| Source-linked summaries with retrieval timestamps | A real-time or guaranteed-complete data service |
| A system that says "unavailable" when it does not know | A system that fills gaps with guesses |

**Hard boundaries enforced in code** (`finagent/guardrails.py`, `agents.py`): no trade execution, no account/brokerage
connection, no personalised buy/sell/hold opinion, no secrets in logs, web content treated as untrusted data,
kill switch, rate limit.

## 2. Accountability (who answers for what)
| Person | Owns | If something goes wrong they are first responder for |
|---|---|---|
| Zoha Ahmed | Scope, architecture, final demo, release decision | Deciding to pause / kill switch; communicating to instructor |
| Urooj | Providers, config, secrets, dependencies | Provider outages, key leaks, version breakage |
| Amna Zahid | Test matrix, response wording, documentation | Wrong/misleading outputs, evaluation records, disclaimer accuracy |

Rule: **nobody merges or demos alone.** Every release candidate needs a second member to run `pytest` and
`python evaluate.py` and read three sample outputs.

## 3. Risk register
| # | Risk | Likelihood | Impact | Control already in the code | Residual action for humans |
|---|---|---|---|---|---|
| R1 | Stale / wrong market data shown as fact | Med | High | Retrieval time on every figure; plausibility checks (price vs 52-wk range, P/E sanity); status = DEGRADED | Spot-check 3 figures against the source before every demo |
| R2 | LLM invents numbers or sources | Med-High (small local models) | High | Draft verified against evidence (`unsupported_numbers`, 1% tolerance, unit-scale aware); up to 2 revisions; else deterministic text. Derived numbers must come from the `calculate` tool | Compare `agentic` vs `pipeline` in evaluation; use `--mode pipeline` for any high-stakes demo |
| R3 | Prompt injection in web pages / MCP output | Med | High | `sanitize_web_text` withholds suspicious text; LLM system prompt says evidence is untrusted; tools are read-only | Review flagged items in `logs/audit.jsonl` |
| R4 | Data provider outage / rate limit | High | Med | Timeout, retry with backoff, circuit breaker, provider fallback chain, short cache, honest "unavailable" | Have a pre-recorded demo as backup |
| R5 | Provider terms violated (e.g. unofficial scraping wrapper) | Med if deployed publicly | High | Demo-only scope; provider named in docs | Do not deploy publicly on yfinance. See section 6 |
| R6 | User treats output as advice | Med | High | Disclaimer on every output; advice questions get facts + explicit notice; trade requests refused | Never remove the disclaimer; never market as "signals" |
| R7 | API key leak | Low-Med | Med | `.env` only; audit log redacts key patterns; `.gitignore` | Rotate key immediately if committed; check git history |
| R8 | Cost spike | Low | Low | No paid service anywhere: local open-source model, free data tiers; per-minute rate limit | If anyone adds a paid key later, set a provider-side spend cap first |
| R9 | Malicious or changed MCP server | Low-Med | High | Provider isolated behind interface; output parsed to scalars only; fallback chain | Pin versions, vet source (section 5) |
| R10 | Privacy: logging user queries | Low | Med | Queries stored only as a hash unless `LOG_QUERIES=true`; redaction | Delete logs after evaluation |
| R11 | Academic-integrity mismatch (AI use not declared) | Low | High | Declaration in proposal s.14 | Update declaration (section 9) to match what you actually used |
| R12 | Team member unavailable before demo | Med | Med | Setup docs, demo mode, tests | Cross-train: every member can run the demo |
| R13 | Excessive agency: agent calls tools it should not, loops, or wanders | Med | Med-High | Allow-listed tools per agent, single-ticker scope, step budget (`AGENT_MAX_STEPS`), max 3 calls per step, all tools read-only | Never add write/shell/email tools without a new risk review |
| R14 | Agent fetches internal/private URLs (SSRF) or arbitrary sites | Low | High | `fetch_page` only accepts URLs returned by `search_web`; private/loopback/link-local IPs blocked, including on redirects; text-only, size-capped | Keep this check if you extend tools |
| R15 | Small local model unreliable at tool calling | High | Med | Tool errors returned to model; safety net runs missing tools directly; LLM crash -> pipeline fallback | Pick `qwen2.5:7b` if hardware allows; record failure rates in the report |
| R16 | Local model too slow / out of memory on a student laptop | Med | Med | 180 s client timeout; fallback to pipeline | Use a 3B model or `--mode pipeline` for the live demo; pre-record a backup |

## 4. Malfunction playbook (what happens automatically, what you do)
| Failure | What the system does by itself | What you do |
|---|---|---|
| Finance API times out / errors | Retries (backoff) -> tries next provider -> if all fail returns **DEGRADED/UNAVAILABLE** with reason; breaker stops hammering for 60 s | Check provider status page; wait; do not "fix" by switching to demo data and presenting it as live |
| Search provider down | Finance-only answer, status DEGRADED, warning shown | Same as above |
| Ticker unknown | UNAVAILABLE + message; no retry, breaker not tripped | Ask user for correct ticker |
| Numbers look impossible | Warning + status DEGRADED | Compare with the source page; log the case in the evaluation record |
| Agent draft contains unsupported number or advice | Rejected, revision requested (max 2), then deterministic summary; shown in trace | Review trace; tighten prompts if frequent |
| Ollama not running / model missing / crashes | `auto` mode: pipeline used with visible notice; mid-request crash: pipeline fallback | Start Ollama, `ollama pull <model>`; do not hide the notice in the demo |
| Agent loops or calls wrong tool | Step budget, unknown-tool error returned to model, out-of-scope ticker refused | Read the trace; adjust prompts |
| Suspicious web text | Text withheld, user warned | Review `audit.jsonl`; add pattern to `INJECTION` if new |
| Rate limit hit | STOPPED + polite message | Raise `MAX_QUERIES_PER_MINUTE` only if justified |
| **Something is clearly wrong and you are unsure why** | Create a file named `KILL_SWITCH` in the project root (or set `KILL_SWITCH=1`). All requests return STOPPED | Investigate; delete the file only after fix + second-person check |
| MCP server returns garbage | Not parseable -> treated as provider failure -> next provider | Check tool name/args in `.env`; compare with server docs |
| Key leaked | n/a | Revoke/rotate at the provider, remove from git history, tell instructor, check usage dashboard |

**Incident steps (any severity):** 1) Contain (kill switch). 2) Record what happened, when, which query (from `audit.jsonl`).
3) Assess who could have been affected. 4) Tell the instructor the same day if output reached anyone outside the team.
5) Fix and add a regression test. 6) Write a 5-line post-mortem in `docs/incidents.md`.

Severity guide: **S1** wrong data presented to people outside the team, or key/credential leak; **S2** repeated wrong
output caught internally; **S3** outage/degraded only, correctly flagged.

## 5. Using MCP servers as the data source (what your sir mentioned)
**Where to look.** The official MCP Registry and the `modelcontextprotocol/servers` GitHub repo are the most
authoritative starting points; community directories (e.g. Smithery, mcp.so, PulseMCP) list many more.
Several market-data vendors have published their own MCP servers (check Alpha Vantage, Financial Datasets, and
similar). Availability, free-tier limits and tool names change often, so confirm on the vendor's site.
This project's `providers/mcp_provider.py` plugs one in via `.env`; it has **not** been tested against a live server
by us, so test it before relying on it.

**Vetting checklist (do before connecting any MCP server):**
1. Provenance: official vendor or well-maintained repo? Last commit? Stars are not security.
2. License and the data vendor's terms: are educational/redistribution uses allowed? Is attribution required?
3. Permissions: read-only tools only. Reject servers that expose write, file or shell tools you do not need.
4. Read the tool descriptions yourself: tool descriptions can contain hidden instructions ("tool poisoning").
5. Pin the exact version; no `@latest` in the run command.
6. Secrets via environment variables only; separate key just for this project with a spend cap.
7. Free-tier rate limits and daily caps noted in `.env.example` comments.
8. Run it once manually, read the raw output, and add a test with a saved sample.

**How we handle MCP malfunction:** the MCP server is just one entry in the provider chain
(`FINANCE_PROVIDERS=mcp,yfinance`). If it hangs, errors or returns an unparseable shape, the timeout, retry, circuit
breaker and fallback apply, and the user sees a data-status warning. MCP output is never trusted as instructions.

## 6. Consequences if the project fails or causes harm
Be realistic: consequences depend almost entirely on **where it runs and who relies on it**.

### Tier A: Failure inside the course (demo only, disclaimers intact). This is your actual situation.
- A broken demo, an API outage, or wrong figures **that the system flagged** are normal engineering outcomes.
  Expected consequence: lost marks on that component, not liability. A documented failure analysis can earn credit.
- Unflagged wrong output in a graded demo: marks lost for evaluation/safeguard criteria.
- AI-use declaration that does not match reality, copied code without credit, or fabricated evaluation numbers:
  this is an academic-integrity matter and is **much more serious than a broken demo**. Report honestly.
- Shared responsibility: the proposal lists three members with no supervisor, so all three carry the outcome. Agree roles in writing.

### Tier B: Shared publicly (GitHub, a website, friends using it for real money). Not recommended.
Possible consequences (illustrative, not a prediction for your case):
- **Users lose money** relying on stale or wrong data. A disclaimer reduces but does not eliminate blame, especially if
  the tool looks authoritative. Reputational damage for the team and the university.
- **Financial-promotion rules.** Some jurisdictions regulate giving investment advice or recommendations to the public.
  Pakistan's securities regulator (SECP) and the regulators of any country your users are in may apply. Ask your
  university; we cannot tell you whether any rule applies.
- **Provider terms.** Free, unofficial data access (such as scraping wrappers) typically restricts use to personal /
  non-commercial purposes. Consequences: blocked IP, revoked key, takedown or cease-and-desist letter.
- **Copyright.** Republishing article text instead of linking can infringe. We store links and short snippets only.
- **Privacy / data protection.** Retaining user queries or identifiers creates obligations. We hash queries by default.
- **Security incident.** A leaked key can produce a bill under your name.

### Tier C: Commercial or advisory use. Out of scope. Needs licensed data, legal review, compliance and insurance. Do not do it.

### Recommendation
Keep it a course demo. If a user outside the team will use it, add: authentication, hosted-provider licence review,
monitoring, a legal/university sign-off, and re-read section 8. Otherwise tell people it is a classroom prototype.

## 7. What a "professional" release needs (and what we do)
| Practice | Status |
|---|---|
| Automated tests (`pytest`) | Included (25 tests, incl. agent failure modes) |
| Fixed evaluation matrix before test run | `evaluate.py`, cases fixed in code |
| Structured audit log, secrets redacted | Included |
| Timeouts, retries, breaker, fallback | Included |
| Kill switch, rate limit | Included |
| Versions pinned | Run `pip freeze > requirements.lock` before the demo |
| Backup demo | Record a screen capture; use `--demo` mode only if labelled as demo |
| Monitoring / alerting | Manual: read `logs/audit.jsonl`; not implemented for a course scope |

## 8. Post-deployment checklist (if the demo lives on after the course)
- [ ] Re-confirm every data provider's current terms and free-tier limits
- [ ] Rotate API keys; set provider-side spend caps and alerts
- [ ] Re-run `pytest` and `evaluate.py --live`; compare with last report
- [ ] Review audit log weekly for DEGRADED rate, flagged content, latency
- [ ] Update dependencies in a branch; re-test before merging
- [ ] Re-read disclaimer and README; confirm nothing implies advice
- [ ] Name one owner who answers incident reports; publish contact in README
- [ ] Define end-of-life date; delete logs and keys when the project is retired

## 9. Updated sections to paste into the proposal
**s.12 Governance (addition):** The agents are limited to read-only, allow-listed tools scoped to one ticker with a step budget, and their drafts are verified against retrieved evidence before display. The prototype also includes a kill switch, request rate limit, provider fallback with
circuit breaking, plausibility checks on retrieved figures, prompt-injection filtering of web and tool content, and an
append-only redacted audit log. Failures are reported to the user as DEGRADED/UNAVAILABLE rather than concealed.
Public deployment is out of scope pending licence review of data providers and instructor approval.

**s.14 AI-usage declaration (update):** Generative AI assisted in drafting this proposal and in generating the initial
code scaffold and risk documentation. At runtime the system uses a locally hosted open-source language model
(via Ollama); no paid API is used. The team reviewed, ran and tested the code, wrote/ran the evaluation, and takes
responsibility for the submitted work. (Edit to match what you actually did.)

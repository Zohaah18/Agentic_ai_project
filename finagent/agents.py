"""Pipeline-mode agents + orchestrator base class (also the safe fallback for agentic mode)."""
import time
from concurrent.futures import ThreadPoolExecutor

from . import guardrails as g
from .audit import AuditLog
from .models import Response
from .resilience import AllProvidersFailed, RateLimiter, TTLCache


class WebResearchAgent:
    def __init__(self, chain):
        self.chain = chain

    def search(self, query, n=5):
        provider, docs, errs = self.chain.call(query, n)
        clean = []
        for d in docs:
            d.snippet, flagged_s = g.sanitize_web_text(d.snippet)
            d.title, flagged_t = g.sanitize_web_text(d.title, 120)
            d.flagged = flagged_s or flagged_t
            if d.url.startswith(("http://", "https://")):
                clean.append(d)
        return provider, clean, errs

    def run(self, ticker, company_hint=None):
        return self.search(f"{ticker} {company_hint or ''} stock news analyst".strip())


class FinanceAgent:
    def __init__(self, chain, cache):
        self.chain, self.cache = chain, cache

    def run(self, ticker):
        hit = self.cache.get(ticker)
        if hit:
            return hit[0], hit[1], ["served from short-lived cache"]
        provider, snap, errs = self.chain.call(ticker)
        snap.warnings = list(snap.warnings) + g.plausibility_warnings(snap.metrics)
        self.cache.set(ticker, (provider, snap))
        return provider, snap, errs


def _fmt(v):
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


class Orchestrator:
    mode = "pipeline"

    def __init__(self, settings, finance_chain, search_chain, demo=False):
        self.s, self.demo, self.mode_note = settings, demo, None
        self.finance = FinanceAgent(finance_chain, TTLCache(120))
        self.web = WebResearchAgent(search_chain)
        self.limiter = RateLimiter(settings.max_qpm)
        self.audit = AuditLog(settings)

    # ---- public API -------------------------------------------------
    def answer(self, query: str) -> Response:
        t0 = time.time()
        query = g.clean_query(query)
        resp = self._answer(query)
        resp.latency_ms = int((time.time() - t0) * 1000)
        try:
            self.audit.write(query, resp.status, resp.ticker, {k: v for k, v in resp.trace.items() if k != "evidence"},
                             resp.latency_ms)
        except OSError:
            pass  # logging must never break the answer
        return resp

    # ---- internals --------------------------------------------------
    def _answer(self, query):
        if self.s.kill_switch:
            return Response("STOPPED", None, "Service is temporarily disabled by the operators (kill switch).")
        if not query:
            return Response("NEEDS_INPUT", None, "Please enter a company name or ticker, e.g. `AAPL` or `$MSFT`.")
        if not self.limiter.allow():
            return Response("STOPPED", None, "Rate limit reached. Please wait a minute and try again.")

        intent = g.classify_intent(query)
        if intent == "trade":
            return Response("REFUSED", None,
                            "I can't place trades, connect to accounts or act on your behalf. I only provide "
                            "read-only research summaries.\n\n> " + g.DISCLAIMER, trace={"intent": intent})
        ticker = g.resolve_ticker(query)
        if not ticker:
            return Response("NEEDS_INPUT", None,
                            "I couldn't identify a company or ticker. Try `AAPL`, `$MSFT` or a company name.",
                            trace={"intent": intent})

        trace = {"intent": intent, "mode": self.mode}
        snap, docs, warnings, summary = self._collect(query, ticker, trace)
        if intent == "advice":
            warnings.insert(0, "You asked for a buy/sell/hold style opinion. I can't give one; here are facts and sources instead.")
        if self.mode_note:
            warnings.append(self.mode_note)
        if snap:
            warnings += snap.warnings
        if any(d.flagged for d in docs):
            warnings.append("Some web content contained suspicious instruction-like text and was withheld.")

        status = "OK" if (snap and docs) else "DEGRADED" if (snap or docs) else "UNAVAILABLE"
        if status == "OK" and any(k in w for w in warnings for k in ("stale", "implausible", "inconsistent")):
            status = "DEGRADED"
        md = self._render(ticker, snap, docs, warnings, status, trace, summary)
        return Response(status, ticker, md, snap, docs, warnings, trace=trace)

    def _collect(self, query, ticker, trace):
        """Pipeline mode: fixed workflow, both agents run in parallel. Returns (snap, docs, warnings, summary|None)."""
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_fin = ex.submit(self._safe, self.finance.run, ticker)
            f_web = ex.submit(self._safe, self.web.run, ticker)
            fin, web = f_fin.result(), f_web.result()
        trace["agents"] = {"finance": fin["trace"], "web": web["trace"]}
        snap = fin["data"][1] if fin["ok"] else None
        docs = web["data"][1] if web["ok"] else []
        w = []
        if not fin["ok"]:
            w.append(f"Financial data unavailable: {fin['error']}")
        if not web["ok"] or not docs:
            w.append("No usable web sources were retrieved." + (f" ({web['error']})" if web["error"] else ""))
        return snap, docs, w, None

    @staticmethod
    def _safe(fn, *args):
        t = time.time()
        ms = lambda: int((time.time() - t) * 1000)  # noqa: E731
        try:
            provider, data, errs = fn(*args)
            return {"ok": True, "data": (provider, data), "error": None,
                    "trace": {"provider": provider, "errors": errs, "ms": ms()}}
        except AllProvidersFailed as e:
            return {"ok": False, "data": None, "error": str(e), "trace": {"provider": None, "errors": e.errors, "ms": ms()}}
        except Exception as e:  # noqa: BLE001  (agents must never crash the orchestrator)
            return {"ok": False, "data": None, "error": f"{type(e).__name__}: {e}",
                    "trace": {"provider": None, "errors": [str(e)], "ms": ms()}}

    def _summary(self, ticker, snap, docs, trace=None):
        if trace is not None:
            trace["summary"] = "deterministic"
        if not snap:
            return "No verified figures were available, so no numerical summary is given."
        by = {m.name: m for m in snap.metrics}
        parts = []
        if "Last price" in by:
            m = by["Last price"]
            parts.append(f"{snap.company} ({snap.ticker}) last price was {_fmt(m.value)} {m.unit}".strip())
        if "52-week low" in by and "52-week high" in by:
            parts.append(f"with a 52-week range of {_fmt(by['52-week low'].value)} to {_fmt(by['52-week high'].value)}")
        s = " ".join(parts) + "." if parts else ""
        if "Analyst consensus" in by:
            n = by.get("Analyst count")
            s += f" The reported analyst consensus label is '{by['Analyst consensus'].value}'" + \
                 (f" across {_fmt(n.value)} analysts." if n else ".")
        return s.strip() or "Figures retrieved; see the table."

    @staticmethod
    def _evidence_text(snap, docs):
        lines = []
        if snap:
            lines += [f"{m.name}: {_fmt(m.value)} {m.unit} ({m.value})" for m in snap.metrics]
        lines += [f"{d.title}. {d.snippet}" for d in docs if not d.flagged]
        return "\n".join(lines)

    def _render(self, ticker, snap, docs, warnings, status, trace, summary=None):
        out = []
        if self.demo:
            out.append("> **DEMO DATA: not real market data. For testing and demonstration only.**\n")
        out.append(f"# {snap.company if snap else ticker} ({ticker})")
        out.append(f"**Data status:** {status} &nbsp; **Mode:** {self.mode}\n")
        out.append("## Summary\n" + (summary or self._summary(ticker, snap, docs, trace)) + "\n")
        if snap and snap.metrics:
            out.append("## Key figures\n| Metric | Value | Unit | Source | Retrieved (UTC) |\n|---|---|---|---|---|")
            for m in snap.metrics:
                out.append(f"| {m.name} | {_fmt(m.value)} | {m.unit} | {m.source} | {m.retrieved_at} |")
            out.append("")
        if docs:
            out.append("## Recent public sources")
            for i, d in enumerate(docs, 1):
                note = " ⚠ withheld" if d.flagged else ""
                out.append(f"{i}. [{d.title or d.url}]({d.url}){note}: {d.snippet}")
            out.append("")
        if warnings:
            out.append("## Warnings and data-quality notes\n" + "\n".join(f"- {w}" for w in warnings) + "\n")
        out.append("> " + g.DISCLAIMER)
        return "\n".join(out)

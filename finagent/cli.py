import argparse
import json
import sys

from .factory import build


def print_trace(trace):
    for st in trace.get("steps", []):
        a, t = st["agent"], st["type"]
        if t == "tool_call":
            print(f"  [{a}] -> {st['tool']}({json.dumps(st['args'])})")
        elif t == "tool_result":
            print(f"  [{a}] <- {st['tool']}: {st['text'][:90]}")
        else:
            print(f"  [{a}] {t}: {st.get('text', '')[:110]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="finagent", description="Educational multi-agent financial research assistant")
    ap.add_argument("query", nargs="*", help="e.g. 'Tell me about AAPL'. Omit for interactive mode.")
    ap.add_argument("--demo", action="store_true", help="offline demo data + scripted test LLM (no network)")
    ap.add_argument("--mode", choices=["auto", "agentic", "pipeline"], help="default: auto (agentic if Ollama is running)")
    ap.add_argument("--trace", action="store_true", help="print every agent step and tool call")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    try:
        orch = build(demo=a.demo, mode=a.mode)
    except Exception as e:  # noqa: BLE001
        print(f"Cannot start: {e}", file=sys.stderr)
        return 2

    def run(q):
        r = orch.answer(q)
        if a.json:
            print(json.dumps({"status": r.status, "ticker": r.ticker, "warnings": r.warnings,
                              "latency_ms": r.latency_ms, "trace": {k: v for k, v in r.trace.items() if k != "evidence"}},
                             indent=2, default=str))
            return
        if a.trace:
            print("AGENT TRACE"); print_trace(r.trace); print()
        print(r.markdown + f"\n\n_status={r.status} mode={orch.mode} latency={r.latency_ms}ms_")

    if a.query:
        run(" ".join(a.query))
        return 0
    print(f"Financial Research Assistant (educational) [{orch.mode} mode]. Type a company/ticker, or 'quit'.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if q.lower() in {"quit", "exit"}:
            return 0
        run(q)


if __name__ == "__main__":
    sys.exit(main())

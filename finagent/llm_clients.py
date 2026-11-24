"""LLM back-ends. Real: Ollama (free, open-source models running on your own machine).
Test double: ScriptedLLM (deterministic, offline, used by --demo and the unit tests; NOT intelligence)."""
import json
import re


class OllamaClient:
    name = "ollama"

    def __init__(self, model, host="", timeout=180):
        import ollama  # pip install ollama
        self.model = model
        self.client = ollama.Client(host=host or None, timeout=timeout)
        self.name = f"ollama:{model}"

    def check(self):
        """Fail fast (clear message) if the Ollama server or model is missing."""
        try:
            names = [m.model for m in self.client.list().models]
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("Ollama server not reachable. Install from ollama.com and run `ollama serve`.") from e
        if self.model not in names and f"{self.model}:latest" not in names:
            raise RuntimeError(f"Model '{self.model}' not downloaded. Run: ollama pull {self.model}")

    def chat(self, messages, tools):
        r = self.client.chat(model=self.model, messages=messages, tools=tools or None, options={"temperature": 0.1})
        m = r.message
        calls = []
        for tc in (getattr(m, "tool_calls", None) or []):
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append({"name": tc.function.name, "arguments": dict(args or {})})
        return {"content": (m.content or "").strip(), "tool_calls": calls}


class ScriptedLLM:
    """Deterministic stand-in that follows a fixed tool-use policy per role (read from 'ROLE:X' in the system prompt)."""
    name = "scripted-demo-llm"

    def __init__(self, hallucinate_once=False):
        self.hallucinate_once, self._done = hallucinate_once, False

    def chat(self, messages, tools):
        role = re.search(r"ROLE:(\w+)", messages[0]["content"]).group(1)
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        user0 = next(m["content"] for m in messages if m["role"] == "user")
        tk = re.search(r"Ticker:\s*([A-Z.\-]{1,7})", user0)
        ticker = tk.group(1) if tk else ""
        call = lambda name, **a: {"content": "", "tool_calls": [{"name": name, "arguments": a}]}  # noqa: E731
        say = lambda text: {"content": text, "tool_calls": []}  # noqa: E731
        load = lambda m: json.loads(m["content"])  # noqa: E731

        if role == "ORCHESTRATOR":
            if messages[-1]["role"] == "user" and "REVISE" in messages[-1]["content"]:
                return say(self._compose(tool_msgs, bad=False))
            if not tool_msgs:
                return {"content": "", "tool_calls": [
                    {"name": "delegate_finance", "arguments": {"task": f"Get key figures for {ticker}"}},
                    {"name": "delegate_research", "arguments": {"task": f"Find recent public sources about {ticker}"}}]}
            bad = self.hallucinate_once and not self._done
            self._done = self._done or bad
            return say(self._compose(tool_msgs, bad))
        if role == "FINANCE":
            if not tool_msgs:
                return call("get_quote", ticker=ticker)
            first = load(tool_msgs[0])
            if "error" in first:
                return say(f"Financial data could not be retrieved ({first['error']}).")
            by = {m["name"]: m["value"] for m in first["metrics"]}
            if len(tool_msgs) == 1 and all(k in by for k in ("Last price", "52-week high", "52-week low")):
                return call("calculate", expression=f"({by['Last price']} - {by['52-week low']}) / "
                                                    f"({by['52-week high']} - {by['52-week low']}) * 100")
            txt = f"{first['company']} last price {by.get('Last price')} {first['currency']}; " \
                  f"52-week range {by.get('52-week low')} to {by.get('52-week high')}."
            if len(tool_msgs) > 1 and "result" in load(tool_msgs[1]):
                txt += f" The price sits at {load(tool_msgs[1])['result']}% of that range (calculated)."
            return say(txt)
        if role == "RESEARCH":
            if not tool_msgs:
                return call("search_web", query=f"{ticker} stock news")
            first = load(tool_msgs[0])
            results = first.get("results", [])
            if len(tool_msgs) == 1 and results:
                return call("fetch_page", url=results[0]["url"])
            if not results:
                return say("No usable public sources were found.")
            return say("Sources reviewed: " + "; ".join(r["title"] for r in results if "withheld" not in r["snippet"]) + ".")
        return say("")

    @staticmethod
    def _compose(tool_msgs, bad):
        txt = " ".join(m["content"] for m in tool_msgs)
        if bad:
            txt += " Shares rose 87.65% over the past year."  # invented figure: verifier must catch it
        return txt

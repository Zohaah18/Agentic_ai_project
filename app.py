"""Web UI:  streamlit run app.py   (shows answer + every agent step and tool call)"""
import streamlit as st

from finagent.factory import build

st.set_page_config(page_title="Financial Research Assistant", page_icon="📈", layout="wide")
st.title("📈 Multi-Agent Financial Research Assistant")
st.caption("Educational, read-only. Not financial advice.")

with st.sidebar:
    demo = st.toggle("Demo mode (offline, fake data + scripted LLM)", value=False)
    mode = st.selectbox("Mode", ["auto", "agentic", "pipeline"], help="agentic = open-source LLM via Ollama")
    st.markdown("Run `ollama pull qwen2.5:7b` once for agentic mode.")


@st.cache_resource(show_spinner="Starting agents...")
def get(demo, mode):
    return build(demo=demo, mode=mode)


try:
    orch = get(demo, mode)
except Exception as e:  # noqa: BLE001
    st.error(f"Cannot start in this mode: {e}")
    st.stop()
if orch.mode_note:
    st.warning(orch.mode_note)
st.sidebar.success(f"Running: {orch.mode} mode")

q = st.text_input("Ask about a company or ticker", placeholder="Tell me about AAPL")
if st.button("Research", type="primary") and q:
    with st.spinner("Agents working..."):
        r = orch.answer(q)
    {"OK": st.success, "DEGRADED": st.warning}.get(r.status, st.error)(f"Status: {r.status}  |  {r.latency_ms} ms")
    st.markdown(r.markdown)
    steps = r.trace.get("steps", [])
    if steps:
        with st.expander(f"Agent trace ({len(steps)} steps)", expanded=True):
            icon = {"tool_call": "🔧", "tool_result": "📥", "final": "✅", "rejected": "🛑", "revision": "♻️", "error": "⚠️"}
            for st_ in steps:
                body = f"`{st_['tool']}({st_['args']})`" if st_["type"] == "tool_call" else \
                       (f"`{st_.get('tool', '')}` → " if st_["type"] == "tool_result" else "") + st_.get("text", "")
                st.markdown(f"{icon.get(st_['type'], '•')} **{st_['agent']}**: {body}")

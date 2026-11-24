import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return int(default)


@dataclass(frozen=True)
class Settings:
    finance_providers: tuple
    mcp_command: str
    mcp_args: str
    mcp_tool: str
    mcp_ticker_arg: str
    timeout_s: int
    retries: int
    breaker_threshold: int
    breaker_reset_s: int
    max_qpm: int
    log_queries: bool
    kill_switch_env: bool
    log_dir: Path
    ollama_model: str = "qwen2.5:7b"
    ollama_host: str = ""
    max_agent_steps: int = 6
    mode: str = "auto"  # auto | agentic | pipeline

    @property
    def kill_switch(self) -> bool:
        """Emergency stop: env var OR a file named KILL_SWITCH in project root."""
        return self.kill_switch_env or (ROOT / "KILL_SWITCH").exists()


def get_settings() -> Settings:
    return Settings(
        finance_providers=tuple(p.strip() for p in os.getenv("FINANCE_PROVIDERS", "yfinance").split(",") if p.strip()),
        mcp_command=os.getenv("MCP_COMMAND", ""),
        mcp_args=os.getenv("MCP_ARGS", ""),
        mcp_tool=os.getenv("MCP_TOOL_NAME", ""),
        mcp_ticker_arg=os.getenv("MCP_TICKER_ARG", "symbol"),
        timeout_s=_int("PROVIDER_TIMEOUT_S", 15),
        retries=_int("PROVIDER_RETRIES", 2),
        breaker_threshold=_int("BREAKER_THRESHOLD", 3),
        breaker_reset_s=_int("BREAKER_RESET_S", 60),
        max_qpm=_int("MAX_QUERIES_PER_MINUTE", 10),
        log_queries=os.getenv("LOG_QUERIES", "false").lower() == "true",
        kill_switch_env=os.getenv("KILL_SWITCH", "0") == "1",
        log_dir=ROOT / "logs",
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        ollama_host=os.getenv("OLLAMA_HOST", ""),
        max_agent_steps=_int("AGENT_MAX_STEPS", 6),
        mode=os.getenv("FINAGENT_MODE", "auto"),
    )

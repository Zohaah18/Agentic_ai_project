"""MCP server (official SDK, stdio). Tools: get_history, get_quote, render_chart (image for multimodal agents).
MARKET_PROVIDER=synthetic (default, offline, deterministic) | yfinance (real data; needs internet)."""
import base64, hashlib, io, os, re
from datetime import date, timedelta
import numpy as np
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("market-data")
PROVIDER = os.environ.get("MARKET_PROVIDER", "yfinance")   # real data by default; "synthetic" is offline-dev only
_CACHE = {}


def _check(symbol, days):
    if not re.fullmatch(r"[A-Z]{1,5}", symbol):
        raise ValueError("invalid symbol")
    if not 5 <= days <= 500:
        raise ValueError("days must be 5..500")


def _series(symbol, days):
    if PROVIDER == "yfinance":
        import time, yfinance as yf
        hit = _CACHE.get(symbol)
        if not hit or time.time() - hit[0] > 60:      # 60s cache: one provider call per symbol per minute
            h = yf.Ticker(symbol).history(period="2y", auto_adjust=True)["Close"].dropna()
            if len(h) < 30:
                raise RuntimeError(f"provider returned too little data for {symbol}")
            hit = _CACHE[symbol] = (time.time(), [d.strftime("%Y-%m-%d") for d in h.index], [round(float(x), 2) for x in h.values])
        return hit[1][-days:], hit[2][-days:], "yfinance"
    # one deterministic 500-day path per (symbol, day); every tool slices the same path => consistent data
    seed = int(hashlib.sha256(f"{symbol}{date.today()}".encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    r = rng.normal(float(os.environ.get("MARKET_DRIFT", "0.0004")), 0.014, 500)
    prices = (50 + seed % 400) * np.exp(np.cumsum(r))
    dates = [(date.today() - timedelta(days=499 - i)).isoformat() for i in range(500)]
    return dates[-days:], [round(float(x), 2) for x in prices[-days:]], "synthetic"


@mcp.tool()
def get_history(symbol: str, days: int = 120) -> dict:
    """Daily closing prices for a US ticker."""
    _check(symbol, days)
    dates, closes, src = _series(symbol, days)
    return {"symbol": symbol, "dates": dates, "closes": closes, "source": src}


@mcp.tool()
def get_quote(symbol: str) -> dict:
    """Latest price for a US ticker."""
    _check(symbol, 30)
    dates, closes, src = _series(symbol, 30)
    return {"symbol": symbol, "price": closes[-1], "as_of": dates[-1], "source": src}


@mcp.tool()
def render_chart(symbol: str, days: int = 60) -> dict:
    """PNG price chart (base64) so a vision model can read it."""
    _check(symbol, days)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dates, closes, src = _series(symbol, days)
    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=90)
    ax.plot(closes, lw=1.6)
    ax.set_title(f"{symbol} close, last {days}d ({src})")
    ax.set_xlabel("trading day")
    ax.set_ylabel("USD")
    ax.grid(alpha=.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return {"symbol": symbol, "png_base64": base64.b64encode(buf.getvalue()).decode(), "source": src}


if __name__ == "__main__":
    mcp.run()

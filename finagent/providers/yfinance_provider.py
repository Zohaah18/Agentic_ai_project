"""Free market data via the `yfinance` package.

NOTE: yfinance is an unofficial wrapper around Yahoo Finance endpoints. Yahoo's terms
limit use to personal/educational purposes. Fine for a course demo; NOT fine for a
public/commercial deployment. See docs/GOVERNANCE_AND_RISK.md.
"""
from ..models import FinancialSnapshot, Metric
from ..resilience import TickerNotFound
from .base import FinanceProvider


class YFinanceProvider(FinanceProvider):
    name = "yfinance"

    FIELDS = [
        ("Last price", "currentPrice", "currency"),
        ("Market cap", "marketCap", "currency"),
        ("Trailing P/E", "trailingPE", "ratio"),
        ("52-week high", "fiftyTwoWeekHigh", "currency"),
        ("52-week low", "fiftyTwoWeekLow", "currency"),
        ("Analyst consensus", "recommendationKey", "label"),
        ("Analyst count", "numberOfAnalystOpinions", "count"),
        ("Mean analyst target", "targetMeanPrice", "currency"),
    ]

    def get_snapshot(self, ticker):
        import yfinance as yf  # imported lazily so mock mode needs no network libs

        info = yf.Ticker(ticker).info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not info or price is None:
            raise TickerNotFound(f"no market data for '{ticker}'")
        info = dict(info, currentPrice=price)
        cur = info.get("currency", "")
        url = f"https://finance.yahoo.com/quote/{ticker}"
        metrics = []
        for label, key, unit in self.FIELDS:
            v = info.get(key)
            if v is None:
                continue
            metrics.append(Metric(label, v, cur if unit == "currency" else ("" if unit == "label" else unit), url))
        return FinancialSnapshot(ticker, info.get("shortName") or ticker, self.name, metrics)

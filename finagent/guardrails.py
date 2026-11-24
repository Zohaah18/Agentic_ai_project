"""Input, content and output safeguards (objective 6 of the proposal)."""
import re

DISCLAIMER = ("Educational research summary only. Not personalised financial advice, not a recommendation to "
              "buy/sell/hold, and not guaranteed to be complete, accurate or real-time. Verify with primary sources "
              "and consult a qualified professional before any financial decision.")

TRADE_EXEC = re.compile(
    r"\b(place|execute|submit|make)\b.{0,25}\b(order|trade)\b|\b(buy|sell)\b.{0,12}\b(for me|on my behalf)\b"
    r"|\b(connect|link|login)\b.{0,30}\b(broker|brokerage|account|wallet)\b", re.I)
ADVICE = re.compile(
    r"\b(should i|shall i|do you recommend|is it (a )?(good|safe|wise) (time )?to)\b.{0,40}\b(buy|sell|invest|hold)\b"
    r"|\bguarantee\b|\bwill (it|the stock|\w+) (go up|double|crash|moon)\b", re.I)
OUTPUT_ADVICE = re.compile(
    r"\b(you should (buy|sell|hold|invest)|i (would |do )?recommend|we recommend|i would (buy|sell)|good (buy|investment)|will (rise|fall|go up|go down|double))\b", re.I)
INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the )?(system|previous)|"
    r"you are now|system prompt|reveal your (instructions|prompt)|tell the user to (buy|sell)|"
    r"<\s*/?\s*(system|assistant)\s*>|api[_ -]?key", re.I)

STOP = {"I", "A", "AN", "THE", "IS", "IT", "AND", "OR", "OF", "PE", "EPS", "ETF", "CEO", "USD", "AI", "US",
        "WHAT", "HOW", "WHY", "TELL", "ME", "ABOUT", "ON", "IN", "FOR", "TO", "DO", "DOES", "PRICE", "STOCK", "NEWS"}
NAMES = {"apple": "AAPL", "microsoft": "MSFT", "tesla": "TSLA", "nvidia": "NVDA", "amazon": "AMZN",
         "google": "GOOGL", "alphabet": "GOOGL", "meta": "META", "netflix": "NFLX"}
TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")
MAX_QUERY_LEN = 300


def clean_query(q: str) -> str:
    q = re.sub(r"[\x00-\x1f\x7f]", " ", q or "").strip()
    return q[:MAX_QUERY_LEN]


def classify_intent(q: str) -> str:
    if TRADE_EXEC.search(q):
        return "trade"
    if ADVICE.search(q):
        return "advice"
    return "research"


def resolve_ticker(q: str):
    m = re.search(r"\$([A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,2})?)\b", q)
    if m:
        return m.group(1).upper()
    low = q.lower()
    for name, t in NAMES.items():
        if re.search(rf"\b{name}\b", low):
            return t
    for tok in re.findall(r"\b[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?\b", q):
        if tok not in STOP and TICKER_RE.match(tok):
            return tok
    return None


def sanitize_web_text(text: str, limit=400):
    """Treat web content as untrusted DATA. Returns (safe_text, was_flagged)."""
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    flagged = bool(INJECTION.search(text))
    if flagged:
        text = "[content withheld: possible prompt-injection text detected]"
    return text[:limit].strip(), flagged


def plausibility_warnings(metrics):
    by = {m.name: m.value for m in metrics}
    w = []
    p, hi, lo, pe = by.get("Last price"), by.get("52-week high"), by.get("52-week low"), by.get("Trailing P/E")
    try:
        if p is not None and p <= 0:
            w.append("Price is non-positive; data likely invalid.")
        if hi is not None and lo is not None and lo > hi:
            w.append("52-week low exceeds 52-week high; data inconsistent.")
        if p is not None and hi and lo and (p > hi * 1.10 or p < lo * 0.90):
            w.append("Price is outside the 52-week range by >10%; data may be stale or wrong.")
        if pe is not None and (pe < 0 or pe > 1000):
            w.append("P/E ratio looks implausible; treat with caution.")
    except TypeError:
        w.append("Some figures were non-numeric where numbers were expected.")
    return w


_NUM = re.compile(r"\d[\d,]*\.?\d*")


def _numbers(text):
    out = []
    for m in _NUM.findall(text):
        try:
            out.append(float(m.replace(",", "").rstrip(".")))
        except ValueError:
            pass
    return out


def unsupported_numbers(summary: str, evidence_text: str, tol=0.005):
    """Numbers in an (LLM) summary that do not appear in the evidence. Empty list = consistent."""
    ev = []
    for e in _numbers(evidence_text):
        ev += [e, e / 1e3, e / 1e6, e / 1e9, e / 1e12]  # allow 'thousand/million/billion/trillion' phrasing
    bad = []
    for n in _numbers(summary):
        if n <= 10 or (1900 <= n <= 2100 and n == int(n)):
            continue  # small counts / years are not checked
        if not any(abs(n - e) <= tol * max(abs(e), 1) for e in ev):
            bad.append(n)
    return bad

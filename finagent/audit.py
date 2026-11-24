"""Append-only JSONL audit log with secret redaction and optional query hashing."""
import hashlib
import json
import re
from datetime import datetime, timezone

_SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{10,}|api[_-]?key\s*[=:]\s*\S+|bearer\s+[A-Za-z0-9._\-]{10,})", re.I)


def redact(s: str) -> str:
    return _SECRET.sub("[REDACTED]", s or "")


class AuditLog:
    def __init__(self, settings):
        self.s = settings
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.log_dir / "audit.jsonl"

    def write(self, query, status, ticker, trace, latency_ms):
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query_sha256": hashlib.sha256(query.encode()).hexdigest()[:16],
            "query": redact(query) if self.s.log_queries else None,
            "ticker": ticker, "status": status, "latency_ms": latency_ms,
            "trace": json.loads(redact(json.dumps(trace, default=str))),
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

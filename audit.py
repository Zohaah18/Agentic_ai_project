"""Tamper-evident audit log: append-only JSONL, each entry hashes the previous one."""
import hashlib, json, threading, time
from pathlib import Path

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path):
        self.path, self.lock = Path(path), threading.Lock()
        self.path.touch(exist_ok=True)
        self.seq, self.last = 0, GENESIS
        for line in self.path.read_text().splitlines():
            e = json.loads(line)
            self.seq, self.last = e["seq"], e["hash"]

    @staticmethod
    def _hash(e):
        body = {k: e[k] for k in ("seq", "ts", "type", "actor", "data", "prev")}
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()

    def append(self, type_, actor, data=None):
        with self.lock:
            e = {"seq": self.seq + 1, "ts": round(time.time(), 3), "type": type_, "actor": actor,
                 "data": data or {}, "prev": self.last}
            e["hash"] = self._hash(e)
            with self.path.open("a") as f:
                f.write(json.dumps(e, default=str) + "\n")
            self.seq, self.last = e["seq"], e["hash"]
            return e

    def tail(self, n=50):
        return [json.loads(l) for l in self.path.read_text().splitlines()[-n:]]

    def verify(self):
        """(ok, first_bad_seq). Any edit, deletion or reordering breaks the chain."""
        prev = GENESIS
        for line in self.path.read_text().splitlines():
            e = json.loads(line)
            if e["prev"] != prev or e["hash"] != self._hash(e):
                return False, e["seq"]
            prev = e["hash"]
        return True, None

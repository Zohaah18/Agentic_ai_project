"""SQLite state: proposals awaiting humans, paper positions, kill switch."""
import json, sqlite3, threading, time
from datetime import datetime, timezone


def _today_start():
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, created REAL, expires REAL,
                requested_by TEXT, status TEXT, payload TEXT);
            CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id TEXT,
                symbol TEXT, qty INTEGER, entry REAL, stop REAL, tp REAL, opened REAL,
                closed REAL, exit_price REAL, pnl REAL);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);""")

    def _x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur

    # kill switch
    def kill_switch(self):
        r = self._x("SELECT value FROM kv WHERE key='kill'").fetchone()
        return json.loads(r["value"]) if r else {"engaged": False}

    def set_kill_switch(self, engaged, by, reason):
        v = json.dumps({"engaged": engaged, "by": by, "reason": reason, "ts": time.time()})
        self._x("INSERT OR REPLACE INTO kv VALUES('kill', ?)", (v,))

    # proposals
    def add_proposal(self, pid, requested_by, status, payload, ttl):
        now = time.time()
        self._x("INSERT INTO proposals VALUES(?,?,?,?,?,?)",
                (pid, now, now + ttl, requested_by, status, json.dumps(payload, default=str)))

    def get_proposal(self, pid):
        r = self._x("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        return self._prop(r) if r else None

    def list_proposals(self, status=None):
        q, a = ("SELECT * FROM proposals WHERE status=? ORDER BY created DESC", (status,)) if status else \
               ("SELECT * FROM proposals ORDER BY created DESC", ())
        return [self._prop(r) for r in self._x(q, a).fetchall()]

    def set_status(self, pid, status, payload=None):
        if payload is None:
            self._x("UPDATE proposals SET status=? WHERE id=?", (status, pid))
        else:
            self._x("UPDATE proposals SET status=?, payload=? WHERE id=?", (status, json.dumps(payload, default=str), pid))

    @staticmethod
    def _prop(r):
        d = dict(r)
        d["payload"] = json.loads(d["payload"])
        return d

    # positions
    def open_position(self, pid, symbol, qty, entry, stop, tp):
        return self._x("INSERT INTO positions(proposal_id,symbol,qty,entry,stop,tp,opened) VALUES(?,?,?,?,?,?,?)",
                       (pid, symbol, qty, entry, stop, tp, time.time())).lastrowid

    def open_positions(self):
        return [dict(r) for r in self._x("SELECT * FROM positions WHERE closed IS NULL").fetchall()]

    def close_position(self, pos_id, price):
        r = self._x("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
        pnl = round((price - r["entry"]) * r["qty"], 2)
        self._x("UPDATE positions SET closed=?, exit_price=?, pnl=? WHERE id=?", (time.time(), price, pnl, pos_id))
        return pnl

    def realized_pnl_today(self):
        r = self._x("SELECT COALESCE(SUM(pnl),0) s FROM positions WHERE closed>=?", (_today_start(),)).fetchone()
        return float(r["s"])

"""Authentication (PBKDF2 passwords, signed expiring tokens) and authorization (RBAC)."""
import base64, hashlib, hmac, json, os, secrets, time
from pathlib import Path

ROLES = {
    "viewer":   {"read"},
    "operator": {"read", "run"},
    "approver": {"read", "approve"},
    "admin":    {"read", "run", "approve", "kill_switch", "manage_users"},
}


class AuthError(Exception):
    def __init__(self, msg, status=401):
        super().__init__(msg)
        self.status = status


def get_secret():
    s = os.environ.get("SENTINEL_SECRET", "")
    if len(s) < 32:
        raise RuntimeError("SENTINEL_SECRET must be set to a random string of >= 32 characters")
    return s.encode()


def hash_password(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return salt, h


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(secret, sub, role, ttl=900, now=None):
    now = now or time.time()
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"sub": sub, "role": role, "iat": int(now), "exp": int(now + ttl)}).encode())
    sig = _b64(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def verify_token(secret, token, now=None):
    try:
        head, body, sig = token.split(".")
        good = _b64(hmac.new(secret, f"{head}.{body}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            raise AuthError("bad signature")
        claims = json.loads(_unb64(body))
    except AuthError:
        raise
    except Exception:
        raise AuthError("malformed token")
    if claims["exp"] < (now or time.time()):
        raise AuthError("token expired")
    if claims["role"] not in ROLES:
        raise AuthError("unknown role")
    return claims


def require(claims, perm):
    if perm not in ROLES[claims["role"]]:
        raise AuthError(f"role '{claims['role']}' lacks permission '{perm}'", 403)


class UserStore:
    def __init__(self, path):
        self.path = Path(path)
        self.users = json.loads(self.path.read_text()) if self.path.exists() else {}
        self.fails = {}  # username -> (count, locked_until)

    def create(self, name, password, role):
        if role not in ROLES:
            raise ValueError("bad role")
        if len(password) < 12:
            raise ValueError("password must be >= 12 chars")
        salt, h = hash_password(password)
        self.users[name] = {"salt": salt, "hash": h, "role": role}
        self.path.write_text(json.dumps(self.users))
        os.chmod(self.path, 0o600)

    def authenticate(self, name, password, now=None):
        now = now or time.time()
        count, until = self.fails.get(name, (0, 0))
        if until > now:
            raise AuthError("account temporarily locked", 429)
        u = self.users.get(name)
        salt = u["salt"] if u else "00" * 16  # constant-ish work for unknown users
        _, h = hash_password(password, salt)
        if not u or not hmac.compare_digest(h, u["hash"]):
            count += 1
            self.fails[name] = (count, now + 300 if count >= 5 else 0)
            raise AuthError("invalid credentials")
        self.fails.pop(name, None)
        return u["role"]


class RateLimiter:
    def __init__(self, limit=30, window=60):
        self.limit, self.window, self.hits = limit, window, {}

    def check(self, key, now=None):
        now = now or time.time()
        q = [t for t in self.hits.get(key, []) if t > now - self.window]
        if len(q) >= self.limit:
            raise AuthError("rate limit exceeded", 429)
        q.append(now)
        self.hits[key] = q

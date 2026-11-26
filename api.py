"""Human-facing control plane. Binds to localhost by default. Every route needs a signed token + role."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from .config import DATA_DIR
from .contracts import CONTRACTS
from .orchestrator import Sentinel
from .security import AuthError, RateLimiter, UserStore, get_secret, issue_token, require, verify_token

S: dict = {}


@asynccontextmanager
async def lifespan(app):
    S["secret"], S["users"], S["rl"] = get_secret(), UserStore(DATA_DIR / "users.json"), RateLimiter()
    async with Sentinel() as s:
        S["s"] = s
        yield


app = FastAPI(title="Sentinel control plane", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/", include_in_schema=False)
async def dashboard():
    from fastapi.responses import FileResponse
    r = FileResponse(Path(__file__).parent / "dashboard.html")
    r.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"
    return r


@app.exception_handler(AuthError)
async def _auth_err(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({"error": str(exc)}, status_code=exc.status)


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.update({"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store", "X-Frame-Options": "DENY"})
    return resp


def who(perm):
    def dep(request: Request):
        h = request.headers.get("authorization", "")
        if not h.startswith("Bearer "):
            raise AuthError("missing bearer token")
        claims = verify_token(S["secret"], h[7:])
        S["rl"].check(claims["sub"])
        require(claims, perm)
        return claims
    return dep


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)

class Run(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=6)

class Note(BaseModel):
    note: str = Field("", max_length=500)

class Kill(BaseModel):
    engaged: bool
    reason: str = Field(max_length=500)


@app.post("/auth/login")
async def login(b: Login):
    role = S["users"].authenticate(b.username, b.password)
    S["s"].audit.append("login", b.username, {"role": role})
    return {"token": issue_token(S["secret"], b.username, role), "role": role, "expires_in": 900}


@app.get("/contracts")
async def contracts(c=Depends(who("read"))):
    return {k: v.to_dict() for k, v in CONTRACTS.items()}

@app.get("/policy")
async def policy(c=Depends(who("read"))):
    from dataclasses import asdict
    return asdict(S["s"].policy)

@app.post("/runs")
async def runs(b: Run, c=Depends(who("run"))):
    bad = [x for x in b.symbols if x not in S["s"].policy.allowed_symbols]
    if bad:
        raise HTTPException(422, f"symbols outside approved universe: {bad}")
    return await S["s"].run(b.symbols, c["sub"])

@app.get("/proposals")
async def proposals(status: str | None = None, c=Depends(who("read"))):
    return S["s"].store.list_proposals(status)

@app.post("/proposals/{pid}/approve")
async def approve(pid: str, b: Note, c=Depends(who("approve"))):
    try:
        return await S["s"].approve(pid, c["sub"], b.note)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))

@app.post("/proposals/{pid}/reject")
async def reject(pid: str, b: Note, c=Depends(who("approve"))):
    try:
        await S["s"].reject(pid, c["sub"], b.note)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"status": "REJECTED_BY_HUMAN"}

@app.get("/positions")
async def positions(c=Depends(who("read"))):
    return S["s"].store.open_positions()

@app.post("/monitor")
async def monitor(c=Depends(who("run"))):
    return await S["s"].monitor(c["sub"])

@app.get("/status")
async def status(c=Depends(who("read"))):
    s = S["s"]
    return {"kill_switch": s.store.kill_switch(), "daily_budget_remaining": round(s.gov.daily_budget(), 2),
            "realized_pnl_today": s.store.realized_pnl_today(), "audit_chain_ok": s.audit.verify()[0]}

@app.post("/kill-switch")
async def kill(b: Kill, c=Depends(who("kill_switch"))):
    (S["s"].trip_kill_switch if b.engaged else S["s"].release_kill_switch)(c["sub"], b.reason)
    return S["s"].store.kill_switch()

@app.get("/audit")
async def audit(limit: int = 50, c=Depends(who("read"))):
    return S["s"].audit.tail(min(limit, 500))

@app.get("/audit/verify")
async def verify(c=Depends(who("read"))):
    ok, bad = S["s"].audit.verify()
    return {"ok": ok, "first_bad_seq": bad}

"""
Authentication (Phase 3).

Concepts in play, in one breath each:

- PASSWORD HASHING (bcrypt): we never store your password — we store a
  one-way scrambled version. Login scrambles what you typed and compares
  scrambles. A stolen database leaks no passwords. bcrypt is deliberately
  SLOW, which turns a billion-guesses-per-second attack into a crawl.

- JWT (JSON Web Token): a visitor badge. It carries who-you-are and an
  expiry time, signed with a secret only the server knows. Tampering
  breaks the signature, so the server can trust a badge WITHOUT a
  database lookup on every request. Access badges live ~30 minutes.

- REFRESH TOKEN: a longer-lived pass (30 days) whose only power is
  minting fresh access badges. Phones store it so you log in once.

- SINGLE-USER BOOTSTRAP: /auth/register works exactly once — while the
  users table is empty. The first person to claim the server owns it;
  everyone after gets a 403. Simple, and correct for a personal Jarvis.

The old X-API-Key still works everywhere (your PowerShell scripts keep
running); JWT is the path humans-with-browsers use.
"""
import datetime

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from . import ratelimit
from .config import settings
from .db import SessionLocal, User

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------- passwords ----------------
def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


# ---------------- tokens ----------------
def _secret() -> str:
    # A dedicated JWT_SECRET is best; falling back to API_KEY keeps a
    # single-user setup to one secret to manage.
    return settings.jwt_secret or settings.api_key


def make_token(username: str, kind: str, lifetime: datetime.timedelta) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {"sub": username, "type": kind, "iat": now, "exp": now + lifetime},
        _secret(),
        algorithm="HS256",
    )


def decode_token(token: str, expected_kind: str) -> str:
    """Returns the username, or raises ValueError. Expiry and signature
    checks happen inside jwt.decode — we never trust a badge blindly."""
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise ValueError(f"invalid token: {e}")
    if payload.get("type") != expected_kind:
        raise ValueError("wrong token type")
    sub = payload.get("sub")
    if not sub:
        raise ValueError("token has no subject")
    return sub


def issue_pair(username: str) -> dict:
    return {
        "access_token": make_token(
            username, "access", datetime.timedelta(minutes=settings.access_token_minutes)
        ),
        "refresh_token": make_token(
            username, "refresh", datetime.timedelta(days=settings.refresh_token_days)
        ),
        "token_type": "bearer",
    }


# ---------------- the guard used by every protected route ----------------
async def authenticate(
    authorization: str = Header(default=""),
    x_api_key: str = Header(default=""),
) -> str:
    """Accepts EITHER a Bearer JWT (humans) or the X-API-Key (scripts).
    Returns the caller's identity for logging/rate-limiting."""
    if x_api_key and x_api_key == settings.api_key:
        return "api-key"
    if authorization.startswith("Bearer "):
        try:
            return decode_token(authorization[7:], "access")
        except ValueError:
            pass
    raise HTTPException(status_code=401, detail="Login required (Bearer token or X-API-Key)")


def check_ws_token(token: str) -> str | None:
    """WebSockets can't send headers from a browser, so the token rides a
    query parameter. Short-lived access tokens make that acceptable here."""
    if token and token == settings.api_key:
        return "api-key"
    try:
        return decode_token(token, "access")
    except ValueError:
        return None


# ---------------- routes ----------------
class Credentials(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


@router.get("/status")
async def status():
    async with SessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar()
    return {"initialized": bool(count)}


@router.post("/register")
async def register(creds: Credentials, request: Request):
    await ratelimit.guard(request, scope="register", limit=5, window_s=300)
    username = creds.username.strip().lower()
    if len(username) < 3 or len(creds.password) < 8:
        raise HTTPException(400, "Username min 3 chars; password min 8.")
    async with SessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(User))).scalar()
        if count:
            raise HTTPException(403, "This Jarvis already has an owner.")
        db.add(User(username=username, password_hash=hash_password(creds.password)))
        await db.commit()
    return issue_pair(username)


@router.post("/login")
async def login(creds: Credentials, request: Request):
    # Tight limit: password guessing is the one attack every public
    # login endpoint meets. 10 tries per 5 minutes per address.
    await ratelimit.guard(request, scope="login", limit=10, window_s=300)
    username = creds.username.strip().lower()
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None or not verify_password(creds.password, user.password_hash):
        # Same message for "no such user" and "wrong password" — never
        # help an attacker enumerate accounts.
        raise HTTPException(401, "Invalid username or password.")
    return issue_pair(username)


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    try:
        username = decode_token(req.refresh_token, "refresh")
    except ValueError:
        raise HTTPException(401, "Refresh token invalid or expired — log in again.")
    return issue_pair(username)

"""
Rate limiting (Phase 3) — the bouncer.

Mechanism: a Redis counter per (who, what) that self-destructs after the
window. First request creates the counter with an expiry; each request
increments it; over the limit -> HTTP 429 "Too Many Requests".

This is the FIXED WINDOW algorithm — simplest of the family. Its known
flaw (a burst straddling two windows can briefly double the rate) is
irrelevant at personal scale; sliding windows and token buckets exist
for when it isn't.

Failure policy: if Redis is unreachable we ALLOW the request. A limiter
that fails closed turns a Redis hiccup into "owner locked out of his own
assistant" — a security control should never be your own outage.
"""
from fastapi import HTTPException, Request

from .events import client as redis_client


async def allow(key: str, limit: int, window_s: int) -> bool:
    try:
        r = redis_client()
        n = await r.incr(f"rl:{key}")
        if n == 1:
            await r.expire(f"rl:{key}", window_s)
        return n <= limit
    except Exception:
        return True  # fail open — see module docstring


async def guard(request: Request, scope: str, limit: int, window_s: int) -> None:
    """Per-client-address limiter for unauthenticated routes (login/register)."""
    who = request.client.host if request.client else "unknown"
    if not await allow(f"{scope}:{who}", limit, window_s):
        raise HTTPException(429, "Too many requests — slow down and try again shortly.")


async def guard_identity(identity: str, scope: str, limit: int, window_s: int) -> None:
    """Per-identity limiter for authenticated routes (chat)."""
    if not await allow(f"{scope}:{identity}", limit, window_s):
        raise HTTPException(429, "Rate limit reached — give it a minute.")

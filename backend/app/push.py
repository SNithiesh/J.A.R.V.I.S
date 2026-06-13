"""
Push notifications (Phase 4) — ringing the phone when nobody's looking.

How Web Push works, in four sentences: the browser (even closed!) keeps a
service worker registered and a SUBSCRIPTION — a one-off delivery address at
Google's/Mozilla's/Apple's push service. Our server POSTs an encrypted
message to that address. The message is signed with our VAPID key pair so
the push service knows the sender is legitimate. The service worker wakes,
shows the notification, goes back to sleep.

Keys are generated ONCE on first boot and stored in kv_store — no accounts,
no dashboards, nothing for the owner to configure.

Failure policy, as everywhere: notifications are best-effort. Any error is
swallowed; a broken push pipeline must never break a chat or a tool.
"""
import asyncio
import base64
import json
import tempfile

from cryptography.hazmat.primitives import serialization
from sqlalchemy import select

from .db import PushSubscription, SessionLocal

VAPID_SUBJECT = "mailto:owner@jarvis.local"

_private_pem: str | None = None
_public_key_b64: str | None = None
_pem_path: str | None = None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


async def ensure_keys() -> None:
    """Load the VAPID pair from kv_store, generating it on first ever boot."""
    global _private_pem, _public_key_b64, _pem_path
    from . import memory  # get_kv/set_kv live there

    async with SessionLocal() as db:
        priv = await memory.get_kv(db, "vapid_private_pem")
        pub = await memory.get_kv(db, "vapid_public_b64")
        if not priv or not pub:
            from py_vapid import Vapid
            vapid = Vapid()
            vapid.generate_keys()
            priv = vapid.private_pem().decode()
            raw = vapid.public_key.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
            pub = _b64url(raw)
            await memory.set_kv(db, "vapid_private_pem", priv)
            await memory.set_kv(db, "vapid_public_b64", pub)
            await db.commit()
            print("[push] generated new VAPID key pair")
    _private_pem, _public_key_b64 = priv, pub
    # pywebpush wants a key FILE; write the PEM to a private temp file once.
    f = tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False)
    f.write(priv)
    f.close()
    _pem_path = f.name


def public_key() -> str:
    return _public_key_b64 or ""


async def save_subscription(sub: dict) -> None:
    endpoint = str(sub.get("endpoint", ""))[:500]
    if not endpoint:
        return
    async with SessionLocal() as db:
        existing = (await db.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )).scalar_one_or_none()
        if existing is None:
            db.add(PushSubscription(endpoint=endpoint, subscription=sub))
            await db.commit()


def _send_sync(sub: dict, payload: str) -> bool:
    """Blocking send; returns False if the subscription is dead (expired/unsubscribed)."""
    from pywebpush import webpush, WebPushException
    try:
        webpush(
            subscription_info=sub,
            data=payload,
            vapid_private_key=_pem_path,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
        return True
    except WebPushException as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        return code not in (404, 410)  # dead address -> prune
    except Exception:
        return True  # transient — keep the subscription


async def notify_all(title: str, body: str, url: str = "/") -> None:
    """Best-effort push to every registered device."""
    try:
        if not _pem_path:
            return
        payload = json.dumps({"title": title, "body": body, "url": url})
        async with SessionLocal() as db:
            rows = (await db.execute(select(PushSubscription))).scalars().all()
            for row in rows:
                alive = await asyncio.to_thread(_send_sync, row.subscription, payload)
                if not alive:
                    await db.delete(row)
            await db.commit()
    except Exception as e:
        print(f"[push] notify failed (non-fatal): {e}")

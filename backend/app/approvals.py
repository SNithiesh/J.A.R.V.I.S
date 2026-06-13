"""
Approvals (Phase 4) — the human-in-the-loop pattern.

A confirm-policy tool call arrives here and STOPS. We record it, ring every
screen (WebSocket broadcast) and every pocket (push notification), then wait
on an asyncio.Event — a one-shot starting gun another part of the program
can fire. Tapping Allow/Deny on any device calls resolve(), which fires the
gun; the paused tool call wakes up holding the verdict.

Every exit is fail-safe: no answer in time -> denied; unknown approval id ->
ignored; server restart mid-wait -> the call was already denied by timeout
semantics. The model proposes, the human disposes — now literally.
"""
import asyncio
import uuid

from . import events, hub, push
from .db import Approval

TIMEOUT_SECONDS = 120

_pending: dict[str, dict] = {}  # id -> {"event": Event, "approved": bool|None, "tool": str, "args": dict}


def pending_list() -> list[dict]:
    return [{"id": k, "tool": v["tool"], "args": v["args"]} for k, v in _pending.items()]


def resolve(approval_id: str, approved: bool) -> bool:
    entry = _pending.get(approval_id)
    if entry is None:
        return False           # already resolved, timed out, or never existed
    entry["approved"] = approved
    entry["event"].set()       # fire the starting gun
    return True


async def request_and_wait(tool: str, args: dict, db=None,
                           timeout: float = TIMEOUT_SECONDS) -> bool:
    approval_id = uuid.uuid4().hex
    entry = {"event": asyncio.Event(), "approved": None, "tool": tool, "args": args}
    _pending[approval_id] = entry

    if db is not None:
        db.add(Approval(id=approval_id, tool=tool, args=args))
        await db.flush()

    payload = {"id": approval_id, "tool": tool, "args": args, "timeout": timeout}
    await hub.broadcast({"type": "approval_request", "data": payload})
    await events.publish(events.APPROVAL_REQUESTED, {"id": approval_id, "tool": tool})
    await push.notify_all("Jarvis needs permission",
                          f"Allow '{tool}'? Open to decide.", "/")

    try:
        await asyncio.wait_for(entry["event"].wait(), timeout)
    except asyncio.TimeoutError:
        entry["approved"] = False   # silence is refusal
    finally:
        _pending.pop(approval_id, None)

    approved = bool(entry["approved"])
    if db is not None:
        row = await db.get(Approval, approval_id)
        if row is not None:
            row.status = "approved" if approved else "denied"
    await hub.broadcast({"type": "approval_resolved",
                         "data": {"id": approval_id, "approved": approved}})
    await events.publish(events.APPROVAL_RESOLVED,
                         {"id": approval_id, "approved": approved})
    return approved

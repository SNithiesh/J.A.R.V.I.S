"""
The API surface. Two transports over one brain:

  POST /api/chat                  simple request/response (great for curl)
  WS   /ws/chat?token=KEY         live streaming, the path the PWA will use
  GET  /api/sessions              list conversations
  GET  /api/sessions/{id}/messages
  GET  /healthz                   unauthenticated liveness probe
"""
import pathlib

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select

<<<<<<< HEAD
from . import agent, approvals, auth, desktop_bridge, mcp_client, memory, push, ratelimit, tasks
=======
from . import agent, approvals, auth, memory, push, ratelimit, tasks
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
from .config import settings
from .db import ChatSession, Fact, Message, SessionLocal, Task

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    tier: str | None = None  # optional override: "fast" | "smart"


_STATIC = pathlib.Path(__file__).parent / "static"


@router.get("/")
async def home():
    """The chat page — one file, served by the API itself, so the phone
    just opens this server's address and gets a working client."""
    return FileResponse(_STATIC / "index.html")


@router.get("/healthz")
async def healthz():
    return {"ok": True, "node": settings.node_name}


@router.post("/api/chat")
async def chat(req: ChatRequest, identity: str = Depends(auth.authenticate)):
    # The guard returned WHO is calling, so the limiter can count per person.
    await ratelimit.guard_identity(identity, "chat", limit=60, window_s=60)
    async with SessionLocal() as db:
        session_id = await agent.ensure_session(db, req.session_id, req.message)
        reply, tools_used, model = "", [], None
        async for event in agent.run_turn(db, session_id, req.message, req.tier):
            if event["type"] == "done":
                reply = event["data"]
            elif event["type"] == "tool":
                tools_used.append(event["data"]["name"])
            elif event["type"] == "model":
                model = event["data"]
            elif event["type"] == "error":
                raise HTTPException(status_code=502, detail=event["data"])
        return {"session_id": session_id, "reply": reply, "tools_used": tools_used, "model": model}


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
<<<<<<< HEAD
    # Accept FIRST, then close with our code. Closing before accept() makes
    # the server send a bare HTTP 403, and the browser sees only a generic
    # failure — it can't distinguish "badge expired, refresh me" from
    # "network down", so it never uses its refresh token. Accept-then-close
    # is what actually delivers close code 4401 to the page.
    # (Field-found bug: a phone returning after 30+ minutes looped offline.)
    await ws.accept()
    identity = auth.check_ws_token(ws.query_params.get("token", ""))
    if identity is None:
=======
    identity = auth.check_ws_token(ws.query_params.get("token", ""))
    if identity is None:
        # 4401 is our "badge expired" signal — the page reacts by spending
        # its refresh token and reconnecting, invisible to the user.
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
        await ws.close(code=4401)
        return
    if not await ratelimit.allow(f"ws:{identity}", limit=120, window_s=60):
        await ws.close(code=4429)
        return
<<<<<<< HEAD
=======
    await ws.accept()
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
    from . import hub
    hub.register(ws)   # server-initiated events (approvals, tasks, reminders) reach every screen
    try:
        while True:
            incoming = await ws.receive_json()
            text = str(incoming.get("message", "")).strip()
            if not text:
                continue
            async with SessionLocal() as db:
                session_id = await agent.ensure_session(db, incoming.get("session_id"), text)
                await ws.send_json({"type": "session", "data": session_id})
                async for event in agent.run_turn(db, session_id, text, incoming.get("tier")):
                    await ws.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(ws)


@router.get("/api/sessions", dependencies=[Depends(auth.authenticate)])
async def list_sessions():
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(ChatSession).order_by(ChatSession.created_at.desc()).limit(50)
        )).scalars().all()
        return [{"id": s.id, "title": s.title, "created_at": s.created_at.isoformat()} for s in rows]


@router.get("/api/sessions/{session_id}/messages", dependencies=[Depends(auth.authenticate)])
async def list_messages(session_id: str):
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )).scalars().all()
        return [{"role": m.role, "content": m.content, "at": m.created_at.isoformat()} for m in rows]


# ====================== PWA files (public by design) ======================
@router.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(_STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker():
    # Must be served from the root path: a service worker may only control
    # pages within the scope it was loaded from.
    return FileResponse(_STATIC / "sw.js", media_type="application/javascript")

<<<<<<< HEAD
@router.get("/anime.min.js")
async def anime_js():
    return FileResponse(_STATIC / "anime.min.js", media_type="application/javascript")


@router.get("/three.min.js")
async def three_js():
    return FileResponse(_STATIC / "three.min.js", media_type="application/javascript")


=======
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c

@router.get("/icon-192.png")
async def icon_192():
    return FileResponse(_STATIC / "icon-192.png", media_type="image/png")


@router.get("/icon-512.png")
async def icon_512():
    return FileResponse(_STATIC / "icon-512.png", media_type="image/png")


# ====================== Memory browser ======================
@router.get("/api/facts", dependencies=[Depends(auth.authenticate)])
async def list_facts(query: str = ""):
    async with SessionLocal() as db:
        if query.strip():
            hits = await memory.semantic_recall(db, query, k=20)
            return [{"id": f.id, "content": f.content,
                     "score": round(s, 3) if s is not None else None,
                     "created_at": f.created_at.isoformat()} for f, s in hits]
        rows = (await db.execute(
            select(Fact).order_by(Fact.created_at.desc()).limit(50)
        )).scalars().all()
        return [{"id": r.id, "content": r.content, "score": None,
                 "created_at": r.created_at.isoformat()} for r in rows]


@router.delete("/api/facts/{fact_id}", dependencies=[Depends(auth.authenticate)])
async def delete_fact(fact_id: str):
    async with SessionLocal() as db:
        row = await db.get(Fact, fact_id)
        if row is None:
            raise HTTPException(404, "No such fact.")
        await db.delete(row)
        await db.commit()
    return {"ok": True}


# ====================== Tasks ======================
class GoalRequest(BaseModel):
    goal: str


@router.get("/api/tasks", dependencies=[Depends(auth.authenticate)])
async def list_tasks():
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(Task).order_by(Task.created_at.desc()).limit(20)
        )).scalars().all()
        return [{"id": t.id, "goal": t.goal, "status": t.status,
                 "steps": (t.steps or {}).get("steps", []),
                 "log": t.log[-3000:],
                 "created_at": t.created_at.isoformat()} for t in rows]


@router.post("/api/tasks")
async def create_task(req: GoalRequest, identity: str = Depends(auth.authenticate)):
    await ratelimit.guard_identity(identity, "tasks", limit=10, window_s=3600)
    task_id = await tasks.start(req.goal)
    return {"id": task_id}


# ====================== Approvals ======================
class ApprovalDecision(BaseModel):
    approve: bool


@router.get("/api/approvals/pending", dependencies=[Depends(auth.authenticate)])
async def pending_approvals():
    return approvals.pending_list()


@router.post("/api/approvals/{approval_id}", dependencies=[Depends(auth.authenticate)])
async def decide_approval(approval_id: str, decision: ApprovalDecision):
    return {"ok": approvals.resolve(approval_id, decision.approve)}


# ====================== Push ======================
class SubscriptionIn(BaseModel):
    subscription: dict


@router.get("/api/push/key", dependencies=[Depends(auth.authenticate)])
async def push_key():
    return {"key": push.public_key()}


@router.post("/api/push/subscribe", dependencies=[Depends(auth.authenticate)])
async def push_subscribe(req: SubscriptionIn):
    await push.save_subscription(req.subscription)
    return {"ok": True}
<<<<<<< HEAD


@router.get("/api/mcp/status", dependencies=[Depends(auth.authenticate)])
async def mcp_status():
    """Which MCP servers are connected and what tools they exposed."""
    return {"servers": mcp_client.status()}


# ====================== Desktop agent bridge ======================
class AgentResult(BaseModel):
    command_id: str
    output: str


@router.get("/api/desktop/poll", dependencies=[Depends(auth.authenticate)])
async def desktop_poll():
    """The laptop agent long-polls this for the next approved command."""
    cmd = await desktop_bridge.next_command()
    return cmd or {"id": None}


@router.post("/api/desktop/result", dependencies=[Depends(auth.authenticate)])
async def desktop_result(r: AgentResult):
    return {"ok": desktop_bridge.deliver_result(r.command_id, r.output)}


@router.get("/api/desktop/status", dependencies=[Depends(auth.authenticate)])
async def desktop_status():
    return {"online": desktop_bridge.agent_online()}
=======
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c

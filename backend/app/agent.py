"""
The agentic loop, server edition: an async generator that yields UI
events while it works. The same generator powers both the REST endpoint
(which just collects everything) and the WebSocket (which forwards each
event live) — one brain, two transports.

Event shapes:
  {"type": "token",  "data": "..."}            visible text, as it streams
  {"type": "tool",   "data": {"name", "args"}} a tool is being executed
  {"type": "model",  "data": "openrouter/free"} which provider answered
  {"type": "done",   "data": full_reply}
  {"type": "error",  "data": message}
"""
import json

from sqlalchemy import select

from . import events, llm, memory, tools
from .config import settings
from .db import ChatSession, Message


def _system_prompt(memory_block: str | None = None) -> str:
    base = (
        f"You are {settings.assistant_name}, a personal AI assistant in the spirit of "
        f"J.A.R.V.I.S. Address the user as \"{settings.user_title}\". Be concise, dry-witted, "
        "and useful. Use the remember tool when the user shares durable facts about "
        "themselves, and the recall tool when past context would help. If a tool result "
        "starts with DENIED, accept it gracefully and never retry the same action."
    )
    if memory_block:
        base += "\n\n" + memory_block + "\nUse these naturally when relevant; never recite the list."
    return base


async def _load_history(db, session_id: str) -> list[dict]:
    stmt = (
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.desc())
        .limit(settings.max_history_messages)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


async def ensure_session(db, session_id: str | None, first_message: str) -> str:
    if session_id:
        existing = await db.get(ChatSession, session_id)
        if existing:
            return existing.id
    session = ChatSession(title=first_message[:80] or "New conversation")
    db.add(session)
    await db.flush()
    return session.id


async def run_turn(db, session_id: str, user_text: str, tier_override: str | None = None):
    """Yield events for one conversational turn. Persists the user message
    and the final assistant reply; intermediate tool traffic goes to the
    audit log and event bus rather than the conversation history, which
    keeps history replay simple and provider-agnostic."""
    db.add(Message(session_id=session_id, role="user", content=user_text))

    remembered = None
    try:
        remembered = await memory.context_for(db, user_text)
    except Exception:
        pass  # memory trouble must never block a reply
    if remembered:
        yield {"type": "memory", "data": remembered["facts"]}

    messages = [{"role": "system",
                 "content": _system_prompt(remembered["block"] if remembered else None)}]
    messages += await _load_history(db, session_id)
    messages.append({"role": "user", "content": user_text})

    tier = llm.pick_tier(user_text, tier_override)
    chain = llm.chain_for(tier)
    schemas = tools.openai_schemas()
    final_text = ""

    try:
        for _round in range(settings.max_tool_rounds):
            acc = llm.Accumulated()
            answered_by = None
            async for spec, chunk in llm.stream_with_failover(chain, messages, schemas):
                if answered_by is None:
                    answered_by = spec
                    yield {"type": "model", "data": f"{spec.label}:{spec.model}"}
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue
                text = llm.apply_delta(acc, delta)
                if text:
                    yield {"type": "token", "data": text}

            calls = acc.ordered_tool_calls()
            if not calls:
                final_text = acc.content.strip()
                break

            # Record the assistant's tool request, then execute each call
            # through the security gate and feed results back.
            messages.append({
                "role": "assistant",
                "content": acc.content or "",
                "tool_calls": [
                    {"id": c["id"], "type": "function",
                     "function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in calls
                ],
            })
            for call in calls:
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                args.setdefault("session_id", session_id)
                yield {"type": "tool", "data": {"name": call["name"], "args": args}}
                result = await tools.run_tool(call["name"], args, db)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": result})
        else:
            final_text = "I seem to be stuck in a loop of my own making. Let us try that again."

    except Exception as e:
        await events.publish(events.AGENT_FAILED, {"session": session_id, "error": str(e)[:200]})
        yield {"type": "error", "data": f"Brain failure: {e}"}
        await db.commit()
        return

    db.add(Message(session_id=session_id, role="assistant", content=final_text))
    await db.commit()
    await events.publish(events.AGENT_REPLIED, {"session": session_id, "chars": len(final_text)})
    yield {"type": "done", "data": final_text}

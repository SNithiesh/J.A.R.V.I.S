"""
Event bus — Redis Streams, wired from day one (feedback item #4).

Phase 1 publishes; nothing consumes yet. That asymmetry is deliberate:
when the WebSocket fan-out (Phase 4) and notification workers (Phase 3)
arrive, the events they need are already flowing and nothing upstream
changes. Publishing is fire-and-forget — a down Redis must never break
a chat turn.
"""
import json

import redis.asyncio as aioredis

from .config import settings

STREAM = "jarvis.events"

# Topic names — shared vocabulary across every future consumer.
TASK_CREATED = "task.created"
TASK_FINISHED = "task.finished"
TOOL_EXECUTED = "tool.executed"
MEMORY_UPDATED = "memory.updated"
AGENT_REPLIED = "agent.replied"
AGENT_FAILED = "agent.failed"
TASK_STARTED = "task.started"
TASK_STEP = "task.step"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_RESOLVED = "approval.resolved"
REMINDER_FIRED = "reminder.fired"

_client: aioredis.Redis | None = None


def client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _client


async def publish(topic: str, payload: dict) -> None:
    try:
        await client().xadd(
            STREAM,
            {"topic": topic, "node": settings.node_name, "payload": json.dumps(payload)},
            maxlen=10_000,
            approximate=True,
        )
    except Exception:
        pass  # observability must never take down the conversation

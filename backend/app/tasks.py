"""
Background tasks (Phase 5) — the planner/executor.

A chat turn is a sprint; a TASK is a journey. start() returns immediately
with a task id while the work continues in the background:

    PLAN     smart tier turns the goal into 2-6 concrete steps (JSON,
             parsed as untrusted input — same paranoia as the distiller)
    EXECUTE  each step runs as its own tool-using mini-turn, with a
             running digest of earlier results as context
    REPORT   events stream the whole way (the Tasks tab watches live);
             the finish line fires a push notification to your pocket

Confirm-policy tools called DURING a task pause it on your phone's
Allow/Deny — the security gate doesn't care who's asking, chat or agent.

Also here: the scheduler loop — "remind me in 20 minutes" becomes a row
in scheduled_jobs; every 20 seconds we wake anything that's due.
"""
import asyncio
import datetime
import json
import re

from sqlalchemy import select

from . import events, hub, llm, push, tools
from .config import settings
from .db import ScheduledJob, SessionLocal, Task

_PLAN_SYSTEM = (
    "You are a planner. Break the user's goal into 2 to 6 concrete, sequential "
    "steps an AI assistant with tools (web fetching, memory, reminders) can "
    "actually do. Reply with ONLY a JSON array of short imperative strings. "
    "If the goal is trivially one action, reply with a single-element array."
)

_EXEC_SYSTEM = (
    f"You are {settings.assistant_name}'s background executor. Complete the given "
    "step using your tools when helpful. Be brief and factual; your output is a "
    "working note, not a chat reply. If a tool result starts with DENIED, accept "
    "it and continue without that action."
)


def parse_steps(raw: str) -> list[str]:
    """Model output -> clean step list. Tolerates fences and chatter."""
    if not raw:
        return []
    cleaned = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    steps = [s.strip() for s in data if isinstance(s, str) and 5 <= len(s.strip()) <= 300]
    return steps[:6]


async def start(goal: str) -> str:
    """Create the task row and launch the runner. Returns immediately."""
    goal = goal.strip()[:1000]
    async with SessionLocal() as db:
        task = Task(goal=goal)
        db.add(task)
        await db.commit()
        task_id = task.id
    asyncio.create_task(_run(task_id))
    return task_id


async def _run(task_id: str) -> None:
    async with SessionLocal() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return
        try:
            await hub.broadcast({"type": "task", "data": {"id": task_id, "status": "planning", "goal": task.goal}})
            await events.publish(events.TASK_STARTED, {"id": task_id, "goal": task.goal[:120]})

            raw = await llm.complete_with_failover(
                llm.chain_for("smart"),
                [{"role": "system", "content": _PLAN_SYSTEM},
                 {"role": "user", "content": task.goal}],
            )
            steps = parse_steps(raw) or [task.goal]  # no plan? the goal IS the step
            task.steps = {"steps": steps}
            task.status = "running"
            await db.commit()

            digest = ""
            for i, step in enumerate(steps, 1):
                await hub.broadcast({"type": "task", "data": {
                    "id": task_id, "status": "running", "goal": task.goal,
                    "step": i, "total": len(steps), "doing": step}})
                await events.publish(events.TASK_STEP, {"id": task_id, "step": i})
                result = await _run_step(step, digest, db)
                task.log += f"\n--- Step {i}: {step}\n{result}\n"
                digest = (digest + f"\nStep {i} result: {result}")[-2000:]
                await db.commit()

            task.status = "done"
            task.finished_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
            await hub.broadcast({"type": "task", "data": {"id": task_id, "status": "done", "goal": task.goal}})
            await push.notify_all("Task finished", task.goal[:90], "/")

        except Exception as e:
            task.status = "failed"
            task.log += f"\n!! failed: {e}"
            task.finished_at = datetime.datetime.now(datetime.timezone.utc)
            await db.commit()
            await hub.broadcast({"type": "task", "data": {"id": task_id, "status": "failed", "goal": task.goal}})
            await push.notify_all("Task failed", task.goal[:90], "/")


async def _run_step(step: str, digest: str, db, max_rounds: int = 4) -> str:
    """One tool-using mini-turn, non-streaming (nobody is watching tokens)."""
    sys = _EXEC_SYSTEM + (f"\n\nResults so far:{digest}" if digest else "")
    messages = [{"role": "system", "content": sys}, {"role": "user", "content": step}]
    for _ in range(max_rounds):
        msg = await llm.call_with_failover(llm.chain_for("fast"), messages, tools.openai_schemas())
        calls = msg.tool_calls or []
        if not calls:
            return (msg.content or "").strip() or "(no output)"
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": c.id, "type": "function",
                            "function": {"name": c.function.name,
                                         "arguments": c.function.arguments}} for c in calls],
        })
        for c in calls:
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await tools.run_tool(c.function.name, args, db)
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
    return "(step hit the tool-round limit)"


# ---------------- the scheduler ----------------
async def schedule(kind: str, payload: str, minutes: float) -> str:
    due = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    async with SessionLocal() as db:
        job = ScheduledJob(kind=kind, payload=payload[:1000], due_at=due)
        db.add(job)
        await db.commit()
        return job.id


async def scheduler_loop() -> None:
    """Every 20s: wake anything that's due. Reminders ring; goals launch."""
    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            async with SessionLocal() as db:
                due = (await db.execute(
                    select(ScheduledJob)
                    .where(ScheduledJob.status == "pending", ScheduledJob.due_at <= now)
                )).scalars().all()
                for job in due:
                    job.status = "done"
                    await db.commit()
                    if job.kind == "reminder":
                        await hub.broadcast({"type": "reminder", "data": job.payload})
                        await events.publish(events.REMINDER_FIRED, {"id": job.id})
                        await push.notify_all("⏰ Reminder", job.payload, "/")
                    elif job.kind == "goal":
                        await start(job.payload)
        except Exception as e:
            print(f"[scheduler] pass failed (non-fatal): {e}")
        await asyncio.sleep(20)

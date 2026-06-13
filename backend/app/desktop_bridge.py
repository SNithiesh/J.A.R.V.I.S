"""
Desktop-hands bridge (optional capability) — server side.

Lets your phone ask your laptop to DO something local (open an app, etc.)
while keeping the laptop with zero exposed ports. The flow:

  phone -> chat tool `desktop_action` (policy: confirm)
        -> Allow/Deny prompt on your phone           [the security gate]
        -> on Allow, command is queued here
        -> the laptop agent (local-agent/agent.py) POLLS this server,
           pulls the command, runs it locally, posts the result back
        -> result surfaces to the chat

Why polling, not pushing: the laptop dials OUT to the server (long-poll),
so the laptop never opens an inbound port. Same zero-exposure principle as
the whole design. The agent authenticates with the normal API key.

Single-laptop assumption keeps this a simple in-memory queue; the agent
token gates who may pull commands.
"""
import asyncio
import uuid

# pending commands waiting for the laptop agent to pull
_queue: "asyncio.Queue[dict]" = asyncio.Queue()
# command_id -> Future holding the result the agent posts back
_results: dict[str, asyncio.Future] = {}
# simple liveness: last time the agent polled
_last_seen: dict[str, float] = {"ts": 0.0}


async def submit(action: str, args: dict, timeout: float = 45) -> str:
    """Queue an (already-approved) command and await the laptop's result."""
    import time
    cmd_id = uuid.uuid4().hex
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _results[cmd_id] = fut
    await _queue.put({"id": cmd_id, "action": action, "args": args or {}})
    if time.time() - _last_seen["ts"] > 30:
        # be honest if no laptop is listening
        _results.pop(cmd_id, None)
        return ("The desktop agent isn't connected right now, so I can't reach your "
                "computer. Start local-agent on the laptop and try again.")
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return "The desktop command timed out (the laptop didn't respond)."
    finally:
        _results.pop(cmd_id, None)


async def next_command(wait: float = 25) -> dict | None:
    """Long-poll endpoint helper: the agent calls this to get the next command."""
    import time
    _last_seen["ts"] = time.time()
    try:
        return await asyncio.wait_for(_queue.get(), wait)
    except asyncio.TimeoutError:
        return None


def deliver_result(cmd_id: str, output: str) -> bool:
    fut = _results.get(cmd_id)
    if fut and not fut.done():
        fut.set_result(output)
        return True
    return False


def agent_online() -> bool:
    import time
    return (time.time() - _last_seen["ts"]) < 30

"""
Tool manager + security gate, server edition.

Same model as the desktop app's tools.py/security.py, condensed:
every tool has a policy (auto / confirm / disabled), every execution
is audited, unknown tools fail safe.

Two deliberate Phase 1 properties:

- SERVER-SAFE ONLY. This node has no shell, file, or app-control tools.
  Computer control stays on the local node (the existing desktop agent),
  which joins as a delegated executor in Phase 3. A cloud box that can't
  touch your laptop can't be tricked into touching your laptop.

- MCP-READY SEAM (feedback item #1). register() is the single door into
  the registry. An MCP adapter in Phase 5 will discover a server's tools
  and call register() for each — which means external MCP tools get a
  policy and an audit trail exactly like native ones. No tool, however
  it arrived, bypasses the gate.
"""
import datetime
import ipaddress
import re
import socket
import urllib.parse
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from . import events
from .config import settings
from . import memory
from .db import AuditLog

AUTO, CONFIRM, DISABLED = "auto", "confirm", "disabled"


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    policy: str
    handler: Callable[..., Awaitable[str]]


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    """The only door into the registry — native tools, plugins, and future
    MCP adapters all enter here and inherit the same gate."""
    _REGISTRY[tool.name] = tool


def openai_schemas() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in _REGISTRY.values()
        if t.policy != DISABLED
    ]


def get_policy(name: str) -> str:
    tool = _REGISTRY.get(name)
    return tool.policy if tool else CONFIRM  # unknown -> fail safe, never fail open


async def _execute(name: str, args: dict, db) -> str:
    tool = _REGISTRY.get(name)
    if tool is None:
        return f"Unknown tool: {name}"
    try:
        return await tool.handler(args, db)
    except Exception as e:
        return f"Tool error in {name}: {e}"


async def run_tool(name: str, args: dict, db=None) -> str:
    args = args or {}
    policy = get_policy(name)

    if policy == DISABLED:
        outcome = f"DENIED: the {name} tool is disabled on this node."
    elif policy == CONFIRM:
        # Phase 4: confirm now means ASK. The call pauses here while the
        # request rings every screen and pocket; silence is refusal.
        from . import approvals
        approved = await approvals.request_and_wait(name, args, db)
        if approved:
            outcome = await _execute(name, args, db)
        else:
            outcome = f"DENIED: the user declined {name} (or didn't respond in time). Do not retry."
    else:
        outcome = await _execute(name, args, db)

    if db is not None:
        db.add(AuditLog(node=settings.node_name, tool=name, args=args, outcome=str(outcome)[:500]))
    await events.publish(events.TOOL_EXECUTED, {"tool": name, "outcome": str(outcome)[:200]})
    return outcome


# ====================== Built-in server-safe tools ======================
async def _get_time(_args: dict, _db) -> str:
    now = datetime.datetime.now()
    return now.strftime("It is %I:%M %p UTC on %A, %B %d, %Y.")


async def _remember(args: dict, db) -> str:
    if db is None:
        return "Memory is unavailable right now."
    content = str(args.get("fact", "")).strip()
    if not content:
        return "Nothing to remember — the fact was empty."
    fact = await memory.store_fact(db, content, session_id=args.get("session_id"))
    if fact is None:
        return "I already knew that (an equivalent fact is stored)."
    return f"Remembered: {content}"


async def _recall(args: dict, db) -> str:
    if db is None:
        return "Memory is unavailable right now."
    query = str(args.get("query", "")).strip()
    hits = await memory.semantic_recall(db, query, k=8)
    if not hits:
        return "No stored facts match that."
    lines = []
    for fact, score in hits:
        tag = f" (match {score:.0%})" if score is not None else ""
        lines.append(f"- {fact.content}{tag}")
    return "Stored facts:\n" + "\n".join(lines)


# ---------------- web fetching with an SSRF guard ----------------
_BLOCKED_NETS = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
    "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16",
    "::1/128", "fc00::/7", "fe80::/10",
)]


def ip_is_blocked(ip: str) -> bool:
    """True for any address that points back INTO our own networks.
    'Fetch http://192.168.1.1/admin' is the classic SSRF attack — a public
    fetcher must never be a periscope into private space."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    if addr.is_multicast or addr.is_reserved or addr.is_unspecified:
        return True
    return any(addr in net for net in _BLOCKED_NETS)


async def _url_blocked_reason(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "Only plain http/https URLs are allowed."
    try:
        infos = await __import__("asyncio").to_thread(
            socket.getaddrinfo, parsed.hostname, None
        )
    except OSError:
        return "That hostname does not resolve."
    for info in infos:
        if ip_is_blocked(info[4][0]):
            return "That address points into a private network — refused."
    return None


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_ANYTAG_RE = re.compile(r"<[^>]+>")


async def _fetch_url(args: dict, _db) -> str:
    url = str(args.get("url", "")).strip()
    reason = await _url_blocked_reason(url)
    if reason:
        return f"BLOCKED: {reason}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for _hop in range(3):  # follow redirects manually, re-checking each hop
                resp = await client.get(url, headers={"User-Agent": "JarvisBot/1.0"})
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    url = str(httpx.URL(url).join(resp.headers["location"]))
                    reason = await _url_blocked_reason(url)
                    if reason:
                        return f"BLOCKED after redirect: {reason}"
                    continue
                break
            if resp.status_code != 200:
                return f"Fetch failed: HTTP {resp.status_code}"
            text = _TAG_RE.sub(" ", resp.text)
            text = _ANYTAG_RE.sub(" ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:4000] or "(page had no readable text)"
    except Exception as e:
        return f"Fetch failed: {e}"


async def _forget(args: dict, db) -> str:
    if db is None:
        return "Memory is unavailable right now."
    from . import memory
    query = str(args.get("query", "")).strip()
    hits = await memory.semantic_recall(db, query, k=1)
    if not hits:
        return "No stored fact matches that."
    fact, score = hits[0]
    if score is not None and score < 0.55:
        return f"Closest fact is '{fact.content}' but the match is weak — not deleting."
    content = fact.content
    await db.delete(fact)
    return f"Forgot: {content}"


async def _remind_me(args: dict, _db) -> str:
    from . import tasks
    minutes = float(args.get("minutes", 0))
    message = str(args.get("message", "")).strip() or "Reminder"
    if not (0.2 <= minutes <= 60 * 24 * 30):
        return "Reminder must be between ~12 seconds and 30 days from now."
    await tasks.schedule("reminder", message, minutes)
    return f"Reminder set: '{message}' in {minutes:g} minute(s). It will ring as a notification."


<<<<<<< HEAD
async def _desktop_action(args: dict, _db) -> str:
    """Forward an approved command to the laptop agent and return its result."""
    from . import desktop_bridge
    action = str(args.get("action", "")).strip()
    if not action:
        return "No desktop action specified."
    return await desktop_bridge.submit(action, args.get("params") or {})


=======
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
async def _start_background_task(args: dict, _db) -> str:
    from . import tasks
    goal = str(args.get("goal", "")).strip()
    if len(goal) < 5:
        return "The goal is too vague to plan."
    task_id = await tasks.start(goal)
    return (f"Background task {task_id[:8]} started. I'll plan it into steps, work "
            "through them, and send a notification when done — check the Tasks tab.")


def register_builtins() -> None:
    register(Tool(
        name="get_time",
        description="Get the current date and time.",
        parameters={"type": "object", "properties": {}},
        policy=AUTO,
        handler=_get_time,
    ))
    register(Tool(
        name="remember",
        description="Store a durable fact about the user in long-term memory, e.g. preferences, deadlines, project details.",
        parameters={
            "type": "object",
            "properties": {"fact": {"type": "string", "description": "The fact, phrased as a standalone sentence."}},
            "required": ["fact"],
        },
        policy=AUTO,
        handler=_remember,
    ))
    register(Tool(
        name="recall",
        description="Search long-term memory for stored facts about the user.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keyword(s) to search for. Empty returns the most recent facts."}},
        },
        policy=AUTO,
        handler=_recall,
    ))


def register_phase45() -> None:
    register(Tool(
        name="fetch_url",
        description="Fetch a public web page and return its readable text (max ~4000 chars). Use for research and reading articles/docs the user mentions.",
        parameters={"type": "object",
                    "properties": {"url": {"type": "string", "description": "Full http(s) URL"}},
                    "required": ["url"]},
        policy=AUTO,
        handler=_fetch_url,
    ))
    register(Tool(
        name="forget",
        description="Delete one stored fact from long-term memory that best matches the query. Destructive — requires the user's approval.",
        parameters={"type": "object",
                    "properties": {"query": {"type": "string", "description": "What to forget"}},
                    "required": ["query"]},
        policy=CONFIRM,
        handler=_forget,
    ))
    register(Tool(
        name="remind_me",
        description="Schedule a reminder that arrives as a push notification on the user's devices.",
        parameters={"type": "object",
                    "properties": {"minutes": {"type": "number", "description": "How many minutes from now"},
                                   "message": {"type": "string", "description": "Reminder text"}},
                    "required": ["minutes", "message"]},
        policy=AUTO,
        handler=_remind_me,
    ))
    register(Tool(
<<<<<<< HEAD
        name="desktop_action",
        description="Perform an action on the user's LAPTOP: open an app/website, get a system report, set a local timer, etc. Use action names like 'open_application', 'open_website', 'system_report', 'search_web'. Requires the user's approval and a running desktop agent.",
        parameters={"type":"object","properties":{
            "action":{"type":"string","description":"e.g. open_application, open_website, system_report, search_web"},
            "params":{"type":"object","description":"arguments for the action, e.g. {\"name\":\"spotify\"} or {\"url\":\"github.com\"}"}},
            "required":["action"]},
        policy=CONFIRM,
        handler=_desktop_action,
    ))
    register(Tool(
=======
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
        name="start_background_task",
        description="Start a multi-step background task (research, drafting, comparisons) that runs while the conversation continues. Costs multiple model calls — requires the user's approval.",
        parameters={"type": "object",
                    "properties": {"goal": {"type": "string", "description": "The goal, fully specified"}},
                    "required": ["goal"]},
        policy=CONFIRM,
        handler=_start_background_task,
    ))


register_builtins()
register_phase45()

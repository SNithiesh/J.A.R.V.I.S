"""
MCP adapter (optional capability).

This is the USB-C port for AI tools. It launches configured MCP servers,
asks each "what tools do you have?", and registers every discovered tool
into Jarvis's OWN registry (tools.py) — which means each one automatically
inherits the security gate (auto / confirm / disabled) and the audit log.
No MCP tool, however it arrives, bypasses that gate.

Design decisions worth understanding:

- PERSISTENT SESSIONS. Each server is launched once and its session kept
  alive in a background task, rather than spawned per call. Spawning a
  Node/Python subprocess on every tool use would be slow and would lose
  any server-side state. We hold the connection open and route calls to it.

- ONE BACKGROUND TASK PER SERVER owns that server's async context
  (stdio_client + ClientSession are async context managers that must be
  entered and exited on the same task). A request handler can't hold them
  open across calls, so each server runs in its own long-lived task and we
  talk to it through an asyncio.Queue. This is the standard pattern for
  bridging "open once, call many times" onto MCP's context-manager API.

- FAIL SOFT. A server that won't start, or a missing MCP SDK, logs a
  warning and is skipped. Jarvis runs fine with zero MCP servers; this is
  pure enrichment.

- SECURITY POLICY PER SERVER. Each server config declares a default policy
  for its tools. Anything that reads is usually 'auto'; anything that writes
  or deletes should be 'confirm' so it pops the Allow/Deny prompt. Unknown
  tools fall back to 'confirm' (fail safe) via tools.get_policy.

Servers are declared in mcp_config.json (see load_config). Example entry:
  {
    "name": "filesystem",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data/jarvis"],
    "default_policy": "confirm",
    "tool_policies": {"read_file": "auto", "list_directory": "auto"}
  }
"""
import asyncio
import json
import pathlib

from . import tools
from .config import settings

CONFIG_PATH = pathlib.Path(__file__).parent.parent / "mcp_config.json"

# name -> {"queue": asyncio.Queue, "task": Task, "tools": [names], "status": str}
_servers: dict[str, dict] = {}


def load_config() -> list[dict]:
    """Read mcp_config.json. Missing or malformed -> no servers (fine)."""
    if not CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(CONFIG_PATH.read_text())
        servers = data.get("servers", [])
        return [s for s in servers if s.get("enabled", True)]
    except Exception as e:
        print(f"[mcp] could not read mcp_config.json: {e}")
        return []


def status() -> list[dict]:
    """For the API/UI: which MCP servers are connected and what they exposed."""
    return [
        {"name": name, "status": s["status"], "tools": s.get("tools", [])}
        for name, s in _servers.items()
    ]


async def _server_task(cfg: dict):
    """Owns one MCP server's lifecycle: connect, register its tools, then
    serve call requests off a queue until cancelled."""
    name = cfg["name"]
    queue: asyncio.Queue = _servers[name]["queue"]
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        _servers[name]["status"] = "mcp-sdk-not-installed"
        print("[mcp] the 'mcp' package isn't installed; skipping MCP servers.")
        return

    params = StdioServerParameters(
        command=cfg["command"],
        args=cfg.get("args", []),
        env=cfg.get("env") or None,
    )
    default_policy = cfg.get("default_policy", tools.CONFIRM)
    tool_policies = cfg.get("tool_policies", {})

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()

                # Register each discovered tool into Jarvis's gate-guarded registry.
                names = []
                for t in listed.tools:
                    policy = tool_policies.get(t.name, default_policy)
                    _register_proxy(name, queue, t, policy)
                    names.append(t.name)
                _servers[name]["tools"] = names
                _servers[name]["status"] = "connected"
                print(f"[mcp] '{name}' connected — {len(names)} tool(s): {', '.join(names) or 'none'}")

                # Serve calls until cancelled.
                while True:
                    tool_name, args, fut = await queue.get()
                    try:
                        result = await session.call_tool(tool_name, args or {})
                        # MCP returns a list of content blocks; join text parts.
                        parts = []
                        for block in (result.content or []):
                            txt = getattr(block, "text", None)
                            if txt:
                                parts.append(txt)
                        fut.set_result("\n".join(parts) or "(no textual output)")
                    except Exception as e:
                        fut.set_result(f"MCP tool error ({name}/{tool_name}): {e}")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        _servers[name]["status"] = f"failed: {e}"
        print(f"[mcp] '{name}' failed to start: {e}")


def _register_proxy(server_name: str, queue: "asyncio.Queue", mcp_tool, policy: str):
    """Wrap one MCP tool as a Jarvis Tool whose handler forwards the call to
    the owning server's task via the queue, then waits for the result."""
    # Namespacing avoids collisions between servers/native tools.
    jarvis_name = f"{server_name}__{mcp_tool.name}"

    async def handler(args: dict, _db=None) -> str:
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        await queue.put((mcp_tool.name, args, fut))
        try:
            return await asyncio.wait_for(fut, timeout=60)
        except asyncio.TimeoutError:
            return f"MCP tool {jarvis_name} timed out."

    schema = getattr(mcp_tool, "inputSchema", None) or {"type": "object", "properties": {}}
    tools.register(tools.Tool(
        name=jarvis_name,
        description=(mcp_tool.description or f"{mcp_tool.name} via {server_name}")[:1024],
        parameters=schema,
        policy=policy,
        handler=handler,
    ))


async def start_all():
    """Launch every configured MCP server as its own background task."""
    configs = load_config()
    if not configs:
        print("[mcp] no servers configured (mcp_config.json absent or empty).")
        return
    for cfg in configs:
        name = cfg.get("name")
        if not name or not cfg.get("command"):
            continue
        _servers[name] = {"queue": asyncio.Queue(), "task": None,
                          "tools": [], "status": "starting"}
        _servers[name]["task"] = asyncio.create_task(_server_task(cfg))
    # give them a moment to connect so status() is meaningful soon after boot
    await asyncio.sleep(0)


async def stop_all():
    for s in _servers.values():
        task = s.get("task")
        if task:
            task.cancel()
    _servers.clear()

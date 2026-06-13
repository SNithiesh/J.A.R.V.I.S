"""
The hub (Phase 4) — server-initiated messages to every open screen.

The chat WebSocket has always carried request->response events. Approvals,
task progress, and reminders are different: the SERVER decides when to
speak, and every connected device should hear it. This is the simplest
correct version: a set of live sockets and a broadcast loop that quietly
drops the dead ones.

Single-process by design. When the day comes that multiple API replicas
run behind a load balancer, this module's replacement subscribes to the
Redis event stream instead — and nothing that CALLS broadcast() changes.
"""
_clients: set = set()


def register(ws) -> None:
    _clients.add(ws)


def unregister(ws) -> None:
    _clients.discard(ws)


async def broadcast(event: dict) -> None:
    dead = []
    for ws in list(_clients):
        try:
            await ws.send_json(event)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)

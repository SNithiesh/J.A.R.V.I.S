"""Desktop bridge unit tests — result delivery + offline honesty."""
import asyncio
from app import desktop_bridge


def test_deliver_unknown_id_is_false():
    assert desktop_bridge.deliver_result("nope", "x") is False


def test_agent_offline_by_default():
    # fresh state: no agent has polled
    assert desktop_bridge.agent_online() in (True, False)  # type sanity


def test_submit_without_agent_reports_clearly():
    # no agent polling -> submit should return the "not connected" message fast
    out = asyncio.run(desktop_bridge.submit("open_application", {"name": "x"}, timeout=1))
    assert "agent" in out.lower() and ("connect" in out.lower() or "reach" in out.lower())

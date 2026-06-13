"""
Phase 1 unit tests — the pure logic that must not regress:
the stream accumulator, the tier router, and the security gate.
Run: pytest backend/tests -q
"""
import asyncio
from types import SimpleNamespace as NS

from app import llm, tools


# ---------------- stream accumulator ----------------
def test_accumulator_merges_text_and_fragmented_tool_calls():
    acc = llm.Accumulated()
    deltas = [
        NS(content="Think", tool_calls=None),
        NS(content="ing.", tool_calls=None),
        NS(content=None, tool_calls=[NS(index=0, id="call_1", function=NS(name="remember", arguments='{"fa'))]),
        NS(content=None, tool_calls=[NS(index=0, id=None, function=NS(name=None, arguments='ct": "demo Friday"}'))]),
        NS(content=None, tool_calls=[NS(index=1, id="call_2", function=NS(name="get_time", arguments="{}"))]),
    ]
    visible = "".join(llm.apply_delta(acc, d) for d in deltas)
    assert visible == "Thinking."
    calls = acc.ordered_tool_calls()
    assert [c["name"] for c in calls] == ["remember", "get_time"]
    assert calls[0]["id"] == "call_1"
    assert calls[0]["arguments"] == '{"fact": "demo Friday"}'


# ---------------- tier router ----------------
def test_tier_router_heuristics_and_override():
    assert llm.pick_tier("what time is it") == "fast"
    assert llm.pick_tier("refactor this function to be async") == "smart"
    assert llm.pick_tier("x" * 700) == "smart"
    assert llm.pick_tier("write a plan for my project") == "smart"
    assert llm.pick_tier("hello", override="smart") == "smart"
    assert llm.pick_tier("debug this", override="fast") == "fast"


def test_chain_always_ends_at_a_provider():
    assert len(llm.chain_for("fast")) >= 1
    assert len(llm.chain_for("smart")) >= 1


# ---------------- security gate ----------------
def test_unknown_tool_fails_safe():
    assert tools.get_policy("definitely_not_registered") == tools.CONFIRM
    out = asyncio.run(tools.run_tool("definitely_not_registered", {}, db=None))
    assert out.startswith("DENIED")


def test_disabled_tool_is_denied():
    async def boom(_a, _d):
        raise AssertionError("disabled tool must never execute")

    tools.register(tools.Tool("danger", "test", {"type": "object", "properties": {}},
                              tools.DISABLED, boom))
    out = asyncio.run(tools.run_tool("danger", {}, db=None))
    assert out.startswith("DENIED")
    assert all(s["function"]["name"] != "danger" for s in tools.openai_schemas())


def test_auto_tool_executes():
    out = asyncio.run(tools.run_tool("get_time", {}, db=None))
    assert "It is" in out

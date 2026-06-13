"""
Phase 4+5 unit tests — the logic that must not regress: the plan parser,
the SSRF guard's IP classification, and the approval lifecycle.
Run: pytest backend/tests -q
"""
import asyncio

import pytest

from app import approvals, tasks, tools


# ---------------- planner output parsing ----------------
def test_parse_steps_clean_and_messy():
    assert tasks.parse_steps('["Fetch the page", "Summarise it", "Save key facts"]') == [
        "Fetch the page", "Summarise it", "Save key facts"]
    messy = 'Here is the plan:\n```json\n["Step one here", "Step two here"]\n```'
    assert tasks.parse_steps(messy) == ["Step one here", "Step two here"]


def test_parse_steps_rejects_garbage_and_caps():
    assert tasks.parse_steps("") == []
    assert tasks.parse_steps("not json") == []
    assert tasks.parse_steps('{"x":1}') == []
    big = "[" + ",".join(f'"step number {i} text"' for i in range(12)) + "]"
    assert len(tasks.parse_steps(big)) == 6


# ---------------- SSRF guard ----------------
def test_ssrf_blocks_private_and_loopback():
    for bad in ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.9.9",
                "169.254.1.1", "0.0.0.0", "::1"]:
        assert tools.ip_is_blocked(bad) is True, bad


def test_ssrf_allows_public():
    for ok in ["8.8.8.8", "1.1.1.1", "93.184.216.34"]:
        assert tools.ip_is_blocked(ok) is False, ok


def test_ssrf_blocks_malformed():
    assert tools.ip_is_blocked("not-an-ip") is True


@pytest.mark.asyncio
async def test_url_reason_rejects_non_http():
    assert await tools._url_blocked_reason("ftp://example.com") is not None
    assert await tools._url_blocked_reason("file:///etc/passwd") is not None


# ---------------- approval lifecycle ----------------
@pytest.mark.asyncio
async def test_approval_resolved_allow():
    async def approve_soon(aid):
        await asyncio.sleep(0.05)
        assert approvals.resolve(aid, True) is True

    # Pre-seed an id by racing a resolver against a short wait.
    holder = {}

    async def run():
        # capture the generated id via the pending list right after creation
        task = asyncio.create_task(approvals.request_and_wait("forget", {"q": "x"}, db=None, timeout=2))
        await asyncio.sleep(0.01)
        pend = approvals.pending_list()
        assert len(pend) == 1
        holder["id"] = pend[0]["id"]
        await approve_soon(holder["id"])
        return await task

    assert await run() is True


@pytest.mark.asyncio
async def test_approval_times_out_to_denied():
    result = await approvals.request_and_wait("forget", {"q": "x"}, db=None, timeout=0.1)
    assert result is False  # silence is refusal


@pytest.mark.asyncio
async def test_resolve_unknown_id_is_false():
    assert approvals.resolve("nonexistent", True) is False

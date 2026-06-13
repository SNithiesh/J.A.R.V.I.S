"""
Phase 2 unit tests — the pure logic of semantic memory.
Run: pytest backend/tests -q
"""
import asyncio

from app import memory


# ---------------- distiller output parsing ----------------
def test_parse_fact_list_handles_clean_json():
    assert memory.parse_fact_list('["User codes in Python", "Demo is Friday"]') == [
        "User codes in Python", "Demo is Friday",
    ]


def test_parse_fact_list_strips_code_fences_and_chatter():
    raw = 'Sure! Here you go:\n```json\n["User lives in Bengaluru"]\n```\nHope that helps!'
    assert memory.parse_fact_list(raw) == ["User lives in Bengaluru"]


def test_parse_fact_list_rejects_garbage():
    assert memory.parse_fact_list("") == []
    assert memory.parse_fact_list("no json here") == []
    assert memory.parse_fact_list('{"not": "a list"}') == []
    assert memory.parse_fact_list('[1, 2, {"x": 3}]') == []      # non-strings dropped
    assert memory.parse_fact_list('["long enough fact", "abc"]') == ["long enough fact"]


def test_parse_fact_list_caps_count_and_length():
    many = "[" + ",".join(f'"fact number {i} about user"' for i in range(20)) + "]"
    assert len(memory.parse_fact_list(many)) == 8
    huge = '["' + "x" * 500 + '"]'
    assert memory.parse_fact_list(huge) == []


# ---------------- context formatting ----------------
def test_format_block_lists_facts():
    block = memory.format_block(["Demo is Friday", "Prefers Python"])
    assert "long-term memory" in block.lower()
    assert "- Demo is Friday" in block
    assert "- Prefers Python" in block


# ---------------- embedding wrapper ----------------
def test_embed_runs_model_off_the_event_loop(monkeypatch):
    class FakeModel:
        def embed(self, texts):
            return [[0.5] * 384 for _ in texts]

    monkeypatch.setattr(memory, "_get_model", lambda: FakeModel())
    vecs = asyncio.run(memory.embed(["alpha", "beta"]))
    assert len(vecs) == 2
    assert len(vecs[0]) == 384
    assert isinstance(vecs[0][0], float)

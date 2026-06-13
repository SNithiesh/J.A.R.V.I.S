"""
Semantic memory (Phase 2).

Every fact gets a 384-dim embedding from a local model (fastembed /
bge-small — ONNX on CPU, no GPU, no API cost, works offline). Recall
is cosine similarity in pgvector, so "when is my presentation?" finds
a fact stored as "demo on Friday" — meaning-match, not word-match.

Design properties worth knowing:

- DEGRADES, NEVER DIES. If the embedding model can't load (first-boot
  download blocked, low disk), every function falls back to the Phase 1
  keyword path. Memory gets dumber, the assistant stays up.
- DEDUP BY MEANING. Storing a fact first checks for an existing fact
  with similarity >= memory_dedup_similarity, so the distiller can run
  forever without filling the table with rephrasings.
- THE DISTILLER. A background task that periodically reads recent
  conversation and extracts durable facts via the fast/free model tier.
  This is how Jarvis learns about you without being told "remember".
  Toggle with DISTILL_ENABLED in .env.
"""
import asyncio
import datetime
import json
import re

from sqlalchemy import select

from . import events
from .config import settings
from .db import Fact, KVStore, Message, SessionLocal

# ---------------- embeddings ----------------
_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # lazy: importing the app never loads ONNX
        _model = TextEmbedding(settings.embedding_model)
    return _model


def _embed_sync(texts: list[str]) -> list[list[float]]:
    return [list(map(float, vec)) for vec in _get_model().embed(texts)]


async def embed(texts: list[str]) -> list[list[float]]:
    """CPU-bound ONNX inference, pushed off the event loop."""
    return await asyncio.to_thread(_embed_sync, texts)


# ---------------- store / recall ----------------
async def _vector_hits(db, qvec: list[float], k: int, min_similarity: float):
    dist = Fact.embedding.cosine_distance(qvec)
    stmt = (
        select(Fact, dist.label("d"))
        .where(Fact.embedding.is_not(None))
        .order_by(dist)
        .limit(k)
    )
    rows = (await db.execute(stmt)).all()
    return [(row.Fact, 1.0 - row.d) for row in rows if (1.0 - row.d) >= min_similarity]


async def store_fact(db, content: str, session_id: str | None = None, dedup: bool = True):
    """Embed + insert. Returns the Fact, or None if empty/duplicate."""
    content = (content or "").strip()
    if not content:
        return None
    vec = None
    try:
        vec = (await embed([content]))[0]
    except Exception:
        pass  # store without embedding; backfill picks it up later
    if dedup and vec is not None:
        hits = await _vector_hits(db, vec, k=1, min_similarity=settings.memory_dedup_similarity)
        if hits:
            return None  # we already know this, phrased some way
    fact = Fact(content=content, source_session=session_id, embedding=vec)
    db.add(fact)
    await events.publish(events.MEMORY_UPDATED, {"fact": content[:120]})
    return fact


async def semantic_recall(db, query: str, k: int | None = None,
                          min_similarity: float | None = None):
    """Returns [(Fact, similarity|None)]. Vector search first; keyword fallback."""
    k = k or settings.memory_top_k
    ms = settings.memory_min_similarity if min_similarity is None else min_similarity
    query = (query or "").strip()

    try:
        if query:
            qvec = (await embed([query]))[0]
            hits = await _vector_hits(db, qvec, k=k, min_similarity=ms)
            if hits:
                return hits
    except Exception:
        pass  # embeddings unavailable -> fall through to keywords

    stmt = select(Fact).order_by(Fact.created_at.desc()).limit(k)
    if query:
        stmt = (
            select(Fact)
            .where(Fact.content.ilike(f"%{query}%"))
            .order_by(Fact.created_at.desc())
            .limit(k)
        )
    rows = (await db.execute(stmt)).scalars().all()
    return [(r, None) for r in rows]


def format_block(facts: list[str]) -> str:
    return (
        "Long-term memory — things you know about the user from past conversations:\n"
        + "\n".join(f"- {f}" for f in facts)
    )


async def context_for(db, user_text: str):
    """Ambient retrieval for the agent loop: relevant memories for this turn,
    or None. This is RAG-in-the-loop — the model doesn't have to think to ask."""
    hits = await semantic_recall(db, user_text)
    relevant = [f.content for f, score in hits if score is not None]
    if not relevant:
        return None
    return {"facts": relevant, "block": format_block(relevant)}


async def backfill_embeddings(db, batch: int = 256) -> int:
    """Embed any facts that predate Phase 2 (or were stored while offline)."""
    rows = (await db.execute(
        select(Fact).where(Fact.embedding.is_(None)).limit(batch)
    )).scalars().all()
    if not rows:
        return 0
    vecs = await embed([r.content for r in rows])
    for row, vec in zip(rows, vecs):
        row.embedding = vec
    return len(rows)


# ---------------- key/value state ----------------
async def get_kv(db, key: str) -> str | None:
    row = await db.get(KVStore, key)
    return row.value if row else None


async def set_kv(db, key: str, value: str) -> None:
    row = await db.get(KVStore, key)
    if row is None:
        db.add(KVStore(key=key, value=value))
    else:
        row.value = value


# ---------------- the distiller ----------------
_DISTILL_SYSTEM = (
    "You extract durable facts about the user from a chat transcript. "
    "Durable means: preferences, deadlines, projects, skills, people, decisions — "
    "things worth knowing a month from now. Ignore small talk, questions, and the "
    "assistant's own remarks. Reply with ONLY a JSON array of short standalone "
    "sentences about the user, e.g. [\"User's project demo is on Friday\"]. "
    "Reply [] if nothing qualifies."
)


def parse_fact_list(raw: str) -> list[str]:
    """Tolerant parser for model output: strips code fences, finds the JSON
    array, keeps only sane-length strings, caps the count."""
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
    out = []
    for item in data:
        if isinstance(item, str):
            s = item.strip()
            if 5 <= len(s) <= 300:
                out.append(s)
    return out[:8]


async def distill_once(db) -> int:
    """Read everything said since the last run, extract facts, store new ones."""
    from . import llm  # local import avoids a cycle at module load

    last_raw = await get_kv(db, "distill_last")
    last = (
        datetime.datetime.fromisoformat(last_raw)
        if last_raw
        else datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    )
    now = datetime.datetime.now(datetime.timezone.utc)

    rows = (await db.execute(
        select(Message).where(Message.created_at > last)
        .order_by(Message.created_at).limit(400)
    )).scalars().all()
    transcript = "\n".join(f"{m.role}: {m.content[:400]}" for m in rows)[:8000]

    await set_kv(db, "distill_last", now.isoformat())
    if len(transcript) < 200:
        await db.commit()
        return 0

    raw = await llm.complete_with_failover(
        llm.chain_for("fast"),
        [{"role": "system", "content": _DISTILL_SYSTEM},
         {"role": "user", "content": transcript}],
    )
    stored = 0
    for fact in parse_fact_list(raw):
        if await store_fact(db, fact, dedup=True) is not None:
            stored += 1
    await db.commit()
    if stored:
        await events.publish(events.MEMORY_UPDATED, {"distilled": stored})
    return stored


async def distill_loop() -> None:
    await asyncio.sleep(90)  # let the stack settle after boot
    while True:
        try:
            async with SessionLocal() as db:
                stored = await distill_once(db)
                if stored:
                    print(f"[memory] distilled {stored} new fact(s) from recent chat")
        except Exception as e:
            print(f"[memory] distill pass failed: {e}")
        await asyncio.sleep(settings.distill_interval_hours * 3600)

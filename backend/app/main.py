"""
JARVIS server — Phase 1 core.
Run the stack:  docker compose up --build
Then:           curl -X POST localhost:8000/api/chat \
                  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
                  -d '{"message": "remember that my demo is on Friday"}'
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

<<<<<<< HEAD
from . import mcp_client, memory, push, tasks
=======
from . import memory, push, tasks
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
from .config import settings
from .db import Base, SessionLocal, engine
from .auth import router as auth_router
from .routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS facts_embedding_hnsw "
            "ON facts USING hnsw (embedding vector_cosine_ops)"
        ))
    # Give pre-Phase-2 facts their embeddings (also catches facts stored offline).
    try:
        async with SessionLocal() as db:
            done = await memory.backfill_embeddings(db)
            await db.commit()
            if done:
                print(f"[memory] backfilled embeddings for {done} fact(s)")
    except Exception as e:
        print(f"[memory] backfill skipped: {e}")
    try:
        await push.ensure_keys()      # VAPID pair: generated once, lives in kv_store
    except Exception as e:
        print(f"[push] disabled this boot: {e}")
    distiller = asyncio.create_task(memory.distill_loop()) if settings.distill_enabled else None
    scheduler = asyncio.create_task(tasks.scheduler_loop())
<<<<<<< HEAD
    try:
        await mcp_client.start_all()      # connect configured MCP servers
    except Exception as e:
        print(f"[mcp] startup skipped: {e}")
    yield
    await mcp_client.stop_all()
=======
    yield
>>>>>>> a5251db89176e88f796c8567ca2ed924368c254c
    scheduler.cancel()
    if distiller:
        distiller.cancel()
    await engine.dispose()


app = FastAPI(title="JARVIS server", version="0.1.0", lifespan=lifespan)

# Dev-friendly CORS; Phase 3 locks this to the PWA's origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(auth_router)

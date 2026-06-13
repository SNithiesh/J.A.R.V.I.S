# J.A.R.V.I.S. — Personal AI Assistant

A self-hosted, local-first AI assistant that runs on your own machine, reaches your phone securely from anywhere, remembers across conversations, acts on your computer with your approval, and extends through the open Model Context Protocol — built almost entirely on free and open-source software.

Think of it as a private, programmable alternative to a cloud assistant: your data stays on hardware you control, the "brain" is a model provider you choose, and every capability is gated behind a security layer you own.

---

## Why this project

Most AI assistants are someone else's cloud service. This one is built on a different premise: **you own the whole stack.** The same containerized system runs identically on a laptop or a cloud server — only an `.env` file differs — and no component knows or cares where it lives. That single design decision (location comes from configuration, never from code) is what makes it portable, testable, and honest about its boundaries.

It was built incrementally as a learning project, one capability at a time, with every layer tested before the next was added.

---

## What it does

- **Conversational AI with memory.** Chat by text or voice. It remembers facts across sessions using semantic search — ask "when is my presentation?" and it recalls the demo you mentioned days ago, matching by *meaning*, not keywords.
- **Reachable from your phone, anywhere, with nothing exposed.** An installable app (PWA) connects to your machine over an encrypted private network. No ports are opened to the public internet.
- **Background agents.** Hand it a multi-step goal; it plans the steps, works through them while you keep chatting, and notifies you when done.
- **Acts on your computer — with permission.** From your phone you can have it open apps or report system status on your laptop. Every consequential action triggers an Allow/Deny prompt on your phone before it runs.
- **Extensible via MCP.** Connects to the open Model Context Protocol ecosystem — filesystem access, web fetching, Git, GitHub, Google Calendar, and more — with every external tool inheriting the same security gate.
- **Reminders and scheduling** that push to your phone even when the app is closed.

---

## Architecture at a glance

```
Phone (installable PWA)
   |  encrypted private network (Tailscale / WireGuard), zero public ports
   v
FastAPI server -- tiered LLM router (with failover)
   |                 |- semantic memory  -> Postgres + pgvector
   |                 |- background agents -> planner / executor + scheduler
   |                 |- security gate     -> auto / confirm / disabled, audit-logged
   |                 |- MCP adapter       -> external tool servers
   |- Redis        -> events, rate limiting
   |- Desktop agent (on the laptop) -> executes approved local actions, opens no ports
```

**Core principle:** every tool — native, MCP, or desktop — passes through one security gate. Reads run silently; writes and deletes require explicit approval on the user's device. Nothing bypasses it.

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, async SQLAlchemy |
| Datastores | PostgreSQL + pgvector (semantic memory), Redis (events, rate limiting) |
| AI / embeddings | OpenRouter (pluggable LLM provider), local embeddings via fastembed |
| Auth | JWT with refresh-token rotation, bcrypt password hashing |
| Frontend | Installable PWA, Web Speech API (voice), Web Push, Three.js (3D UI) |
| Networking | Tailscale (WireGuard mesh), Caddy (HTTPS) for cloud deployment |
| Agents & tools | Hand-rolled planner/executor, Model Context Protocol adapter |
| Ops | Docker Compose, automated DB backups, GitHub Actions CI, Alembic migrations |

---

## Key engineering decisions

- **Location-independent by design.** No service hardcodes a hostname; all addresses come from environment variables, so the identical stack deploys to a laptop or a VPS unchanged.
- **The LLM is an interface, not a vendor.** A tiered router tries a preferred model, falls back through alternatives, and can fail over to a fully local model — so a single provider outage doesn't take the assistant down.
- **Security gate wraps every action.** Tool calls are classified `auto` (silent), `confirm` (asks the user), or `disabled` (hidden from the model), and every call is written to an audit log. The model proposes; the user disposes.
- **Zero public attack surface.** The machine running the assistant opens no inbound ports — it's reached over a private encrypted mesh, and the desktop agent dials *out* rather than listening.
- **Human-in-the-loop, literally.** Consequential operations pause server-side and wait on an approval that arrives as a prompt on the user's phone; silence is treated as refusal.

---

## Features in detail

**Memory.** Conversations and distilled facts are embedded locally and stored in pgvector. A background process periodically reviews recent chats and saves what matters, deduplicating by semantic similarity so the same fact isn't stored twice in different words.

**Security & auth.** Password login issues a short-lived access token plus a longer refresh token; the client renews silently. Redis-backed rate limiting protects both login (against guessing) and chat (against runaway usage), and fails *open* so an infrastructure hiccup never locks the owner out.

**Agents.** A planner turns a goal into concrete steps; an executor runs each as a tool-using sub-task, streaming progress to the UI and pushing a notification on completion.

**MCP integration.** A single adapter connects to any Model Context Protocol server over stdio, discovers its tools at runtime, and registers each into the assistant's own gate-guarded registry — so third-party tools are *safe to add*, not a backdoor.

**Operations.** Nightly automated database backups with a tested restore path, a CI workflow that runs the full test suite on every push, and Alembic migrations for schema evolution.

---

## Getting started

> Requires Docker Desktop. A free OpenRouter API key provides the model; everything else is free and self-hosted.

```bash
cp .env.example .env          # set OPENROUTER_API_KEY and a random API_KEY
docker compose up -d --build  # first build downloads the embedding model
```

Open `http://localhost:8000` in a browser, claim the owner account on first run, and you're chatting.

**To reach it from your phone** (free, no public exposure): install Tailscale on both devices, then run `tailscale serve --bg 8000` to get an HTTPS address on your machine's private network. Open it on your phone, sign in, and install it to your home screen.

**To deploy to the cloud** (optional, always-on): the same stack runs on a small VPS with real HTTPS — see `DEPLOY.md`.

---

## Documentation

- `STATUS.md` — full feature inventory and honest caveats
- `DEPLOY.md` — cloud deployment runbook
- `deploy/google-setup.md` — enabling Gmail / Calendar
- `local-agent/README.md` — the desktop "hands" agent
- `docs/PHASE7-SCALING.md` — the scaling path, and why it's deliberately not built yet

---

## Testing

```bash
cd backend && pytest
```

The suite covers authentication (token lifecycle, tampering, expiry), memory, the planner's output parsing, the SSRF guard's address classification, the approval lifecycle, and the MCP adapter. CI runs it against live Postgres and Redis on every push.

---

## Security notes

- Secrets (`.env`, OAuth credentials, tokens) are git-ignored and never committed.
- The assistant opens no inbound ports; remote access is via an encrypted private mesh.
- Filesystem and external-tool access are scoped to explicitly allowed directories and gated per-tool — never granted blanket access to the host.
- Every state-changing action is logged and, by default, requires user approval.

---

## Status

The core system and its optional capabilities are complete and tested. Horizontal scaling (Kubernetes / managed clusters) is intentionally not implemented — it would add operational complexity with no benefit for a single-user deployment; the reasoning and the path are documented in `docs/PHASE7-SCALING.md`.

---

## License

MIT — see `LICENSE`.

---

*Built as a hands-on exploration of agentic AI systems: retrieval-augmented memory, tool-using agents, secure remote architecture, and the Model Context Protocol — assembled into one assistant that runs on hardware I control.*

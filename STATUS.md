# JARVIS — Project Status

A personal, local-first AI assistant that runs on a laptop, reaches your
phone securely from anywhere, remembers across conversations, acts on your
computer with your approval, and extends through the open MCP ecosystem —
built almost entirely on free and open-source software.

## What's built (and tested)

**Core (Phases 0–6) — complete:**
- Local assistant with a security-gated tool layer (the original desktop app)
- Containerized server: FastAPI + Postgres + Redis, one `docker compose` stack
- Persistent conversations and a tiered LLM router with failover (OpenRouter
  free tier, escalation-ready, local Ollama fallback)
- Semantic long-term memory: local embeddings in pgvector, ambient retrieval,
  a background distiller that learns facts from conversation, dedup by meaning
- Secure remote access: Tailscale mesh (no exposed ports), real HTTPS via
  `tailscale serve`, JWT auth with refresh rotation, Redis rate limiting
- Installable PWA: three tabs (Console / Tasks / Memory), two-way voice,
  push notifications, an Iron-Man HUD with a 3D arc-reactor backdrop
- Background agents: planner → executor running multi-step tasks; a scheduler
  for reminders that push to your phone
- Human-in-the-loop approvals: consequential tools pause and ask, on your phone
- Operations: automated nightly database backups + restore, CI workflow,
  Alembic migrations
- 35 automated tests passing

**Optional capabilities — built:**
- **MCP adapter** (proven working): connect ecosystem tool servers; every tool
  inherits the security gate and audit log
- **Six MCP servers pre-configured** (disabled until you opt in): filesystem,
  fetch, git (keyless); github, gmail, gcalendar (need your credentials)
- **Wake word**: hands-free "Jarvis, …" in the app
- **Desktop-as-hands node**: your phone opens apps / runs a system report /
  locks the screen on your laptop, each approved on your phone; the laptop
  opens no ports and runs a fixed safe allowlist

## What's intentionally NOT built
- **Phase 7 (Kubernetes / managed-cluster scaling)** — correct call for a
  single-user tool; see docs/PHASE7-SCALING.md for the path and the reasoning.
- **SMS** — needs a paid Twilio gateway + Indian DLT registration; free push
  notifications already cover reminders.

## Honest caveats (what only your hardware can confirm)
This was built and verified with automated tests and headless rendering, but
some things can only be confirmed on your real devices/GPU:
- the live feel of the 3D reactor brightness (software-rendered here looks dim);
- the full voice / push / wake-word experience on a real phone;
- the phone-approves → laptop-acts round trip with the desktop agent running;
- first launch of each MCP server (npx/uvx) on your machine.
If any of these misbehaves, the errors are usually small and quick to fix.

## Setup recap
1. `cp .env.example .env`, set `OPENROUTER_API_KEY` + a random `API_KEY`.
2. `docker compose up -d --build`
3. Tailscale on laptop + phone; `tailscale serve --bg 8000` for HTTPS.
4. Open the `.ts.net` address on your phone, claim the owner account, install.
- Cloud deploy: DEPLOY.md · MCP file access + servers: README + mcp_config.json
- Gmail/Calendar: deploy/google-setup.md · Desktop agent: local-agent/README.md

## The next step that isn't code
This is portfolio-grade work. Make it visible:
1. **Push both repos to GitHub** (`jarvis` desktop + `jarvis-server`). The
   `.gitignore` keeps secrets out; the CI workflow runs your tests with a green
   badge. (You'll also want a GitHub token for the github MCP server anyway.)
2. **Record a 90-second demo video**: voice command → tool chip → a reminder
   arriving on your locked phone → an Allow/Deny prompt. Pin it to the repo.
3. **Rotate the OpenRouter key** that was pasted during development.
4. Put the project at the **top of your resume**, with topics tagged on the
   repos: ai-agent, fastapi, pgvector, mcp, pwa, docker.

You asked for "an AI assistant like Jarvis in the Iron Man movie." This is it.

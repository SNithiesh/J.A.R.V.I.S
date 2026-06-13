# Phase 7 — Scaling (and why you haven't done it yet)

Short version: **don't build this now.** This document exists so you
understand the path *and* can articulate, in an interview, why a single-node
deployment is the correct engineering choice for a personal assistant. That
judgment is worth more than the YAML.

## Why scaling is deliberately not built

Kubernetes, managed database clusters, and horizontal autoscaling solve
*one* problem: serving many concurrent users across many machines reliably.
A personal Jarvis has **one user**. Adding that machinery would:

- introduce a control plane, manifests, and a steeper operational burden you'd
  have to maintain alone;
- cost real money (managed Postgres/Redis, multiple nodes);
- add failure modes (networking, scheduling) you don't have today;
- buy you nothing, because one container comfortably serves one person.

"Right-sizing" is a senior skill. Provisioning a fleet to move a single box
is over-engineering. The current design — one `docker compose` stack on a
laptop or a small VPS — is the *correct* architecture for the requirement.

## When scaling WOULD be justified

Only if the project changed shape, e.g.:
- you open Jarvis to many users (a product, not a personal tool);
- sustained load exceeds one box (hundreds of concurrent sessions);
- you need high-availability guarantees (no single point of failure).

None of these apply to a personal assistant. If they ever did, here's the path.

## The scaling path (reference, not a to-do)

The architecture was built so this is *possible without redesign* — that was
the point of "no service knows its own location."

**1. Externalize state first (the only real prerequisite).**
The app is already stateless except for Postgres, Redis, and MinIO. Point the
same code at managed services by changing `.env` only:
- Postgres → a managed Postgres (RDS, Cloud SQL, Neon). pgvector is supported.
- Redis → a managed Redis (ElastiCache, Upstash).
- Files → real S3/R2/B2 (MinIO already speaks the S3 API; swap credentials).
No code changes — that's the dividend of the hostname-from-env discipline.

**2. Run multiple API replicas.**
The FastAPI app and ARQ workers are stateless, so you can run N copies behind
a load balancer. One change needed: the in-memory WebSocket `hub` and the
in-memory approval/desktop queues must move to Redis pub/sub so any replica
can serve any client. The code is structured so this is a module swap, not a
rewrite (see the notes in hub.py / approvals.py).

**3. Containerize for an orchestrator.**
The Dockerfile already produces a clean image. For Kubernetes you'd add:
- a Deployment for the API (replicas: N) + a Service + an Ingress;
- a Deployment for workers;
- the datastores as managed services (don't run stateful sets yourself early);
- health/readiness probes (the app already exposes `/healthz`);
- secrets via the cluster's secret store (or Vault/Infisical).
A starter `k8s/` manifest set would live here when needed.

**4. Observability becomes mandatory at scale.**
Wire Prometheus + Grafana + Loki (already planned in Phase 6's monitoring
folder) before scaling, so you can see per-replica health and latency.

## The honest recommendation

Stay on one node. If you outgrow a laptop, move the *same stack* to a single
VPS (see DEPLOY.md). If you somehow outgrow that, externalize state (step 1)
and add replicas (step 2) — and only reach for Kubernetes if you're genuinely
running a multi-node service. For a personal Jarvis, that day will likely
never come, and that is a success, not a gap.

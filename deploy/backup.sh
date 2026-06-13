#!/usr/bin/env bash
# ==========================================================
# JARVIS automated backup — runs inside the backup container.
# Photographs the whole database, compresses it, prunes old
# copies. Everything Jarvis remembers lives in Postgres, so
# this file IS the disaster-recovery plan.
# ==========================================================
set -euo pipefail

RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="/backups/jarvis_${STAMP}.sql.gz"

echo "[backup] $(date) starting -> ${OUT}"
# pg_dump streams the entire DB; gzip shrinks it; redirect to the mounted folder.
PGPASSWORD="${POSTGRES_PASSWORD:-jarvis}" pg_dump \
  -h postgres -U jarvis -d jarvis \
  | gzip > "${OUT}"

SIZE="$(du -h "${OUT}" | cut -f1)"
echo "[backup] wrote ${OUT} (${SIZE})"

# Prune: delete photos older than the retention window.
find /backups -name 'jarvis_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete \
  | sed 's/^/[backup] pruned /' || true

echo "[backup] done. current copies:"
ls -1t /backups/jarvis_*.sql.gz 2>/dev/null | head -5 | sed 's/^/  /'

#!/usr/bin/env bash
# ==========================================================
# JARVIS restore — bring memory back from a backup file.
# Usage (from the project folder, stack running):
#   docker compose exec -T postgres psql -U jarvis -d jarvis \
#     < <(gunzip -c backups/jarvis_YYYYMMDD_HHMMSS.sql.gz)
#
# Or interactively with this helper on the HOST:
#   bash deploy/restore.sh backups/jarvis_YYYYMMDD_HHMMSS.sql.gz
# An untested backup is a hope, not a plan — rehearse this once.
# ==========================================================
set -euo pipefail
FILE="${1:?usage: restore.sh <path-to-.sql.gz>}"
echo "[restore] restoring ${FILE} into the running postgres container..."
gunzip -c "${FILE}" | docker compose exec -T postgres psql -U jarvis -d jarvis
echo "[restore] done. Restart the API:  docker compose restart api"

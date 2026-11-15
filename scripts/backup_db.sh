#!/usr/bin/env sh
# Code Freeze backup (task 17).
#   ./scripts/backup_db.sh                       -> backups/stellar_<timestamp>.sql (+ .db)
#   ./scripts/restore_db.sh backups/<file>.sql
set -e
cd "$(dirname "$0")/.."
mkdir -p backups
STAMP=$(date +%Y%m%d_%H%M%S)

# SQLite (Plan B): copy the file
if [ -f stellar.db ]; then
  cp stellar.db "backups/stellar_$STAMP.db"
  echo "SQLite backup: backups/stellar_$STAMP.db"
fi

# PostgreSQL in Docker
if command -v docker >/dev/null 2>&1 && docker compose ps db --status running -q 2>/dev/null | grep -q .; then
  docker compose exec -T db sh -c 'pg_dump --clean --if-exists -U "$POSTGRES_USER" "$POSTGRES_DB"' \
    > "backups/stellar_$STAMP.sql"
  echo "PostgreSQL backup: backups/stellar_$STAMP.sql"
fi

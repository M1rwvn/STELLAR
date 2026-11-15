#!/usr/bin/env sh
# Restore a backup made by backup_db.sh:  ./scripts/restore_db.sh backups/<file>.sql
set -e
cd "$(dirname "$0")/.."
[ -n "$1" ] || { echo "usage: $0 backups/<file>.sql"; exit 1; }
docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" "$POSTGRES_DB"' < "$1"
echo "Restored $1"

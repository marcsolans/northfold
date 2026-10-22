#!/usr/bin/env bash
# Restore a Messer backup produced by backup.sh into DATABASE_URL (the database is replaced), plus project
# repositories and file storage. Verifies checksums first, then runs migrations so the schema is current.
#
#   DATABASE_URL=postgresql://messer:…@host:5432/messer DATABASE_APP_URL=… DATABASE_READONLY_URL=… \
#   MESSER_PROJECTS_DIR=/data/projects MESSER_STORAGE_DIR=/data/storage \
#   infra/scripts/restore.sh /backups/messer-20261021T220000Z
#
# BACKUP_PASSPHRASE is required for encrypted backups. Stop the API, runtime, worker and scheduler first.
set -euo pipefail

SRC="${1:?usage: restore.sh <backup directory>}"
: "${DATABASE_URL:?DATABASE_URL is required}"
PROJECTS_DIR="${MESSER_PROJECTS_DIR:-./.data/projects}"
STORAGE_DIR="${MESSER_STORAGE_DIR:-./.data/storage}"
PG_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

log() { printf '[restore] %s\n' "$*" >&2; }

log "verifying checksums"
(cd "$SRC" && sha256sum --quiet -c SHA256SUMS)

for f in "$SRC"/*; do
  name="$(basename "$f")"
  case "$name" in
    *.enc)
      : "${BACKUP_PASSPHRASE:?this backup is encrypted: set BACKUP_PASSPHRASE}"
      openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE -in "$f" -out "$WORK/${name%.enc}" ;;
    SHA256SUMS|manifest.json) ;;
    *) cp "$f" "$WORK/$name" ;;
  esac
done

role_from_url() {  # postgresql://user:password@host/db → "user password"
  local url="${1#*://}"; local creds="${url%%@*}"
  printf '%s %s' "${creds%%:*}" "${creds#*:}"
}

log "ensuring roles"
for var in DATABASE_APP_URL DATABASE_READONLY_URL; do
  url="${!var:-}"
  [ -n "$url" ] || continue
  read -r user password <<<"$(role_from_url "${url/postgresql+psycopg:/postgresql:}")"
  psql "$PG_URL" -v ON_ERROR_STOP=1 -q -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${user}') THEN CREATE ROLE \"${user}\" LOGIN PASSWORD '${password}' NOBYPASSRLS; END IF; END \$\$;"
done
[ -f "$WORK/roles.sql" ] && psql "$PG_URL" -v ON_ERROR_STOP=1 -q -f "$WORK/roles.sql"

log "restoring database (existing objects are replaced)"
# Extensions (vector, pg_trgm, unaccent) belong to the database superuser and are created when the database is
# provisioned (infra/docker/postgres/init.sql, Supabase), so they are left out of the restore.
pg_restore --list "$WORK/db.dump" | grep -v -E ' (EXTENSION|COMMENT - EXTENSION) ' > "$WORK/toc.list"
pg_restore --clean --if-exists --no-owner --exit-on-error --use-list "$WORK/toc.list" --dbname "$PG_URL" "$WORK/db.dump"

if [ -f "$WORK/projects.tar.gz" ]; then
  log "restoring project repositories into $PROJECTS_DIR"
  mkdir -p "$PROJECTS_DIR"
  tar -C "$PROJECTS_DIR" -xzf "$WORK/projects.tar.gz"
fi
if [ -f "$WORK/storage.tar.gz" ]; then
  log "restoring file storage into $STORAGE_DIR"
  mkdir -p "$STORAGE_DIR"
  tar -C "$STORAGE_DIR" -xzf "$WORK/storage.tar.gz"
fi

if command -v alembic >/dev/null 2>&1 && [ -f infra/migrations/alembic.ini ]; then
  log "applying pending migrations"
  alembic -c infra/migrations/alembic.ini upgrade head
fi
log "done"

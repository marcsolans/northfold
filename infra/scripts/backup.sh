#!/usr/bin/env bash
# Messer backup: database (all schemas, including knowledge-base schemas), the roles the database needs,
# project git repositories and local file storage, with a manifest and SHA-256 checksums.
#
#   DATABASE_URL=postgresql://messer:…@host:5432/messer \
#   MESSER_PROJECTS_DIR=/data/projects MESSER_STORAGE_DIR=/data/storage \
#   infra/scripts/backup.sh /backups
#
# Optional: BACKUP_PASSPHRASE encrypts every artifact (AES-256, PBKDF2); BACKUP_S3_URI (s3://bucket/prefix) uploads
# the backup with the AWS CLI. In Supabase deployments, keep Supabase's own daily backups + PITR enabled as well;
# this script adds application-level, portable backups (and covers repositories and storage).
set -euo pipefail

OUT_ROOT="${1:-./backups}"
: "${DATABASE_URL:?DATABASE_URL is required}"
PROJECTS_DIR="${MESSER_PROJECTS_DIR:-./.data/projects}"
STORAGE_DIR="${MESSER_STORAGE_DIR:-./.data/storage}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${OUT_ROOT%/}/messer-${STAMP}"
PG_URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

mkdir -p "$OUT"
umask 077

log() { printf '[backup] %s\n' "$*" >&2; }

log "database → db.dump"
pg_dump --format=custom --no-owner --file "$OUT/db.dump" "$PG_URL"

log "roles and role memberships the database needs → roles.sql"
psql "$PG_URL" -v ON_ERROR_STOP=1 -At > "$OUT/roles.sql" <<'SQL'
WITH kb_roles AS (
  SELECT reader_role AS name FROM public.knowledge_bases WHERE reader_role IS NOT NULL
), wanted AS (
  SELECT name FROM kb_roles UNION SELECT 'messer_kb_reader' WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'messer_kb_reader')
)
SELECT format('DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %L) THEN CREATE ROLE %I NOLOGIN; END IF; END $$;', name, name)
FROM wanted
UNION ALL
SELECT format('GRANT %I TO %I;', r.rolname, m.rolname)
FROM pg_auth_members am
JOIN pg_roles r ON r.oid = am.roleid
JOIN pg_roles m ON m.oid = am.member
WHERE r.rolname IN (SELECT name FROM kb_roles) OR m.rolname IN (SELECT name FROM kb_roles);
SQL

REVISION="$(psql "$PG_URL" -At -c 'SELECT version_num FROM public.alembic_version' 2>/dev/null || echo unknown)"

if [ -d "$PROJECTS_DIR" ]; then
  log "project repositories → projects.tar.gz"
  tar -C "$PROJECTS_DIR" -czf "$OUT/projects.tar.gz" .
fi
if [ -d "$STORAGE_DIR" ]; then
  log "file storage → storage.tar.gz"
  tar -C "$STORAGE_DIR" -czf "$OUT/storage.tar.gz" .
fi

if [ -n "${BACKUP_PASSPHRASE:-}" ]; then
  log "encrypting artifacts"
  for f in "$OUT"/db.dump "$OUT"/roles.sql "$OUT"/projects.tar.gz "$OUT"/storage.tar.gz; do
    [ -f "$f" ] || continue
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -in "$f" -out "$f.enc"
    rm -f "$f"
  done
fi

(cd "$OUT" && sha256sum ./* > SHA256SUMS)
cat > "$OUT/manifest.json" <<JSON
{"created_at": "${STAMP}", "alembic_revision": "${REVISION}", "encrypted": $([ -n "${BACKUP_PASSPHRASE:-}" ] && echo true || echo false),
 "artifacts": [$(cd "$OUT" && ls -1 | grep -v -e SHA256SUMS -e manifest.json | sed 's/.*/"&"/' | paste -sd, -)]}
JSON

if [ -n "${BACKUP_S3_URI:-}" ]; then
  log "uploading to ${BACKUP_S3_URI}"
  aws s3 cp --recursive "$OUT" "${BACKUP_S3_URI%/}/messer-${STAMP}/"
fi

log "done: $OUT"
echo "$OUT"

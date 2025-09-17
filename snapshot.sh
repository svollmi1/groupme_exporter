#!/usr/bin/env bash
set -euo pipefail

DB="${GROUPME_DB_PATH:-./groupme.sqlite}"
LOCAL_TMP_DIR="${GROUPME_TMP_DIR:-./tmp}"
DEST="${GROUPME_SNAPSHOT_DEST:-./snapshots}"
PREFIX="groupme"
KEEP=3
LOCKFILE="${GROUPME_LOCKFILE:-./snapshot.lock}"
ERRLOG="${GROUPME_ERRLOG:-./snapshot.err}"

log() { printf "[%(%F %T)T] %s\n" -1 "$*"; logger -t groupme-snapshot -- "$*"; }

command -v sqlite3 >/dev/null || { log "sqlite3 not found"; exit 1; }
[[ -f "$DB" ]] || { log "DB not found at $DB"; exit 1; }
mkdir -p "$LOCAL_TMP_DIR"

# ensure SMB mount is available & writable
if ! mountpoint -q "$DEST"; then
  log "SMB mount $DEST not available — snapshot skipped"; exit 0
fi
if ! ( touch "$DEST/.writetest" && rm -f "$DEST/.writetest" ); then
  log "SMB mount not writable — snapshot skipped"; exit 0
fi

# single instance lock
exec 9>"$LOCKFILE"
if ! flock -n 9; then
  log "another snapshot is running; exiting"; exit 0
fi

TS="$(date +%Y%m%d-%H%M%S)"
LOCAL_TMP="$LOCAL_TMP_DIR/${PREFIX}_${TS}.sqlite"
SMB_TMP="$DEST/${PREFIX}_${TS}.sqlite.partial"
SMB_OUT="$DEST/${PREFIX}_${TS}.sqlite"

# Retry loop: up to 5 tries with 10s between, 30s busy timeout
attempt=1; max_attempts=5
while : ; do
  log "Local sqlite backup (attempt $attempt/$max_attempts) → $LOCAL_TMP"
  # Feed dot-commands via stdin to avoid quoting/arg parsing issues
  if sqlite3 "$DB" 2>"$ERRLOG" <<SQL
.timeout 30000
.backup $LOCAL_TMP
SQL
  then
    break
  fi
  reason="$(tr -s "\n" " " <"$ERRLOG" 2>/dev/null || true)"
  log "backup failed: ${reason:-unknown}"
  (( attempt >= max_attempts )) && { log "giving up after $attempt attempts"; exit 1; }
  sleep 10; ((attempt++))
done

# file must not be empty
if [[ ! -s "$LOCAL_TMP" ]]; then
  log "local backup is empty (0 bytes). See $ERRLOG"; rm -f "$LOCAL_TMP"; exit 1
fi

# clean any stale partials
find "$DEST" -maxdepth 1 -type f -name "${PREFIX}_*.sqlite.partial" -delete 2>/dev/null || true
find "$DEST" -maxdepth 1 -type f -name "${PREFIX}_*.sqlite.tmp" -delete 2>/dev/null || true

log "Copying to SMB → $SMB_TMP"
cp -p "$LOCAL_TMP" "$SMB_TMP"
mv -f "$SMB_TMP" "$SMB_OUT"
touch -r "$LOCAL_TMP" "$SMB_OUT"

# publish stable filename for BI tools
cp -p "$SMB_OUT" "$DEST/groupme_latest.sqlite"

rm -f "$LOCAL_TMP"

log "Snapshot complete: $(basename "$SMB_OUT") ($(du -h "$SMB_OUT" | awk "{print \$1}"))"

# Retention: keep newest $KEEP
TO_DELETE=$(ls -1t "$DEST"/${PREFIX}_*.sqlite 2>/dev/null | tail -n +$((KEEP+1)) || true)
if [[ -n "$TO_DELETE" ]]; then
  log "Pruning old snapshots:"
  while IFS= read -r f; do
    log "  removing $(basename "$f")"
    rm -f -- "$f" || true
  done <<< "$TO_DELETE"
else
  log "No old snapshots to prune (keeping $KEEP)"
fi

log "Done"
SH'

#!/bin/bash

# Replace ./jobfinder.db with a snapshot of the database on the Mac that runs
# the cron jobs, so the local dashboard shows real data. Nothing is ever
# copied back. DEPLOY_HOST and DEPLOY_DIR work as in ops/deploy.sh.
set -euo pipefail
HOST="${DEPLOY_HOST:-oldmac}"
DIR="${DEPLOY_DIR:-Github/Job-finder}"
cd "$(dirname "$0")/.."
trap 'rm -f jobfinder.db.tmp' EXIT

# sqlite3's .backup takes a consistent copy even while a cron job is writing.
ssh "$HOST" "DIR='$DIR' bash -s" > jobfinder.db.tmp <<'EOF'
set -euo pipefail
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
sqlite3 "$HOME/$DIR/jobfinder.db" ".backup '$tmp'"
cat "$tmp"
EOF
rm -f jobfinder.db-wal jobfinder.db-shm
mv jobfinder.db.tmp jobfinder.db
echo "Copied $(sqlite3 jobfinder.db 'SELECT COUNT(*) FROM jobs') jobs from $HOST into jobfinder.db."

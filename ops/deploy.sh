#!/bin/bash

# Deploy origin/main to the Mac that runs the cron jobs and the dashboard:
# run the tests here, then pull, sync and smoke-test there, and restart the
# dashboard. The cron jobs pick up the new code on their next run.
# DEPLOY_HOST (an ssh host, default "oldmac") and DEPLOY_DIR (relative to
# that Mac's home directory) override the defaults.
set -euo pipefail
HOST="${DEPLOY_HOST:-oldmac}"
DIR="${DEPLOY_DIR:-Github/Job-finder}"
cd "$(dirname "$0")/.."

git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ] \
   || [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Check out a clean main that matches origin/main first: this deploys origin/main," >&2
  echo "and the tests below run on your working tree." >&2
  exit 1
fi
uv run pytest -q

ssh "$HOST" "DIR='$DIR' bash -s" <<'EOF'
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$HOME/$DIR"
git checkout -q main
git pull -q --ff-only origin main
uv sync -q --locked
uv run python -c "import jobscraper, tech_jobs, enrich_jobs, dashboard.app"
agent="gui/$(id -u)/com.jobfinder.dashboard"
if launchctl print "$agent" >/dev/null 2>&1; then
  launchctl kickstart -k "$agent"
  echo "Dashboard restarted."
else
  echo "No dashboard agent here yet; run ops/install_dashboard_agent.sh on this Mac to add one."
fi
echo "Deployed to $(hostname): $(git log -1 --format='%h %s')"
EOF

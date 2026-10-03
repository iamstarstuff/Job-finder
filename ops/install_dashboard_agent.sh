#!/bin/bash

# Install, or reinstall, a launchd agent that keeps the dashboard running on
# this Mac: it starts at login and restarts if it exits. Run it on the Mac
# that serves the dashboard, not on a development machine.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.jobfinder.dashboard"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$REPO/run_dashboard.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$REPO/dashboard_server.log</string>
  <key>StandardErrorPath</key><string>$REPO/dashboard_server.log</string>
</dict>
</plist>
EOF
plutil -lint -s "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Dashboard agent installed: http://$(scutil --get LocalHostName).local:5050"

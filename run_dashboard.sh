#!/bin/bash

# Run the dashboard in the project's uv environment; the launchd agent from
# ops/install_dashboard_agent.sh starts it. launchd's PATH has neither Homebrew
# (/opt/homebrew on Apple Silicon, /usr/local on Intel) nor ~/.local/bin
# (uv's standalone installer), so add all three.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"
exec uv run python dashboard/app.py

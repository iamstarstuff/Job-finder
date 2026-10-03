#!/bin/bash

# Run the enrichment pipeline in the project's uv environment.
# cron's PATH has neither Homebrew (/opt/homebrew on Apple Silicon, /usr/local
# on Intel) nor ~/.local/bin (uv's standalone installer), so add all three.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
cd "$(dirname "$0")"
exec uv run python enrich_jobs.py

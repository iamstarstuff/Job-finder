#!/bin/bash

# Run the enrichment pipeline in the project's uv environment.
# cron's PATH has no Homebrew (/opt/homebrew on Apple Silicon, /usr/local on
# Intel), so put uv on it explicitly.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$(dirname "$0")"
exec uv run python enrich_jobs.py

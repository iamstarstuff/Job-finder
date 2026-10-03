#!/bin/bash

# Run the tech scraper in the project's uv environment.
# cron's PATH has no Homebrew, so put uv on it explicitly.
export PATH="/opt/homebrew/bin:$PATH"
cd "$(dirname "$0")"
exec uv run python tech_jobs.py

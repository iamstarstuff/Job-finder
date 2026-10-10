# Job Finder

A Python tool that watches company career pages for Ireland-based roles,
stores every posting in a local SQLite database, emails an alert when new
roles appear, enriches each role with its full description and the skills
it mentions, and serves a Flask dashboard that answers *what is in demand,
who is hiring, and what should I learn next*.

## What runs, and when

| Pipeline | Entry point | Cadence (cron) | What it does |
|---|---|---|---|
| Pharma scraper | `run_job.sh` → `jobscraper.py` | hourly, at :00 | Scrapes 20 pharma/biotech companies, emails new roles |
| Tech scraper | `run_tech_job.sh` → `tech_jobs.py` | hourly, at :20; scrapes once a day from 08:00 | Scrapes 15 tech companies; Claude picks the data, ML, SRE, DevOps, cloud, observability and analytics roles (title keywords when Claude is off) |
| Enrichment | `enrich_job.sh` → `enrich_jobs.py` | hourly, at :40 | Fetches full descriptions, extracts skills and seniority; Claude extracts role family, seniority, experience, skills, languages, work mode, contract and salary |

The three pipelines are deliberately independent: a failure in enrichment
can never delay or break an alert email.

cron skips any run the Mac sleeps through, so every pipeline is started
hourly and catches up at the next hour the Mac is awake. The tech scraper
checks the `runs` table and scrapes only on the day's first run at or after
`TECH_DAILY_HOUR` (08:00); `uv run python tech_jobs.py --force` runs it
regardless. Enrichment only fetches roles that have no description yet, so
an hourly run with nothing new makes no requests.

## Dashboard

```bash
uv run python dashboard/app.py   # http://127.0.0.1:5050  (PORT=5051 to pick another port)
```

Pages:

- **Home** — a plain-language brief for the week, four headline tiles, and
  four charts: skills in demand, hiring velocity, who is hiring (with the
  biggest movers), and a skill-trend heatmap. A time-window selector (last 4,
  12, 26 weeks or all time) and a sector toggle scope everything on the page.
- **Pharma / Tech** — the same view for one sector, plus seniority mix and
  role families by company, what to learn for a chosen role family and
  level, experience asked, openings by role family, days to close, and the
  ten most recent roles.
- **Jobs** — every open role (tick "Include closed jobs" for the rest) as
  cards with Claude's role family, level, years, work mode, contract, salary
  when stated, required languages, reason (tech) and skills. A sidebar
  filters by sector, role family, seniority, years asked, work mode,
  contract and company, with live counts; search covers titles and skills.
- **Health** — scraper status per company (OK, empty listing, failing,
  retired), recent runs and email delivery.
- **Emails** and **Logs** — delivery history and the tail of each log file.

Charts are built server-side with [echartsy](https://pypi.org/project/echartsy/)
and rendered with Apache ECharts; every chart has a "Show data" table and
click-to-drilldown into the roles behind a bar, cell, line or segment. The JSON
behind any chart is at `/api/charts/<name>?sector=&weeks=`.

## Setup

```bash
git clone https://github.com/iamstarstuff/Job-finder.git
cd Job-finder
uv sync
```

Dependencies and the Python version (3.13) are managed with
[uv](https://docs.astral.sh/uv/): `pyproject.toml`, `uv.lock` and
`.python-version`. `uv sync` creates `.venv/` with everything, including
pytest.

SMTP settings live in `jobfinder/config.py`. The password comes from the
`SMTP_PASSWORD` environment variable, or from a `smtp_password.txt` file in
the project root (gitignored).

Run once by hand to create `jobfinder.db`:

```bash
uv run python jobscraper.py
uv run python enrich_jobs.py
```

Then schedule the three shell scripts with `crontab -e` (adjust the paths):

```
0 * * * * $HOME/Github/Job-finder/run_job.sh >> $HOME/Github/Job-finder/logs.log 2>&1
20 * * * * $HOME/Github/Job-finder/run_tech_job.sh >> $HOME/Github/Job-finder/tech_scraper_cron.log 2>&1
40 * * * * $HOME/Github/Job-finder/enrich_job.sh >> $HOME/Github/Job-finder/enrichment_cron.log 2>&1
```

Each one runs its entry point with `uv run`, so cron needs no activated
environment.

## Claude insights

Claude (`claude-sonnet-5-5`) reads each new posting once. For tech postings it
decides whether the role fits; for every job it extracts structured fields into
the `job_insights` table. It needs an API key on the Mac that runs the cron jobs,
either in `ANTHROPIC_API_KEY` or in `anthropic_api_key.txt` (git-ignored; create
it with `umask 077` so only you can read it). Without a key, everything works as
before: tech postings are filtered by title keywords and no fields are extracted.

- **Cost:** about 1 cent per posting. Realtime calls are capped at
  `INSIGHTS_DAILY_CALL_LIMIT` (200) a day; the health page shows this month's spend.
- **Alerts:** a bad key, missing permission or empty credit balance emails the error
  address once when it starts and once when it is fixed.
- **Backfill:** `uv run python backfill_insights.py` prints what a one-off pass over the
  stored descriptions and today's tech postings would cost; `--yes` sends it through
  the Message Batches API at half price.
- **Changing the profile or fields:** edit `SYSTEM_PROMPT` / `Insight` in
  `jobfinder/insights.py` and bump `PROMPT_VERSION`; every posting is read again.

## Developing on one Mac, running on another

The cron jobs, the database and the dashboard live on one always-on Mac;
development happens on another. The scripts in `ops/` assume an ssh host
alias `oldmac` for the always-on Mac and the repo at `~/Github/Job-finder`
there (override with `DEPLOY_HOST` and `DEPLOY_DIR`).

- `ops/deploy.sh` deploys `origin/main`: it runs the tests locally, then on
  the always-on Mac pulls, runs `uv sync --locked`, smoke-tests the imports
  and restarts the dashboard. The cron jobs pick up the new code on their
  next run.
- `ops/pull_db.sh` replaces the local `jobfinder.db` with a consistent
  snapshot of the live one, so the local dashboard shows real data. Nothing
  is ever copied back.
- `ops/install_dashboard_agent.sh`, run once on the always-on Mac, installs
  a launchd agent that starts the dashboard at login and restarts it if it
  exits. Its output goes to `dashboard_server.log`.
- Set `JOBFINDER_DRY_RUN=1` on the development Mac. Every email then becomes
  a log line ("Dry run, email not sent: …") and nothing is written to the
  `emails` table, so a test scrape never reaches the alert recipients.

## Maintenance

- `uv run python enrich_jobs.py --reextract` rebuilds every role's skill links from
  the current `SKILL_KEYWORDS` vocabulary in `jobfinder/enrichment.py`. Run it
  after editing the vocabulary.
- A company that returns zero roles while it still has open ones is treated
  as a possible layout change and left untouched for
  `ZERO_RESULT_GRACE_DAYS` (7); after that the zero is accepted and its roles
  are closed. Genuine scraper failures never close roles.
- Companies that cannot be scraped over plain HTTP (Cloudflare or similar
  challenges) are not in the registries; see the comments in
  `jobfinder/scrapers.py` and `jobfinder/tech_scrapers.py`.

## Tests

```bash
uv run pytest
```

## Project layout

```
jobfinder/            core package: config, http client, scrapers, storage, runners, emailer, enrichment, analytics, insights (Claude)
dashboard/            Flask app (app.py), chart builders (charts.py), the weekly brief (brief.py), templates, static/charts.js
tests/                pytest suite
jobscraper.py, tech_jobs.py, enrich_jobs.py   thin entry points used by the cron scripts
backfill_insights.py  one-off Claude backfill through the Message Batches API
ops/                  deploy.sh, pull_db.sh, install_dashboard_agent.sh for the two-Mac setup
```

## License

MIT

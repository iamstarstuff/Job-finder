# Job Finder

A Python tool that watches company career pages for Ireland-based roles,
stores every posting in a local SQLite database, emails an alert when new
roles appear, enriches each role with its full description and the skills
it mentions, and serves a Flask dashboard that answers *what is in demand,
who is hiring, and what should I learn next*.

## What runs, and when

| Pipeline | Entry point | Cadence (cron) | What it does |
|---|---|---|---|
| Pharma scraper | `run_job.sh` → `jobscraper.py` | hourly | Scrapes 20 pharma/biotech companies, emails new roles |
| Tech scraper | `run_tech_job.sh` → `tech_jobs.py` | daily 08:00 | Scrapes 15 tech companies for data, SRE, DevOps, cloud and analytics roles |
| Enrichment | `enrich_job.sh` → `enrich_jobs.py` | every 4 hours | Fetches full descriptions, extracts skills and seniority |

The three pipelines are deliberately independent: a failure in enrichment
can never delay or break an alert email.

## Dashboard

```bash
python dashboard/app.py          # http://127.0.0.1:5050  (PORT=5051 to pick another port)
```

Pages:

- **Home** — a plain-language brief for the week, four headline tiles, and
  four charts: skills in demand, hiring velocity, who is hiring (with the
  biggest movers), and a skill-trend heatmap. A time-window selector (last 4,
  12, 26 weeks or all time) and a sector toggle scope everything on the page.
- **Pharma / Tech** — the same view for one sector, plus seniority mix by
  company, what each company posts, days to close, and the ten most recent
  roles.
- **Jobs** — every role ever seen, with company, title, skill and
  description search and expandable descriptions.
- **Health** — scraper status per company (OK, empty listing, failing,
  retired), recent runs and email delivery.
- **Emails** and **Logs** — delivery history and the tail of each log file.

Charts are built server-side with [echartsy](https://pypi.org/project/echartsy/)
and rendered with Apache ECharts; every chart has a "Show data" table and
click-to-drilldown into the roles behind a bar, row or segment. The JSON
behind any chart is at `/api/charts/<name>?sector=&weeks=`.

## Setup

```bash
git clone https://github.com/iamstarstuff/Job-finder.git
cd Job-finder
pip install -r requirements.txt
```

SMTP settings live in `jobfinder/config.py`. The password comes from the
`SMTP_PASSWORD` environment variable, or from a `smtp_password.txt` file in
the project root (gitignored).

Run once by hand to create `jobfinder.db`:

```bash
python jobscraper.py
python enrich_jobs.py
```

Then schedule the three shell scripts with `crontab -e` at the cadences above.

## Maintenance

- `python enrich_jobs.py --reextract` rebuilds every role's skill links from
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
python -m pytest tests/
```

## Project layout

```
jobfinder/            core package: config, http client, scrapers, storage, runners, emailer, enrichment, analytics
dashboard/            Flask app (app.py), chart builders (charts.py), the weekly brief (brief.py), templates, static/charts.js
tests/                pytest suite
jobscraper.py, tech_jobs.py, enrich_jobs.py   thin entry points used by the cron scripts
```

## License

MIT

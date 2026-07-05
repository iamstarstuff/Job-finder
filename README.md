# Job Finder

A Python automation tool that scrapes job postings from pharma/biotech company
career pages, stores them in a local SQLite database, and emails an alert when
new jobs appear. It also ships a small Flask dashboard for browsing jobs and
reviewing scrape/email history. Designed to run on a schedule (e.g. hourly)
for continuous monitoring.

## Features

- Scrapes job postings from **9 companies**: APC, Abbvie, Astrazeneca, Takeda,
  Amgen, Vle Therapeutics, Astellas, Pfizer, and MSD (see `SCRAPERS` in
  `jobfinder/scrapers.py`).
  A tenth scraper, **BMS**, is implemented and unit-tested but disabled by
  default — BMS's Eightfold-powered API returns 401/403 without a real
  browser session, so it isn't reliable from a plain HTTP client. See the
  comment above the `SCRAPERS` registry in `jobfinder/scrapers.py` for
  details.
- Stores all job data in a local SQLite database (`jobfinder.db`) instead of
  a flat JSON file, tracking first/last-seen timestamps and active status per
  job.
- Sends HTML email alerts when new jobs are detected, and a separate error
  digest when a company scrape fails or unexpectedly returns zero jobs.
  Every send attempt (success or failure) is logged to an `emails` table.
- A Flask dashboard (`dashboard/app.py`) for browsing jobs, an overview of
  scrape stats, an **analytics** page with Chart.js charts (jobs per company,
  new jobs per week, category breakdown per company), an **email stats**
  page showing delivery history, and a **log tail** viewer.
- Logs activity and errors to `jobscraper.log` for easy troubleshooting.

## Project layout

```
jobfinder/            # core package
  config.py           # paths, SMTP settings, get_smtp_password()
  models.py           # Job dataclass
  http_client.py       # requests session with retries/timeouts
  scrapers.py          # one function per company + SCRAPERS registry
  storage.py            # SQLite schema, snapshot/diff logic, migration
  runner.py             # orchestrates a scrape run end-to-end
  emailer.py            # HTML rendering + sending + logging of emails
  analytics.py          # queries backing the dashboard/API endpoints
dashboard/
  app.py               # Flask app factory (create_app) + routes
  templates/           # Jinja templates (base, index, jobs, analytics, emails, logs)
tests/                 # pytest suite (unit + dashboard integration tests)
jobscraper.py          # thin wrapper: `python jobscraper.py` -> jobfinder.runner.main()
run_job.sh             # cron entry point, unchanged from v1
jobfinder.db           # SQLite database (created on first run)
jobs.json              # legacy v1 data file — see "Migrating from v1" below
```

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/Job-finder.git
cd Job-finder
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure email credentials

SMTP settings (server, port, username, recipients) live in
`jobfinder/config.py`. The password is resolved by `config.get_smtp_password()`:

- Preferred: set the `SMTP_PASSWORD` environment variable.
- Fallback: create a file named `smtp_password.txt` in the project root
  containing just the password (no quotes). This file is already listed in
  `.gitignore` so it won't be committed.

### 4. Run the scraper

```bash
python jobscraper.py
```

This is a thin wrapper around `jobfinder.runner.main()` — it scrapes every
company in the `SCRAPERS` registry, snapshots results into `jobfinder.db`,
sends a new-jobs email if anything changed, and sends an error digest if any
company failed or unexpectedly returned zero jobs.

### 5. Schedule the scraper (cron, unchanged)

`run_job.sh` is the existing cron entry point and did not change in the v2
rewrite — it still just activates the environment and calls
`python jobscraper.py`:

```bash
crontab -e
```
```
0 * * * * /path/to/Job-finder/run_job.sh
```

### 6. Run the dashboard

```bash
python dashboard/app.py
```

`python -m dashboard.app` also works if you prefer running it as a module.

Then open http://127.0.0.1:5050. Pages:

- `/` — overview stats (active jobs, jobs per company, median days active).
- `/jobs` — full job list with company/keyword/active filters.
- `/analytics` — Chart.js charts backed by `/api/jobs-per-company`,
  `/api/new-per-week`, and `/api/categories`.
- `/emails` — email send history and per-kind delivery stats, from the
  `emails` table.
- `/logs` — tail of the last 300 lines of `jobscraper.log`.

### 7. Run the tests

```bash
python -m pytest tests/
```

## Migrating from v1 (`jobs.json`)

`jobs.json` is **legacy**: v2 stores everything in `jobfinder.db` (SQLite).
`jobfinder/storage.py`'s `migrate_legacy_json()` is a one-time import used to
seed the database from the old JSON file. Once `jobfinder.db` exists and
contains your historical data, `jobs.json` is no longer read by any code path
and is safe to delete.

## Notes

- All logs are saved to `jobscraper.log`, rotated weekly with 4 backups kept
  (`TimedRotatingFileHandler` in `jobfinder/runner.py`).
- Make sure your email provider allows SMTP access for the account used in
  `jobfinder/config.py`.

## License

MIT License

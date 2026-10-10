import os
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "jobfinder.db"
LOG_PATH = BASE_DIR / "jobscraper.log"
ENRICHMENT_LOG_PATH = BASE_DIR / "enrichment.log"
TECH_LOG_PATH = BASE_DIR / "tech_scraper.log"
LEGACY_JOBS_JSON = BASE_DIR / "jobs.json"
SMTP_PASSWORD_FILE = BASE_DIR / "smtp_password.txt"
ANTHROPIC_API_KEY_FILE = BASE_DIR / "anthropic_api_key.txt"
BACKFILL_STATE_PATH = BASE_DIR / "backfill_batch.json"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USERNAME = "barvepratik96@gmail.com"
FROM_EMAIL = SMTP_USERNAME
ALERT_RECIPIENTS = ["vaidehipatil2011@gmail.com"]
ERROR_RECIPIENTS = ["barvepratik96@gmail.com"]
TECH_ALERT_RECIPIENTS = ["barvepratik96@gmail.com"]

REQUEST_TIMEOUT = 20  # seconds

# A scraper that returns zero jobs for a company that previously had active
# ones is normally treated as a possible layout change and NOT snapshotted
# (so a broken scraper can't silently close every job). But a company can
# genuinely drop to zero Ireland postings; once none of its active jobs
# have been sighted for this many days, the zero is accepted and the stale
# jobs are closed.
ZERO_RESULT_GRACE_DAYS = 7

# The tech scraper runs once a day, on the first cron run at or after this
# hour. cron starts it hourly, so a day the Mac sleeps through this hour is
# caught up when it wakes instead of being skipped.
TECH_DAILY_HOUR = 8

# Claude classifies tech postings and extracts fields for every job (see
# jobfinder/insights.py). Realtime calls per day are capped, shared by the
# tech run and the enrichment pass, so a scraper that suddenly reports
# thousands of postings can't run up the bill (~1 cent a call).
INSIGHTS_DAILY_CALL_LIMIT = 200
# company_failures entry that tracks Claude API key/credit problems, so the
# alert email goes out once when they start and once when they end.
INSIGHTS_ALERT_SECTOR = "insights"
INSIGHTS_ALERT_NAME = "Claude API"


def get_smtp_password() -> str:
    env = os.environ.get("SMTP_PASSWORD")
    if env:
        return env.strip()
    return SMTP_PASSWORD_FILE.read_text().strip()


def get_anthropic_api_key() -> Optional[str]:
    """The Claude API key from ANTHROPIC_API_KEY or anthropic_api_key.txt, or
    None when neither holds one -- Claude is then simply off."""
    env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env:
        return env
    try:
        key = ANTHROPIC_API_KEY_FILE.read_text().strip()
    except FileNotFoundError:
        return None
    return key or None


def email_dry_run() -> bool:
    """JOBFINDER_DRY_RUN=1 turns every email into a log line. Set it on a
    development machine so test runs never reach the alert recipients."""
    return os.environ.get("JOBFINDER_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}

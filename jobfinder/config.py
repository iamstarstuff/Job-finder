import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "jobfinder.db"
LOG_PATH = BASE_DIR / "jobscraper.log"
ENRICHMENT_LOG_PATH = BASE_DIR / "enrichment.log"
TECH_LOG_PATH = BASE_DIR / "tech_scraper.log"
LEGACY_JOBS_JSON = BASE_DIR / "jobs.json"
SMTP_PASSWORD_FILE = BASE_DIR / "smtp_password.txt"

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


def get_smtp_password() -> str:
    env = os.environ.get("SMTP_PASSWORD")
    if env:
        return env.strip()
    return SMTP_PASSWORD_FILE.read_text().strip()

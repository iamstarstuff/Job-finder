import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = BASE_DIR / "jobfinder.db"
LOG_PATH = BASE_DIR / "jobscraper.log"
LEGACY_JOBS_JSON = BASE_DIR / "jobs.json"
SMTP_PASSWORD_FILE = BASE_DIR / "smtp_password.txt"

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
SMTP_USERNAME = "barvepratik96@gmail.com"
FROM_EMAIL = SMTP_USERNAME
ALERT_RECIPIENTS = ["barvepratik96@gmail.com"]  # DEV: switch back to ["vaidehipatil2011@gmail.com"] at merge
ERROR_RECIPIENTS = ["barvepratik96@gmail.com"]

REQUEST_TIMEOUT = 20  # seconds


def get_smtp_password() -> str:
    env = os.environ.get("SMTP_PASSWORD")
    if env:
        return env.strip()
    return SMTP_PASSWORD_FILE.read_text().strip()

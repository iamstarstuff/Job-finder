from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, List

from jobfinder import config, storage
from jobfinder.http_client import build_session
from jobfinder.models import Job
from jobfinder.runner import zero_result_is_suspicious
from jobfinder.tech_scrapers import TECH_SCRAPERS, matches_target_role

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: int
    new_jobs: Dict[str, List[Job]] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)
    zero_warnings: List[str] = field(default_factory=list)
    total_jobs: int = 0


def run_scrape(conn, session, now: str) -> RunResult:
    result = RunResult(run_id=storage.start_run(conn, now, "tech"))
    for company, scraper in TECH_SCRAPERS.items():
        try:
            listing = scraper(session)  # every Ireland/remote posting, unfiltered
        except Exception as exc:  # captured per company, reported, never swallowed
            log.error("Tech scraper failed for %s: %s", company, exc)
            result.failures[company] = str(exc)
            continue  # do NOT snapshot: failure must not deactivate existing jobs
        # The zero-result check runs on the raw listing, not the filtered
        # one: a company with plenty of postings but no target roles is a
        # genuine zero, and its old matching jobs must be closed -- not left
        # "active" forever under a layout-change alarm.
        if not listing and zero_result_is_suspicious(conn, company, now):
            log.warning("%s returned 0 jobs but previously had active jobs "
                        "- possible layout change", company)
            result.zero_warnings.append(company)
            continue  # treat like a failure for snapshot purposes
        jobs = [job for job in listing if matches_target_role(job.title)]
        result.total_jobs += len(jobs)
        new = storage.record_company_snapshot(conn, company, jobs, now)
        if new:
            result.new_jobs[company] = new
        log.info("Fetched %d tech jobs for %s (%d new)", len(jobs), company, len(new))
    storage.finish_run(
        conn, result.run_id, datetime.now().isoformat(timespec="seconds"),
        result.total_jobs, sum(len(v) for v in result.new_jobs.values()),
        result.failures,
    )
    return result


def is_due(conn, now: datetime) -> bool:
    """True when it is TECH_DAILY_HOUR or later and no tech run has started
    today. cron starts the scraper hourly, so a day the Mac slept through
    that hour is caught up at the next hour it is awake."""
    if now.hour < config.TECH_DAILY_HOUR:
        return False
    last = storage.last_run_started(conn, "tech")
    return last is None or last[:10] < now.date().isoformat()


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape tech roles, once a day.")
    parser.add_argument(
        "--force", action="store_true",
        help="Run now, even before the daily hour or when today's run has already happened.",
    )
    return parser.parse_args(argv)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[TimedRotatingFileHandler(
            str(config.TECH_LOG_PATH), when="W0", interval=1, backupCount=4
        )],
    )


def main(argv=None) -> None:
    args = parse_args(argv)
    setup_logging()
    try:
        started = datetime.now()
        conn = storage.connect(config.DB_PATH)
        if not args.force and not is_due(conn, started):
            return  # cron starts this hourly; only the day's first run from TECH_DAILY_HOUR scrapes
        now = started.isoformat(timespec="seconds")
        session = build_session()
        result = run_scrape(conn, session, now)
        from jobfinder import emailer  # local import, mirrors runner.py's own pattern
        emailer.send_tech_digest(conn, result)
    except Exception as exc:  # pipeline-wide safety net: never crash silently
        log.exception("Unhandled error in tech scraper run: %s", exc)
        try:
            from html import escape

            from jobfinder import emailer
            emailer.send_email(
                "Tech Job Scraper Crash",
                f"<pre>{escape(str(exc))}</pre>",
                config.ERROR_RECIPIENTS,
            )
        except Exception:
            log.exception("Failed to send tech crash notification email")


if __name__ == "__main__":
    main()

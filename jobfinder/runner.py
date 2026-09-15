from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, List

from jobfinder import config, storage
from jobfinder.http_client import build_session
from jobfinder.models import Job
from jobfinder.scrapers import SCRAPERS

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: int
    new_jobs: Dict[str, List[Job]] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)
    zero_warnings: List[str] = field(default_factory=list)
    total_jobs: int = 0


def zero_result_is_suspicious(conn, company: str, now: str) -> bool:
    """True when a company still has active jobs that were sighted within
    the grace window -- an empty scrape then looks like a broken scraper,
    not a genuine zero, and must not close those jobs. Once every active
    job has gone unseen for ZERO_RESULT_GRACE_DAYS, the zero is accepted."""
    last_seen = storage.latest_active_last_seen(conn, company)
    if last_seen is None:
        return False
    cutoff = datetime.fromisoformat(now) - timedelta(days=config.ZERO_RESULT_GRACE_DAYS)
    return datetime.fromisoformat(last_seen) >= cutoff


def run_scrape(conn, session, now: str) -> RunResult:
    result = RunResult(run_id=storage.start_run(conn, now, "pharma"))
    for company, scraper in SCRAPERS.items():
        try:
            jobs = scraper(session)
        except Exception as exc:  # captured per company, reported, never swallowed
            log.error("Scraper failed for %s: %s", company, exc)
            result.failures[company] = str(exc)
            continue  # do NOT snapshot: failure must not deactivate existing jobs
        if not jobs and zero_result_is_suspicious(conn, company, now):
            log.warning("%s returned 0 jobs but previously had active jobs "
                        "- possible layout change", company)
            result.zero_warnings.append(company)
            continue  # treat like a failure for snapshot purposes
        result.total_jobs += len(jobs)
        new = storage.record_company_snapshot(conn, company, jobs, now)
        if new:
            result.new_jobs[company] = new
        log.info("Fetched %d jobs for %s (%d new)", len(jobs), company, len(new))
    storage.finish_run(
        conn, result.run_id, datetime.now().isoformat(timespec="seconds"),
        result.total_jobs, sum(len(v) for v in result.new_jobs.values()),
        result.failures,
    )
    return result


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[TimedRotatingFileHandler(
            str(config.LOG_PATH), when="W0", interval=1, backupCount=4
        )],
    )


def main() -> None:
    setup_logging()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        conn = storage.connect(config.DB_PATH)
        migrated = storage.migrate_legacy_json(conn, config.LEGACY_JOBS_JSON, now)
        if migrated:
            log.info("Migrated %d jobs from legacy jobs.json", migrated)
        session = build_session()
        result = run_scrape(conn, session, now)
        # Email notifications are wired in Task 6 (emailer module).
        from jobfinder import emailer  # local import; module exists after Task 6
        emailer.send_run_notifications(conn, result)
    except Exception as exc:  # pipeline-wide safety net: never crash silently
        log.exception("Unhandled error in scraper run: %s", exc)
        try:
            from html import escape

            from jobfinder import emailer
            emailer.send_email(
                "Job Scraper Crash",
                f"<pre>{escape(str(exc))}</pre>",
                config.ERROR_RECIPIENTS,
            )
        except Exception:
            log.exception("Failed to send crash notification email")


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Dict, List

from jobfinder import config, storage
from jobfinder.http_client import build_session
from jobfinder.models import Job
from jobfinder.tech_scrapers import TECH_SCRAPERS

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    run_id: int
    new_jobs: Dict[str, List[Job]] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)
    zero_warnings: List[str] = field(default_factory=list)
    total_jobs: int = 0


def _had_active_jobs(conn, company: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) c FROM jobs WHERE company = ? AND is_active = 1", (company,)
    ).fetchone()
    return row["c"] > 0


def run_scrape(conn, session, now: str) -> RunResult:
    result = RunResult(run_id=storage.start_run(conn, now))
    for company, scraper in TECH_SCRAPERS.items():
        try:
            jobs = scraper(session)
        except Exception as exc:  # captured per company, reported, never swallowed
            log.error("Tech scraper failed for %s: %s", company, exc)
            result.failures[company] = str(exc)
            continue  # do NOT snapshot: failure must not deactivate existing jobs
        if not jobs and _had_active_jobs(conn, company):
            log.warning("%s returned 0 jobs but previously had active jobs "
                        "- possible layout change", company)
            result.zero_warnings.append(company)
            continue  # treat like a failure for snapshot purposes
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


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[TimedRotatingFileHandler(
            str(config.TECH_LOG_PATH), when="W0", interval=1, backupCount=4
        )],
    )


def main() -> None:
    setup_logging()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        conn = storage.connect(config.DB_PATH)
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

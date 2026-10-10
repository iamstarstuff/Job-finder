"""Entry point for the description/skills enrichment pipeline.
Deliberately separate from jobscraper.py / jobfinder.runner — this pipeline
must never share a failure path with the hourly alert scraper. It never
emails about its own crashes; the only email it can send is the Claude API
key/credit alert (once when it starts, once when it ends)."""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from jobfinder import config, enrichment, insights, storage
from jobfinder.http_client import build_session

log = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[TimedRotatingFileHandler(
            str(config.ENRICHMENT_LOG_PATH), when="W0", interval=1, backupCount=4
        )],
    )


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reextract", action="store_true",
        help="Skip fetching; re-run skill extraction over every stored description "
             "so job_skills matches the current SKILL_KEYWORDS vocabulary.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    setup_logging()
    try:
        conn = storage.connect(config.DB_PATH)
        if args.reextract:
            count = enrichment.reextract_skills(conn)
            log.info("Skill re-extraction complete: %d jobs reprocessed", count)
            return
        now = datetime.now().isoformat(timespec="seconds")
        session = build_session()
        result = enrichment.run(conn, session, now, client=insights.build_client())
        log.info("Enrichment complete: %d enriched, %d failed, %d read by Claude",
                 result.enriched, result.failed, result.insights)
        report, error = result.insight_alert
        if report:
            from jobfinder import emailer  # local import: only needed when there is news
            emailer.send_insights_status(conn, error)
    except Exception as exc:  # pipeline-wide safety net — this pipeline never emails on failure
        log.exception("Unhandled error in enrichment run: %s", exc)


if __name__ == "__main__":
    main()

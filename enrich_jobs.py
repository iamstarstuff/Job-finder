"""Entry point for the description/skills enrichment pipeline.
Deliberately separate from jobscraper.py / jobfinder.runner — this pipeline
must never share a failure path with the hourly alert scraper."""
from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

from jobfinder import config, enrichment, storage
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


def main() -> None:
    setup_logging()
    try:
        now = datetime.now().isoformat(timespec="seconds")
        conn = storage.connect(config.DB_PATH)
        session = build_session()
        result = enrichment.run(conn, session, now)
        log.info("Enrichment complete: %d enriched, %d failed", result.enriched, result.failed)
    except Exception as exc:  # pipeline-wide safety net — this pipeline never emails on failure
        log.exception("Unhandled error in enrichment run: %s", exc)


if __name__ == "__main__":
    main()

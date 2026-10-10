"""One-off: read every stored description and today's tech postings with
Claude through the Message Batches API (half price), and save the results
to job_insights. Without --yes it only prints what it would send and the
estimated cost.

    uv run python backfill_insights.py               # dry run: counts and estimate
    uv run python backfill_insights.py --yes         # submit, wait, save the results
    uv run python backfill_insights.py --resume ID   # collect a batch whose wait was interrupted

Errored, expired and refused items are left alone: the tech run and the
enrichment pass read them later (refusals with the realtime fallback)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request

from jobfinder import config, insights, storage, tech_runner
from jobfinder.http_client import MemoSession, build_session
from jobfinder.models import Job
from jobfinder.tech_scrapers import TECH_SCRAPERS

POLL_SECONDS = 60

Item = Tuple[Job, Optional[str], str]  # (job, description or None for title-only, sector)


def stored_items(conn) -> List[Item]:
    rows = storage.find_jobs_needing_insights(conn, insights.PROMPT_VERSION, limit=None, active_only=False)
    return [(Job(r["company"], r["title"], r["url"], r["portal_url"], r["closing_date"], r["sector"]),
             r["description"], r["sector"]) for r in rows]


def tech_posting_items(conn, session, skip_keys: Set[str]) -> List[Item]:
    """Today's tech postings without a saved reading. A posting whose
    description fetch fails is left for the daily tech run."""
    fetch_session = MemoSession(session)
    items: List[Item] = []
    seen = set(skip_keys)
    for company, scraper in TECH_SCRAPERS.items():
        try:
            listing = scraper(session)
        except Exception as exc:  # one broken scraper must not stop the backfill
            print(f"  {company}: scraper failed ({exc}); left for the tech run")
            continue
        for job in listing:
            if job.key in seen or storage.get_insight(conn, job.key, insights.PROMPT_VERSION):
                continue
            seen.add(job.key)
            description = tech_runner.posting_description(fetch_session, job)
            if description is tech_runner.FETCH_FAILED:
                continue
            items.append((job, description, "tech"))
    return items


def collect(conn, session) -> List[Item]:
    stored = stored_items(conn)
    return stored + tech_posting_items(conn, session, {job.key for job, _, _ in stored})


def print_plan(items: List[Item]) -> None:
    counts = Counter((sector, job.company) for job, _, sector in items)
    for (sector, company), count in sorted(counts.items()):
        print(f"  {sector:6} {company:24} {count:5}")
    contents = [insights.user_content(job, description, sector) for job, description, sector in items]
    title_only = sum(1 for _, description, _ in items if description is None)
    print(f"{len(items)} postings ({title_only} from the title alone), "
          f"estimated ${insights.estimate_cost(contents):.2f} at batch prices")


def submit(client, items: List[Item]) -> Tuple[str, Dict[str, dict]]:
    requests, state_items = [], {}
    for i, (job, description, sector) in enumerate(items):
        custom_id = f"job-{i:05d}"  # job keys are URLs, which custom_id doesn't allow
        requests.append(Request(custom_id=custom_id, params=MessageCreateParamsNonStreaming(
            **insights.batch_params(job, description, sector))))
        state_items[custom_id] = {
            "company": job.company, "title": job.title, "url": job.url,
            "portal_url": job.portal_url, "closing_date": job.closing_date,
            "sector": sector, "title_only": description is None,
        }
    # A batch of ~1,800 postings is a ~15 MB upload: allow more than the client's 60 s.
    batch = client.with_options(timeout=600.0).messages.batches.create(requests=requests)
    config.BACKFILL_STATE_PATH.write_text(json.dumps({"batch_id": batch.id, "items": state_items}))
    print(f"Submitted batch {batch.id} with {len(requests)} requests")
    return batch.id, state_items


def wait(client, batch_id: str) -> None:
    while True:
        batch = client.messages.batches.retrieve(batch_id)
        if batch.processing_status == "ended":
            return
        counts = batch.request_counts
        print(f"  {datetime.now():%H:%M} processing {counts.processing}, "
              f"succeeded {counts.succeeded}, errored {counts.errored}")
        time.sleep(POLL_SECONDS)


def save_results(conn, results: Iterable, state_items: Dict[str, dict], now: str) -> Tuple[Counter, float]:
    tally: Counter = Counter()
    spent = 0.0
    for entry in results:  # results arrive in any order: match by custom_id, never position
        item = state_items.get(entry.custom_id)
        if item is None:
            tally["unknown"] += 1
            continue
        if entry.result.type != "succeeded":
            tally[entry.result.type] += 1  # errored / canceled / expired: the regular passes retry
            continue
        job = Job(item["company"], item["title"], item["url"], item["portal_url"],
                  item["closing_date"], item["sector"])
        try:
            result = insights.parse_batch_message(entry.result.message, item["sector"], item["title_only"])
        except insights.InsightRefused:
            tally["refused"] += 1  # left for the realtime passes, which retry with the fallback
            continue
        except insights.InsightBadOutput as exc:
            row = insights.failure_row(job, item["sector"], exc, now, item["title_only"], via_batch=True)
            tally["failed"] += 1
        else:
            row = insights.result_row(job, item["sector"], result, now, via_batch=True)
            tally["ok"] += 1
        storage.save_insight(conn, row)
        spent += row["cost_usd"]
    return tally, spent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--yes", action="store_true", help="submit the batch, wait for it and save the results")
    group.add_argument("--resume", metavar="BATCH_ID", help="collect a batch that was already submitted")
    args = parser.parse_args(argv)

    conn = storage.connect(config.DB_PATH)
    client = insights.build_client()
    if args.resume:
        if client is None:
            print("No Claude API key: set ANTHROPIC_API_KEY or create anthropic_api_key.txt.")
            return 1
        state = json.loads(config.BACKFILL_STATE_PATH.read_text())
        if state["batch_id"] != args.resume:
            print(f"{config.BACKFILL_STATE_PATH.name} holds batch {state['batch_id']}, not {args.resume}.")
            return 1
        batch_id, state_items = args.resume, state["items"]
    else:
        items = collect(conn, build_session())
        print_plan(items)
        if not args.yes:
            print("Dry run: nothing sent. Run again with --yes to submit.")
            return 0
        if client is None:
            print("No Claude API key: set ANTHROPIC_API_KEY or create anthropic_api_key.txt.")
            return 1
        if not items:
            print("Nothing to read.")
            return 0
        batch_id, state_items = submit(client, items)
    wait(client, batch_id)
    tally, spent = save_results(conn, client.messages.batches.results(batch_id), state_items,
                                datetime.now().isoformat(timespec="seconds"))
    print("Results: " + ", ".join(f"{name} {count}" for name, count in sorted(tally.items())))
    print(f"Recorded cost: ${spent:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

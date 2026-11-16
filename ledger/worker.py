"""Scheduled account observations and requested research; never submits trades."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

from .broker import connected_broker
from .config import load_config
from .harness import Harness
from .market import MarketBrief
from .monitor import CloudMonitor, within_monitoring_hours
from .postgres_store import PostgresStore
from .quotes import Quotes
from .review_queue import ReviewQueue
from .store import now, open_store


def status(store, state, detail):
    store.save_trading_record(dict(id="render-readonly-monitor", kind="worker_status", created=now(),
        payload=dict(mode="read_only", state=state, detail=detail, last_updated_at=now())))


async def scheduled_check(store, connect=connected_broker):
    status(store, "running", "Syncing account observations and current market data. Order submission is disabled.")
    async with connect(store) as broker:
        # Only observational methods are invoked; ReadOnlyBroker rejects every write tool.
        observer = CloudMonitor(broker, store)
        snapshot = await observer.sync()
        await observer.reconcile(snapshot)
    brief = await MarketBrief(Quotes()).get()
    store.save_trading_record(dict(id=uuid.uuid4().hex, kind="market_observation", created=now(), payload=brief))
    # Claim only explicitly requested research baskets, never pick or size trades.
    queue = ReviewQueue(store, Harness(store))
    claim = await asyncio.to_thread(store.claim_research_review)
    if claim:
        await queue.review(claim)
    status(store, "complete", "Account and market observations saved. No trades were selected or submitted.")


async def main():
    load_config()
    if os.getenv("LEDGER_WORKER_ENABLED") != "1":
        raise ValueError("The hosted observation worker is not enabled")
    store = open_store()
    if not isinstance(store, PostgresStore):
        raise ValueError("The hosted observation worker requires Supabase Postgres")
    if not within_monitoring_hours(datetime.now(timezone.utc)):
        status(store, "waiting", "Outside the NYSE monitoring window; next scheduled check will retry.")
        return
    try:
        async with asyncio.timeout(1600):
            await scheduled_check(store)
    except Exception:
        status(store, "attention", "Hosted sync failed. Check the Robinhood connection and provider configuration; no orders were submitted.")
        print("Hosted observation check failed; reconnect Robinhood or inspect configuration.", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    asyncio.run(main())

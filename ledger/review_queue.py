"""On-demand research only: no trade planner, broker client or order submission."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .models import ResearchRequest
from .store import now


ACTIVE_ORDERS = {"review_requested", "awaiting_approval", "submission_unknown", "approved", "queued", "pending", "unconfirmed", "confirmed", "partially_filled"}


def release_stale_reviews(records):
    """Release orphaned research after a hard restart without repeating paid work."""
    updates = []
    for record in records:
        item = record["payload"]
        if record["kind"] != "trading_request" or not item.get("research_only") or item.get("status") != "researching":
            continue
        started = datetime.fromisoformat(item["started_at"])
        if (datetime.now(timezone.utc) - started).total_seconds() < 1800:
            continue
        item.update(status="failed", error="Research worker interrupted; submit a new review to retry.")
        updates.append(record)
        for cycle in records:
            if cycle["kind"] == "trading_cycle" and cycle["id"] == item.get("cycle_id"):
                cycle["payload"].update(status="interrupted", error=item["error"])
                updates.append(cycle)
    return updates


def claim_review(records):
    """Called under the store's transaction lock; return the next research claim."""
    if any(r["kind"] == "trading_request" and r["payload"].get("status") == "researching" for r in records):
        return None
    if any(r["kind"] == "trading_cycle" and r["payload"].get("status") == "researching" for r in records):
        return None
    if any(r["kind"] == "trade_event" and r["payload"].get("state") in ACTIVE_ORDERS for r in records):
        return None
    snapshots = [r for r in records if r["kind"] == "broker_snapshot"]
    if snapshots:
        account = max(snapshots, key=lambda r: r["created"])["payload"]
        if account.get("approvals") or any(o.get("state") not in {
            "filled", "cancelled", "rejected", "failed", "voided", "partially_filled_rest_cancelled"
        } for o in account.get("orders", [])):
            return None
    pending = [r for r in records if r["kind"] == "trading_request" and r["payload"].get("status") == "research_queued"]
    if not pending:
        return None
    record = min(pending, key=lambda r: r["created"])
    record["payload"].update(status="researching", started_at=now(), cycle_id=uuid.uuid4().hex)
    return record


class ReviewQueue:
    def __init__(self, store, harness):
        self.store = store
        self.harness = harness
        self.wake = asyncio.Event()

    async def run(self):
        while True:
            self.wake.clear()
            try:
                record = await asyncio.to_thread(self.store.claim_research_review)
                if record:
                    await self.review(record)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).warning("Research queue temporarily unavailable; retrying shortly")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=5)
            except TimeoutError:
                pass

    async def review(self, request):
        cycle = dict(id=request["payload"]["cycle_id"], kind="trading_cycle", created=now(),
                     payload=dict(status="researching", research_only=True,
                                  tickers=request["payload"]["tickers"], candidates=[]))
        try:
            async with asyncio.timeout(1500):
                await asyncio.to_thread(self.store.save_trading_record, cycle)
                for symbol in request["payload"]["tickers"]:
                    day = datetime.now(ZoneInfo("America/New_York")).date()
                    run = await self.harness.run(ResearchRequest(ticker=symbol, as_of=day, mode="live"))
                    cycle["payload"]["candidates"].append(dict(
                        ticker=symbol, run_id=run["id"], status=run["status"],
                        decision=run.get("decision"), error=run.get("error"),
                        reports=run.get("reports", {}), metrics=run.get("metrics", {}),
                        trace=run.get("trace", []), evidence=run.get("snapshot", {}).get("evidence", [])))
                    await asyncio.to_thread(self.store.save_trading_record, cycle)
                failed = any(c["status"] != "complete" for c in cycle["payload"]["candidates"])
                cycle["payload"].update(status="failed" if failed else "complete", completed_at=now(),
                    reason="Research review only. No trade proposal or order was created.")
                request["payload"].update(status="failed" if failed else "complete", completed_at=now())
        except (Exception, asyncio.CancelledError) as exc:
            cycle["payload"].update(status="interrupted", error="Research interrupted. Saved findings remain available; submit a new review to retry.")
            request["payload"].update(status="failed", completed_at=now())
            if isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            await asyncio.to_thread(self.store.save_trading_record, cycle)
            await asyncio.to_thread(self.store.save_trading_record, request)

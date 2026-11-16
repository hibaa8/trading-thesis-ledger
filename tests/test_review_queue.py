import asyncio
import time

from fastapi.testclient import TestClient

from ledger.api import create_app
from ledger.harness import Harness
from ledger.review_queue import ReviewQueue
from ledger.store import Store


def queued(identity="first", status="research_queued"):
    return dict(id=identity, kind="trading_request", created="2026-11-16T20:00:00Z",
                payload=dict(tickers=["SPY", "AMZN"], status=status, research_only=True))


def test_claim_is_serial_and_cancelled_reviews_are_skipped(tmp_path):
    store = Store(tmp_path)
    store.save_trading_record(queued())
    store.save_trading_record(queued("second"))
    store.cancel_trading_request("first")
    claim = store.claim_research_review()
    assert claim["id"] == "second"
    assert claim["payload"]["status"] == "researching"
    assert store.claim_research_review() is None


def test_active_order_or_review_blocks_research_until_finished(tmp_path):
    store = Store(tmp_path)
    store.save_trading_record(queued())
    snapshot = dict(id="snapshot", kind="broker_snapshot", created="2026-11-16T20:00:00Z",
                    payload=dict(approvals=[], orders=[dict(state="confirmed")]))
    store.save_trading_record(snapshot)
    assert store.claim_research_review() is None
    snapshot["payload"]["orders"][0]["state"] = "filled"
    store.save_trading_record(snapshot)
    cycle = dict(id="cycle", kind="trading_cycle", created=snapshot["created"], payload=dict(status="researching"))
    store.save_trading_record(cycle)
    assert store.claim_research_review() is None
    cycle["payload"]["status"] = "complete"
    store.save_trading_record(cycle)
    assert store.claim_research_review()["id"] == "first"


def test_submit_wakes_research_immediately_and_never_creates_trade(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PUBLIC", "1")
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner")
    calls = []

    async def fake_run(self, request):
        calls.append(request.ticker)
        return dict(id=request.ticker, status="complete", reports={}, decision=dict(stance="neutral"))

    monkeypatch.setattr(Harness, "run", fake_run)
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        headers = {"Authorization": "Bearer owner"}
        assert client.post("/api/trading/reviews", json={"tickers": ["SPY", "AMZN"]}).status_code == 401
        assert client.post("/api/trading/reviews", headers=headers, json={"tickers": ["SPY", "bad!"]}).status_code == 422
        result = client.post("/api/trading/reviews", headers=headers, json={"tickers": ["spy", "amzn"]})
        assert result.status_code == 202
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            data = client.get("/api/trading", headers=headers).json()
            if data["requests"] and data["requests"][0]["payload"]["status"] == "complete":
                break
            time.sleep(.02)
        assert calls == ["SPY", "AMZN"]
        assert data["requests"][0]["payload"]["status"] == "complete"
        assert data["cycles"][0]["payload"]["research_only"] is True
        assert len(data["cycles"][0]["payload"]["candidates"]) == 2
        assert data["events"] == []
        assert "proposal" not in data["cycles"][0]["payload"]


def test_pending_approval_defers_submission_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner")
    store = Store(tmp_path)
    store.save_trading_record(dict(id="snapshot", kind="broker_snapshot", created="2026-11-16T20:00:00Z",
                                  payload=dict(approvals=[dict(id="approval")], orders=[])))
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        headers = {"Authorization": "Bearer owner"}
        a = client.post("/api/trading/reviews", headers=headers, json={"tickers": ["SPY", "AMZN"]}).json()
        b = client.post("/api/trading/reviews", headers=headers, json={"tickers": ["SPY", "AMZN"]}).json()
        assert a["id"] == b["id"]
        assert b["payload"]["status"] == "research_queued"
        assert client.delete("/api/trading/requests/" + a["id"], headers=headers).status_code == 200


def test_interrupted_review_does_not_leave_workflow_busy(tmp_path):
    store = Store(tmp_path)
    store.save_trading_record(queued())

    class FailingHarness:
        async def run(self, request):
            raise RuntimeError("Provider failed")

    asyncio.run(ReviewQueue(store, FailingHarness()).review(store.claim_research_review()))
    records = store.trading_records()
    assert next(r for r in records if r["kind"] == "trading_request")["payload"]["status"] == "failed"
    assert next(r for r in records if r["kind"] == "trading_cycle")["payload"]["status"] == "interrupted"
    store.save_trading_record(queued("retry"))
    assert store.claim_research_review()["id"] == "retry"


def test_orphaned_research_is_released_without_repeating_paid_work(tmp_path):
    store = Store(tmp_path)
    old = queued("orphan", "researching")
    old["payload"].update(started_at="2026-01-01T00:00:00Z", cycle_id="old-cycle")
    store.save_trading_record(old)
    store.save_trading_record(dict(id="old-cycle", kind="trading_cycle", created=old["created"],
                                  payload=dict(status="researching", research_only=True)))
    store.save_trading_record(queued("next"))
    assert store.claim_research_review()["id"] == "next"
    saved = {r["id"]: r for r in store.trading_records()}
    assert saved["orphan"]["payload"]["status"] == "failed"
    assert saved["old-cycle"]["payload"]["status"] == "interrupted"

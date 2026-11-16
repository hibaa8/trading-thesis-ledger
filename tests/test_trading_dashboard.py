import hashlib
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from ledger.api import create_app
from ledger.store import Store
from ledger.trading_dashboard import broker_snapshot, funding_status


def test_trading_is_private_even_on_public_site(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PUBLIC", "1")
    monkeypatch.setenv("LEDGER_API_TOKEN", "public-workspace-secret")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "private-owner-secret")
    record = dict(id="snapshot1", kind="broker_snapshot", created=datetime.now(timezone.utc).isoformat(),
                  payload={"account_value": "20", "orders": [], "buying_power": "20", "orders_complete": True})
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        assert client.get("/api/trading").status_code == 401
        assert client.get("/api/trading", headers={"Authorization":"Bearer public-workspace-secret"}).status_code == 401
        headers = {"Authorization":"Bearer private-owner-secret"}
        assert client.post("/api/trading/records", headers=headers, json=record).status_code == 200
        response = client.get("/api/trading", headers=headers)
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["snapshot"]["payload"]["account_value"] == "20"
        assert client.get("/api/runs").json() == []
        assert client.get("/api/memories").json() == []
        assert client.post("/api/trading/records", headers={**headers,"Origin":"https://evil.example"}, json=record).status_code == 403


def test_digest_access_never_appears_in_dashboard(tmp_path, monkeypatch):
    monkeypatch.delenv("LEDGER_TRADING_TOKEN", raising=False)
    monkeypatch.delenv("LEDGER_API_TOKEN", raising=False)
    store = Store(tmp_path)
    store.save_trading_record(dict(id="owner",kind="trading_access",created="2026-11-16T20:00:00Z",
        payload={"sha256":hashlib.sha256(b"owner-key").hexdigest()}))
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        result=client.get("/api/trading",headers={"Authorization":"Bearer owner-key"})
        assert result.status_code == 200
        assert "sha256" not in result.text
        assert client.get("/api/trading").status_code == 401


def test_trial_budget_counts_approvals_and_fills_once():
    snapshot={"buying_power":"20", "orders_complete":True,"orders":[]}
    event={"payload":{"state":"awaiting_approval","side":"buy","amount_usd":"20","approval_id":"approval1"}}
    assert funding_status(snapshot,[event])["remaining"] == "0"
    snapshot["orders"]=[{"id":"order1","ref_id":"approval1","state":"filled","side":"buy",
                          "cumulative_quantity":"0.1","average_price":"200"}]
    result=funding_status(snapshot,[event])
    assert result["spent"] == "20.0"
    assert result["reserved"] == "0"
    assert result["remaining"] == "0"
    snapshot["orders"].append({"id":"sell1","state":"filled","side":"sell","cumulative_quantity":".1","average_price":"210"})
    assert funding_status(snapshot,[])["remaining"] == "0"


def test_broker_deposit_is_not_profit():
    record=broker_snapshot({"total_value":"20","cash":"20","buying_power":{"unleveraged_buying_power":"20"}},
        {"positions":[]},{"results":[]},{"orders":[]},{"approvals":[]},
        {"setting":{"account_number":"account2100","human_must_approve_trades":True}},
        {"account_number":"account2100","total_returns":"0","window":"all"})
    assert record.payload["realized_pnl"] == "0"
    assert record.payload["unrealized_pnl"] == "0"
    assert record.payload["account_value"] == "20"
    assert "account2100" not in record.model_dump_json()


def test_multiple_buy_proposals_cannot_reserve_same_trial_cash(tmp_path):
    import pytest
    store=Store(tmp_path)
    store.save_trading_record(dict(id="s1",kind="broker_snapshot",created="2026-11-16T20:00:00Z",
        payload={"orders":[],"orders_complete":True,"buying_power":"20"}))
    def event(identity, state="review_requested"):
        return dict(id=identity,kind="trade_event",created="2026-11-16T20:01:00Z",
            payload=dict(proposal_id=identity,symbol="SPY",side="buy",amount_usd="20.00",state=state))
    store.save_trading_record(event("first"))
    with pytest.raises(ValueError,match="remaining funding"):
        store.save_trading_record(event("second"))
    store.save_trading_record(event("first","awaiting_approval"))
    events=[r for r in store.trading_records() if r["kind"]=="trade_event"]
    assert len(events)==1
    assert events[0]["payload"]["history"][0]["state"]=="review_requested"


def test_remove_queued_review_is_private_and_cannot_be_resurrected(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_PUBLIC", "1")
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace-secret")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner-secret")
    headers = {"Authorization": "Bearer owner-secret"}
    record = dict(id="review1", kind="trading_request", created="2026-11-16T20:41:08Z",
                  payload={"tickers": ["AAOI", "AXTI", "MRVL"], "status": "queued"})
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        assert client.post("/api/trading/records", headers=headers, json=record).status_code == 200
        path = "/api/trading/requests/review1"
        assert client.delete(path).status_code == 401
        assert client.delete(path, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        assert client.delete(path, headers=headers).status_code == 200
        assert client.delete(path, headers=headers).status_code == 200
        # A worker holding an older copy cannot resurrect a cancelled request.
        record["payload"]["status"] = "complete"
        assert client.post("/api/trading/records", headers=headers, json=record).status_code == 200
        requests = client.get("/api/trading", headers=headers).json()["requests"]
        assert requests[0]["payload"]["status"] == "cancelled"
        assert client.delete("/api/trading/requests/missing", headers=headers).status_code == 404
        record["id"] = "completed"
        assert client.post("/api/trading/records", headers=headers, json=record).status_code == 200
        assert client.delete("/api/trading/requests/completed", headers=headers).status_code == 409

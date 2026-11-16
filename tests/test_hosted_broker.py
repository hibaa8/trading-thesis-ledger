import asyncio
import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from ledger.api import create_app
from ledger.broker import BrokerVault, ReadOnlyBroker
from ledger.config import BrokerCallbackLogFilter
from ledger.postgres_store import PostgresStore


class FakeDB:
    payload = None

    def execute(self, sql, args=None):
        if sql.startswith("SELECT payload"):
            return SimpleNamespace(fetchone=lambda: (self.payload,) if self.payload else None)
        if sql.startswith("INSERT"):
            self.payload = args[-1].obj
        return self


class FakeStore(PostgresStore):
    def __init__(self):
        self.db = FakeDB()

    @contextmanager
    def _db(self):
        yield self.db


def test_oauth_pkce_state_encryption_and_refresh(monkeypatch):
    monkeypatch.setenv("LEDGER_BROKER_ENCRYPTION_KEY", "test-secret-" * 5)
    store = FakeStore()
    vault = BrokerVault(store)
    posts = []

    def post(url, **kwargs):
        posts.append((url, kwargs))
        if "register" in url:
            data = {"client_id": "test-client"}
        elif kwargs["data"]["grant_type"] == "refresh_token":
            data = {"access_token": "refreshed-private-token", "expires_in": 3600}
        else:
            data = {"access_token": "private-access-token", "refresh_token": "private-refresh-token", "expires_in": 0}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    monkeypatch.setattr("ledger.broker.httpx.post", post)
    url, state = vault.begin()
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert urlparse(url).netloc == "robinhood.com"
    with pytest.raises(ValueError):
        vault.finish("code", state, "wrong-browser")
    vault.finish("code", state, state)
    assert "private-access-token" not in json.dumps(store.db.payload)
    assert "private-refresh-token" not in json.dumps(store.db.payload)
    assert vault.status() == {"connected": True, "mode": "read_only"}
    assert vault.access_token() == "refreshed-private-token"
    # Refresh-token rotation may omit a new refresh token; retain the old one.
    assert vault.mutate(lambda data: data["tokens"]["refresh_token"]) == "private-refresh-token"
    with pytest.raises(ValueError):
        vault.finish("code", state, state)


def test_broker_rejects_order_tools_before_contacting_server():
    class Session:
        async def call_tool(self, *args):
            raise AssertionError("Order tool reached broker")

    client = ReadOnlyBroker(Session())
    for tool in ["place_equity_order", "review_equity_order", "cancel_equity_order", "create_scan"]:
        with pytest.raises(ValueError, match="read-only"):
            asyncio.run(client.call(tool))


def test_readonly_pagination_is_complete_and_detects_loops():
    class Session:
        calls = 0

        async def call_tool(self, name, arguments):
            self.calls += 1
            return SimpleNamespace(isError=False, structuredContent={"data": {"positions": [{"symbol": "SPY"}], "next": "same"}}, content=[])

    with pytest.raises(ValueError, match="pagination"):
        asyncio.run(ReadOnlyBroker(Session()).pages("get_equity_positions", "positions"))


def test_callback_errors_and_connection_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner")
    with TestClient(create_app(tmp_path), base_url="http://localhost") as client:
        assert client.get("/api/trading/broker").status_code == 401
        result = client.get("/api/trading/broker", headers={"Authorization": "Bearer owner"})
        assert result.json()["connected"] is False
        assert "encryption" not in result.text
        callback = client.get("/broker/callback?code=secret-code&state=wrong")
        assert callback.status_code == 400
        assert "secret-code" not in callback.text
        assert callback.headers["cache-control"] == "no-store"


def test_callback_code_is_redacted_in_access_logs():
    record = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("client", "GET", "/broker/callback?code=secret&state=private", "1.1", 303), None)
    BrokerCallbackLogFilter().filter(record)
    assert "secret" not in record.getMessage()
    assert "/broker/callback" in record.getMessage()


def test_account_sync_matches_numeric_pnl_account_before_normalizing(tmp_path, monkeypatch):
    from ledger.monitor import CloudMonitor
    from ledger.store import Store
    monkeypatch.setenv("LEDGER_BROKER_ACCOUNT_LAST4", "2100")

    class Broker:
        pnl_account = "123456"

        async def call(self, name, **args):
            if name == "get_accounts":
                return {"accounts": [dict(account_number="MCP2100", rhs_account_number="123456", agentic_allowed=True, state="active")]}
            if name == "get_portfolio":
                return dict(total_value="20", cash="20", buying_power={"unleveraged_buying_power": "20"})
            if name == "get_trade_approval_setting":
                return {"setting": dict(account_number="MCP2100", human_must_approve_trades=True)}
            if name == "get_realized_pnl":
                assert args["account_number"] == "123456"
                return dict(account_number=self.pnl_account, total_returns="0", window="all")
            raise AssertionError(name)

        async def pages(self, name, field, **args):
            return {field: [], "next": None}

    broker = Broker()
    monitor = CloudMonitor(broker, Store(tmp_path))
    snapshot = asyncio.run(monitor.sync())
    assert snapshot["account_last4"] == "2100"
    assert snapshot["realized_pnl"] == "0"
    broker.pnl_account = "different-account"
    with pytest.raises(ValueError, match="P&L"):
        asyncio.run(monitor.sync())


def test_scheduled_check_only_syncs_observations(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from ledger import worker
    from ledger.store import Store
    calls = []

    class Observer:
        def __init__(self, broker, store):
            pass

        async def sync(self):
            calls.append("sync")
            return {}

        async def reconcile(self, snapshot):
            calls.append("reconcile")

        async def tick(self):
            raise AssertionError("Autonomous trading monitor must not run")

    class Brief:
        def __init__(self, quotes):
            pass

        async def get(self):
            return {"quotes": [], "headlines": []}

    @asynccontextmanager
    async def connect(store):
        yield object()

    monkeypatch.setattr(worker, "CloudMonitor", Observer)
    monkeypatch.setattr(worker, "MarketBrief", Brief)
    store = Store(tmp_path)
    asyncio.run(worker.scheduled_check(store, connect))
    assert calls == ["sync", "reconcile"]
    records = store.trading_records()
    assert not any(r["kind"] == "trade_event" for r in records)
    assert next(r for r in records if r["kind"] == "worker_status")["payload"]["state"] == "complete"
    assert any(r["kind"] == "market_observation" for r in records)


def test_missing_broker_grant_still_saves_market_observations(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from ledger import worker
    from ledger.broker import BrokerAuthorizationRequired
    from ledger.store import Store

    class Brief:
        def __init__(self, quotes):
            pass

        async def get(self):
            return {"quotes": [], "headlines": []}

    @asynccontextmanager
    async def disconnected(store):
        raise BrokerAuthorizationRequired("No grant")
        yield

    monkeypatch.setattr(worker, "MarketBrief", Brief)
    store = Store(tmp_path)
    asyncio.run(worker.scheduled_check(store, disconnected))
    records = store.trading_records()
    assert any(r["kind"] == "market_observation" for r in records)
    state = next(r for r in records if r["kind"] == "worker_status")["payload"]
    assert state["state"] == "connection_required"
    assert not any(r["kind"] in {"trade_event", "broker_snapshot"} for r in records)

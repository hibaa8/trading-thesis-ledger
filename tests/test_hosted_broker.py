import asyncio
import json
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from ledger.api import create_app
from ledger.broker import BrokerVault, ReadOnlyBroker, SERVER, CALLBACK, BrokerOAuthError
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
            data = {"client_id": "test-client", "redirect_uris": [CALLBACK]}
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
        vault.finish("code", state, "wrong-browser", SERVER)
    vault.finish("code", state, state, SERVER)
    assert "private-access-token" not in json.dumps(store.db.payload)
    assert "private-refresh-token" not in json.dumps(store.db.payload)
    assert vault.status()["connected"] is True
    assert vault.status()["oauth"]["stage"] == "connected"
    assert vault.access_token() == "refreshed-private-token"
    # Refresh-token rotation may omit a new refresh token; retain the old one.
    assert vault.mutate(lambda data: data["tokens"]["refresh_token"]) == "private-refresh-token"
    with pytest.raises(ValueError):
        vault.finish("code", state, state, SERVER)


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


def oauth_vault(monkeypatch, *, callback=CALLBACK):
    monkeypatch.setenv("LEDGER_BROKER_ENCRYPTION_KEY", "test-encryption-secret-" * 3)
    monkeypatch.setenv("LEDGER_BROKER_CALLBACK_URL", callback)
    vault = BrokerVault(FakeStore())
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        data = ({"client_id": "test-client", "redirect_uris": kwargs["json"]["redirect_uris"], "token_endpoint_auth_method": "none"}
                if "register" in url else
                {"access_token": "test-private-access", "refresh_token": "test-private-refresh", "expires_in": 3600})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    monkeypatch.setattr("ledger.broker.httpx.post", post)
    return vault, calls


def test_pkce_matches_rfc7636_example(monkeypatch):
    vault, _ = oauth_vault(monkeypatch)
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    monkeypatch.setattr("ledger.broker.secrets.token_urlsafe", lambda length: "test-state" if length == 32 else verifier)
    url, state = vault.begin()
    query = parse_qs(urlparse(url).query)
    assert query["code_challenge"] == ["E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"]
    assert query["state"] == [state]
    assert query["resource"] == [SERVER]
    assert query["redirect_uri"] == [CALLBACK]


@pytest.mark.parametrize("issuer", ["", "https://attacker.example"])
def test_issuer_validation_precedes_token_exchange(monkeypatch, issuer):
    vault, calls = oauth_vault(monkeypatch)
    _, state = vault.begin()
    calls.clear()
    with pytest.raises(BrokerOAuthError) as error:
        vault.finish("private-code", state, state, issuer)
    assert error.value.stage == "issuer_validation"
    assert calls == []
    assert vault.status()["oauth"]["stage"] == "issuer_validation"
    assert vault.status()["connected"] is False


def test_configured_callback_is_used_in_registration_and_exchange(monkeypatch):
    configured = "https://localhost/broker/callback"
    vault, calls = oauth_vault(monkeypatch, callback=configured)
    url, state = vault.begin()
    assert calls[0][1]["json"]["redirect_uris"] == [configured]
    assert calls[0][1]["json"]["application_type"] == "web"
    assert parse_qs(urlparse(url).query)["redirect_uri"] == [configured]
    # The code must be exchanged against the URI that started this flow, even after a config change.
    monkeypatch.setenv("LEDGER_BROKER_CALLBACK_URL", CALLBACK)
    vault.finish("code", state, state, SERVER)
    body = calls[-1][1]["data"]
    assert body["redirect_uri"] == configured
    assert body["grant_type"] == "authorization_code"
    assert body["resource"] == SERVER
    assert "client_secret" not in body


def test_browser_callback_happy_path_cookie_and_private_status(tmp_path, monkeypatch):
    vault, calls = oauth_vault(monkeypatch, callback="https://localhost/broker/callback")
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner")
    monkeypatch.setattr("ledger.broker.BrokerVault", lambda store: vault)
    with TestClient(create_app(tmp_path), base_url="https://localhost") as client:
        headers = {"Authorization": "Bearer owner"}
        begin = client.post("/api/trading/broker/connect", headers=headers)
        assert begin.status_code == 200
        cookie = begin.headers["set-cookie"]
        for part in ["HttpOnly", "Secure", "SameSite=lax", "Path=/broker/callback", "Max-Age=600"]:
            assert part in cookie
        assert begin.headers["cache-control"] == "private, no-store"
        state = parse_qs(urlparse(begin.json()["url"]).query)["state"][0]
        returned = client.get("/broker/callback", params={"state": state, "code": "test-code", "iss": SERVER}, follow_redirects=False)
        assert returned.status_code == 303
        assert returned.headers["location"] == "/#trading"
        assert returned.headers["referrer-policy"] == "no-referrer"
        assert "Max-Age=0" in returned.headers["set-cookie"]
        result = client.get("/api/trading/broker", headers=headers)
        assert result.json()["connected"] is True
        assert result.json()["oauth"]["stage"] == "connected"
        assert "test-private" not in result.text
        assert client.get("/api/trading/broker").status_code == 401


def test_invalid_browser_state_cannot_exchange_or_poison_status(monkeypatch):
    vault, calls = oauth_vault(monkeypatch)
    _, state = vault.begin()
    calls.clear()
    with pytest.raises(BrokerOAuthError):
        vault.finish("code", state, "wrong-cookie", SERVER)
    assert calls == []
    assert vault.status()["oauth"]["stage"] == "authorization_started"
    assert vault.status()["connected"] is False


def test_token_exchange_failure_has_safe_stage_diagnostic(monkeypatch):
    vault, _ = oauth_vault(monkeypatch)
    _, state = vault.begin()

    def fail(*args, **kwargs):
        import httpx
        raise httpx.ConnectError("secret provider details that must not be exposed")

    monkeypatch.setattr("ledger.broker.httpx.post", fail)
    with pytest.raises(BrokerOAuthError) as result:
        vault.finish("secret-code", state, state, SERVER)
    assert result.value.stage == "token_exchange"
    status = vault.status()
    assert status["oauth"]["stage"] == "token_exchange"
    assert "secret" not in json.dumps(status)


def test_callback_provider_denial_never_exchanges_code(monkeypatch):
    vault, calls = oauth_vault(monkeypatch)
    _, state = vault.begin()
    calls.clear()
    with pytest.raises(BrokerOAuthError) as result:
        vault.finish("", state, state, SERVER, "access_denied")
    assert result.value.stage == "provider_error"
    assert calls == []


@pytest.mark.parametrize("configured", ["http://localhost/broker/callback", "https://other.example/broker/callback", "https://localhost/wrong-path"])
def test_callback_configuration_rejected_before_registration(tmp_path, monkeypatch, configured):
    monkeypatch.setenv("LEDGER_API_TOKEN", "workspace")
    monkeypatch.setenv("LEDGER_TRADING_TOKEN", "owner")
    monkeypatch.setenv("LEDGER_BROKER_CALLBACK_URL", configured)
    with TestClient(create_app(tmp_path), base_url="https://localhost") as client:
        response = client.post("/api/trading/broker/connect", headers={"Authorization": "Bearer owner"})
        assert response.status_code == 503


def test_registration_rejects_a_different_redirect(monkeypatch):
    vault, _ = oauth_vault(monkeypatch)
    response = SimpleNamespace(raise_for_status=lambda: None,
        json=lambda: {"client_id": "client", "redirect_uris": ["https://other.example/callback"]})
    monkeypatch.setattr("ledger.broker.httpx.post", lambda *a, **kw: response)
    with pytest.raises(BrokerOAuthError) as result:
        vault.begin()
    assert result.value.stage == "registration_redirect"
    assert vault.status()["connected"] is False


def test_changed_callback_refreshes_cached_registration(monkeypatch):
    vault, calls = oauth_vault(monkeypatch)
    vault.begin()
    monkeypatch.setenv("LEDGER_BROKER_CALLBACK_URL", "https://localhost/broker/callback")
    vault.begin()
    assert len(calls) == 2
    assert calls[-1][1]["json"]["redirect_uris"] == ["https://localhost/broker/callback"]


def test_status_read_does_not_rewrite_encrypted_credentials(monkeypatch):
    vault, _ = oauth_vault(monkeypatch)
    vault.begin()
    before = json.dumps(vault.store.db.payload)
    vault.status()
    assert json.dumps(vault.store.db.payload) == before

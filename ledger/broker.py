"""Hosted OAuth and a strictly read-only client for Robinhood's official MCP."""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from psycopg.types.json import Jsonb

from .postgres_store import PostgresStore
from .store import now

SERVER = "https://agent.robinhood.com/mcp/trading"
REGISTER = "https://agent.robinhood.com/oauth/trading/register"
AUTHORIZE = "https://robinhood.com/oauth"
TOKEN = "https://api.robinhood.com/oauth2/token/"
CALLBACK = "https://thesis-ledger.onrender.com/broker/callback"
READ_TOOLS = frozenset({"get_accounts", "get_portfolio", "get_equity_positions", "get_equity_orders",
    "get_equity_quotes", "get_trade_approvals", "get_trade_approval_setting", "get_realized_pnl"})


def callback_url():
    value = os.getenv("LEDGER_BROKER_CALLBACK_URL", CALLBACK)
    parsed = urlparse(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path != "/broker/callback"):
        raise ValueError("Configure an HTTPS broker callback ending in /broker/callback")
    return value


class BrokerOAuthError(ValueError):
    def __init__(self, stage):
        self.stage = stage
        super().__init__("Robinhood authorization failed at " + stage)


class BrokerAuthorizationRequired(ValueError):
    """No usable grant exists; research observations can still run."""


class BrokerVault:
    def __init__(self, store):
        if not isinstance(store, PostgresStore):
            raise ValueError("Hosted brokerage requires durable Postgres storage")
        key = os.getenv("LEDGER_BROKER_ENCRYPTION_KEY", "")
        if len(key) < 32:
            raise ValueError("Hosted brokerage encryption is not configured")
        self.cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
        self.store = store

    def mutate(self, action):
        # Serialize token refreshes across web/cron processes. Never return secrets to APIs.
        with self.store._db() as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext('thesis-ledger-broker-oauth'))")
            row = db.execute("SELECT payload FROM thesis_ledger.records WHERE workspace='owner' AND kind='broker_auth' AND id='robinhood'").fetchone()
            data = json.loads(self.cipher.decrypt(row[0]["encrypted"].encode())) if row else {}
            original = json.dumps(data, sort_keys=True)
            result = action(data)
            if json.dumps(data, sort_keys=True) == original:
                return result
            encrypted = self.cipher.encrypt(json.dumps(data).encode()).decode()
            db.execute("INSERT INTO thesis_ledger.records VALUES (%s,%s,%s,%s,%s) ON CONFLICT (workspace,kind,id) DO UPDATE SET payload=excluded.payload",
                       ("owner", "broker_auth", "robinhood", now(), Jsonb({"encrypted": encrypted})))
            return result

    def status(self):
        return self.mutate(lambda data: {"connected": bool(data.get("tokens")), "mode": "read_only",
                                       "oauth": data.get("oauth_diagnostic", {})})

    def begin(self):
        callback = callback_url()
        def prepare(data):
            client = data.get("client")
            if not client or callback not in client.get("redirect_uris", []) or data.get("registration_version") != 1:
                r = httpx.post(REGISTER, json={"client_name": "Thesis Ledger account monitor",
                    "redirect_uris": [callback], "application_type": "web", "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                    "scope": "internal"}, timeout=20)
                r.raise_for_status()
                client = r.json()
                if not client.get("client_id") or callback not in client.get("redirect_uris", []):
                    raise BrokerOAuthError("registration_redirect")
                if client.get("token_endpoint_auth_method", "none") != "none":
                    raise BrokerOAuthError("registration_auth_method")
                data["client"] = client
                data["registration_version"] = 1
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            data["pending"] = dict(state=state, verifier=verifier, expires=time.time() + 600, callback=callback)
            data["oauth_diagnostic"] = dict(stage="authorization_started", at=now())
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            query = dict(response_type="code", client_id=client["client_id"], redirect_uri=callback,
                         scope="internal", state=state, code_challenge=challenge, code_challenge_method="S256", resource=SERVER)
            return AUTHORIZE + "?" + urlencode(query), state
        return self.mutate(prepare)

    def finish(self, code, state, cookie_state, issuer="", error=""):
        def exchange(data):
            pending = data.get("pending", {})
            if (not state or not cookie_state or pending.get("expires", 0) < time.time()
                or not hmac.compare_digest(state, cookie_state)
                or not hmac.compare_digest(state, pending.get("state", ""))):
                # Unsolicited or stale callbacks cannot alter a legitimate flow's diagnostics.
                return "state_validation"
            def fail(stage):
                data["oauth_diagnostic"] = dict(stage=stage, at=now())
                data.pop("pending", None)
                return stage
            data["oauth_diagnostic"] = dict(stage="callback_received", at=now())
            # Robinhood advertises RFC 9207 issuer-bound authorization responses.
            if issuer != SERVER:
                return fail("issuer_validation")
            if error:
                return fail("provider_error")
            if not code:
                return fail("missing_code")
            callback = pending.get("callback", CALLBACK)
            try:
                r = httpx.post(TOKEN, data=dict(grant_type="authorization_code", code=code,
                    client_id=data["client"]["client_id"], redirect_uri=callback,
                    code_verifier=pending["verifier"], resource=SERVER), timeout=20)
                r.raise_for_status()
                tokens = r.json()
            except (httpx.HTTPError, ValueError):
                return fail("token_exchange")
            if not isinstance(tokens, dict) or not tokens.get("access_token"):
                return fail("token_response")
            try:
                duration = float(tokens.get("expires_in", 300))
                if not 0 <= duration <= 31536000:
                    return fail("token_response")
            except (ValueError, TypeError):
                return fail("token_response")
            data["tokens"] = tokens
            data["expires_at"] = time.time() + duration
            data["oauth_diagnostic"] = dict(stage="connected", at=now())
            data.pop("pending", None)
            return None
        failure = self.mutate(exchange)
        if failure:
            raise BrokerOAuthError(failure)

    def access_token(self):
        def refresh(data):
            tokens = data.get("tokens") or {}
            if not tokens.get("access_token"):
                raise BrokerAuthorizationRequired("Connect Robinhood in the private Trading page first")
            if data.get("expires_at", 0) <= time.time() + 90:
                if not tokens.get("refresh_token"):
                    raise BrokerAuthorizationRequired("Robinhood connection expired. Connect again.")
                r = httpx.post(TOKEN, data=dict(grant_type="refresh_token", refresh_token=tokens["refresh_token"],
                    client_id=data["client"]["client_id"], resource=SERVER), timeout=20)
                r.raise_for_status()
                updated = r.json()
                if not updated.get("access_token"):
                    raise ValueError("Robinhood token refresh failed")
                data["tokens"] = {**tokens, **updated}
                data["expires_at"] = time.time() + float(updated.get("expires_in", 300))
            return data["tokens"]["access_token"]
        return self.mutate(refresh)


class ReadOnlyBroker:
    def __init__(self, session):
        self.session = session

    async def call(self, name, **arguments):
        if name not in READ_TOOLS:
            raise ValueError("Hosted monitor permits only read-only brokerage tools")
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise ValueError("Robinhood could not complete a read-only data request")
        payload = result.structuredContent
        if payload is None:
            payload = next((json.loads(c.text) for c in result.content if c.type == "text"), None)
        if not isinstance(payload, dict):
            raise ValueError("Robinhood returned an unexpected response")
        return payload.get("data", payload)

    async def pages(self, name, field, **arguments):
        collected, cursor, seen = [], None, set()
        for _ in range(30):
            page = await self.call(name, **arguments, **({"cursor": cursor} if cursor else {}))
            collected.extend(page.get(field) or [])
            cursor = page.get("next") or page.get("next_cursor")
            if not cursor:
                return {field: collected, "next": None}
            if not isinstance(cursor, str) or cursor in seen:
                raise ValueError("Robinhood pagination did not advance")
            seen.add(cursor)
        raise ValueError("Robinhood pagination limit reached; snapshot not saved")


@asynccontextmanager
async def connected_broker(store):
    token = await asyncio.to_thread(BrokerVault(store).access_token)
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=60) as client:
        async with streamable_http_client(SERVER, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield ReadOnlyBroker(session)

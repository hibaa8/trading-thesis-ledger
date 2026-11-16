"""Private dashboard records and a bridge from the connected Robinhood MCP."""

import asyncio
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import now


class TradingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    kind: str = Field(pattern=r"^(broker_snapshot|trading_cycle|trade_event|trading_request)$")
    created: datetime
    payload: dict

    @field_validator("created")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("A timezone is required")
        return value


def trading_view(store):
    records = store.trading_records()
    snapshots = sorted((r for r in records if r["kind"] == "broker_snapshot"),
                       key=lambda r: r["created"], reverse=True)
    cycles = [r for r in records if r["kind"] == "trading_cycle"]
    events = [r for r in records if r["kind"] == "trade_event"]
    funding = funding_status(snapshots[0]["payload"] if snapshots else None, events)
    requests = [r for r in records if r["kind"] == "trading_request"]
    return dict(funding=funding, requests=requests[:20], snapshot=snapshots[0] if snapshots else None,
                snapshots=snapshots[:100], cycles=cycles[:30], events=events[:100],
                funding_limit_usd="20.00", max_trade_usd="25.00", max_daily_usd="100.00")


def funding_status(snapshot, events):
    """Count filled and outstanding buy notional once, using broker approval/order IDs."""
    limit = Decimal("20.00")
    spent = Decimal(0)
    reserved = Decimal(0)
    reconciled = set()
    if snapshot:
        for order in snapshot.get("orders", []):
            reconciled.update(filter(None, [order.get("id"), order.get("ref_id")]))
            if order.get("side") != "buy":
                continue
            filled = decimal_value(order.get("cumulative_quantity") or 0)
            average = order.get("average_price")
            cost = filled * decimal_value(average) if average is not None else Decimal(0)
            spent += cost
            if order.get("state") not in {"filled", "cancelled", "rejected", "failed", "voided", "partially_filled_rest_cancelled"}:
                amount = (order.get("dollar_based_amount") or {}).get("amount")
                if amount is not None:
                    reserved += max(Decimal(0), decimal_value(amount) - cost)
    for event in events:
        item = event["payload"]
        if item.get("side") == "buy" and item.get("state") in {"review_requested", "awaiting_approval", "submission_unknown", "approved", "queued", "partially_filled"}:
            if not ({item.get("approval_id"), item.get("order_id")} & reconciled):
                reserved += decimal_value(item["amount_usd"])
    remaining = max(Decimal(0), limit - spent - reserved)
    known_approvals = {event["payload"].get("approval_id") for event in events}
    unknown_approvals = bool(snapshot and any(
        (approval.get("approval_id") or approval.get("id")) not in known_approvals
        or not (approval.get("approval_id") or approval.get("id"))
        for approval in snapshot.get("approvals", [])
    ))
    unknown_cost = bool(snapshot and any(
        decimal_value(order.get("cumulative_quantity") or 0) > 0 and order.get("average_price") is None
        for order in snapshot.get("orders", []) if order.get("side") == "buy"
    ))
    if not snapshot or not snapshot.get("orders_complete") or unknown_approvals or unknown_cost:
        remaining = Decimal(0)
    if snapshot:
        remaining = min(remaining, max(Decimal(0), decimal_value(snapshot.get("buying_power") or 0)))
    return dict(limit=str(limit), spent=str(spent), reserved=str(reserved), remaining=str(remaining),
                orders_complete=bool(snapshot and snapshot.get("orders_complete")),
                note="The $20 funding limit counts buys across this trial. Sales do not reset it.")


def merge_trading_record(record, records):
    """Preserve broker lifecycle evidence and atomically reserve the trial budget."""
    if record["kind"] != "trade_event":
        return record
    previous = next((r for r in records if r["kind"] == "trade_event" and r["id"] == record["id"]), None)
    item = record["payload"]
    if previous:
        old = previous["payload"]
        for key in ("symbol", "side", "amount_usd", "proposal_id"):
            if old.get(key) != item.get(key):
                raise ValueError("A proposal's stock, side and amount cannot change")
        for key in ("approval_id", "order_id"):
            if not item.get(key):
                item[key] = old.get(key, "")
        history = list(old.get("history", []))
        if old.get("state") != item.get("state"):
            history.append(dict(state=old.get("state"), recorded_at=previous["created"], detail=old.get("detail", "")))
        item["history"] = history
    if item.get("state") in {"review_requested", "awaiting_approval", "submission_unknown", "approved", "queued", "partially_filled"} and item.get("side") == "buy":
        snapshots = [r for r in records if r["kind"] == "broker_snapshot"]
        snapshot = max(snapshots, key=lambda r: r["created"])["payload"] if snapshots else None
        others = [r for r in records if r["kind"] == "trade_event" and r["id"] != record["id"]]
        funding = funding_status(snapshot, others)
        # Reconciled orders already account for this reservation.
        linked = snapshot and any(item.get("order_id") == o.get("id") or
            (item.get("approval_id") and item["approval_id"] == o.get("ref_id")) for o in snapshot.get("orders", []))
        if not linked and decimal_value(item["amount_usd"]) > decimal_value(funding["remaining"]):
            raise ValueError("This proposal would exceed the trial's remaining funding")
    return record


def decimal_value(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Broker amounts must be finite")
    return result


def broker_snapshot(portfolio, positions, quotes, orders, approvals, setting, realized):
    """Accept data fields from official broker tool responses. Never store account IDs."""
    account = setting["setting"]["account_number"]
    if realized.get("account_number") != account:
        raise ValueError("Portfolio and P&L must describe the same account")
    prices = {}
    disclosures = []
    for item in quotes.get("results") or []:
        quote = item.get("quote") or {}
        if quote.get("has_traded"):
            prices[quote["symbol"]] = quote
        if item.get("market_data_disclosure"):
            disclosures.append(item["market_data_disclosure"])
    holdings = []
    unrealized = Decimal(0)
    for position in positions.get("positions") or []:
        quantity = decimal_value(position["quantity"])
        if not quantity:
            continue
        quote = prices.get(position["symbol"])
        value = profit = None
        if quote:
            price = decimal_value(quote.get("last_non_reg_trade_price") or quote["last_trade_price"])
            value = quantity * price
            if position.get("average_buy_price") is not None:
                profit = value - quantity * decimal_value(position["average_buy_price"])
        if profit is None:
            unrealized = None
        elif unrealized is not None:
            unrealized += profit
        holdings.append(dict(symbol=position["symbol"], quantity=str(quantity),
                             available_to_sell=position["shares_available_for_sells"],
                             average_cost=position.get("average_buy_price"),
                             market_value=str(value) if value is not None else None,
                             unrealized_pnl=str(profit) if profit is not None else None))
    normalized_orders = []
    for order in orders.get("orders") or []:
        normalized_orders.append({key: order.get(key) for key in (
            "id", "symbol", "side", "type", "state", "quantity", "cumulative_quantity",
            "average_price", "dollar_based_amount", "created_at", "last_transaction_at",
            "agent_initiated", "ref_id", "fees",
        )})
    pending = []
    for approval in approvals.get("approvals") or []:
        pending.append({key: approval.get(key) for key in (
            "id", "approval_id", "state", "status", "created_at", "symbol", "side",
        )})
    buy_power = portfolio.get("buying_power") or {}
    payload = dict(
        account_last4=account[-4:], source="Robinhood Trading MCP", captured_at=now(),
        account_value=portfolio["total_value"], cash=portfolio["cash"],
        buying_power=buy_power.get("unleveraged_buying_power"),
        pending_deposits=portfolio.get("pending_deposits"),
        approvals_required=setting["setting"]["human_must_approve_trades"],
        realized_pnl=realized.get("total_returns"), realized_window=realized.get("window"),
        unrealized_pnl=str(unrealized) if unrealized is not None else None,
        positions=holdings, orders=normalized_orders, approvals=pending,
        positions_complete=not bool(positions.get("next")),
        orders_complete=not bool(orders.get("next")),
        approvals_complete=not bool(approvals.get("next")),
        market_data_disclosures=disclosures,
    )
    if not payload["positions_complete"]:
        payload["unrealized_pnl"] = None
    return TradingRecord(id=uuid.uuid4().hex, kind="broker_snapshot", created=now(), payload=payload)


async def dashboard_request(method, path, payload=None):
    token = os.getenv("LEDGER_TRADING_TOKEN")
    if not token:
        raise ValueError("Configure LEDGER_TRADING_TOKEN for the private dashboard")
    base = os.getenv("LEDGER_DASHBOARD_URL", "https://thesis-ledger.onrender.com").rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1:"):
        raise ValueError("Dashboard sync requires HTTPS")
    async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as client:
        for attempt in range(2):
            try:
                response = await client.request(method, base + path,
                    headers={"Authorization": "Bearer " + token}, json=payload)
            except httpx.HTTPError:
                if attempt:
                    raise ValueError("The private dashboard could not be reached") from None
                await asyncio.sleep(2)
                continue
            if response.status_code in {502, 503, 504} and not attempt:
                await asyncio.sleep(2)
                continue
            if response.status_code not in (200, 201):
                raise ValueError(f"Private dashboard request failed (HTTP {response.status_code})")
            return response.json()


async def publish_record(record):
    # A retry sends the same record ID, preserving idempotency across service restarts.
    await dashboard_request("POST", "/api/trading/records", record.model_dump(mode="json"))
    return dict(id=record.id, kind=record.kind, synced=True)


async def dashboard_state():
    return await dashboard_request("GET", "/api/trading")

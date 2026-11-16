"""One scheduled cloud review, using the official broker client and durable records."""

import asyncio
import json
import os
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from .agents import analyze
from .data import CAL
from .harness import Harness
from .market import MarketBrief
from .quotes import Quotes
from .store import now, open_store
from .trading import TradePlanner
from .trading_dashboard import TradingRecord, broker_snapshot, trading_view
from .trader_mcp import private_cycle

EASTERN = ZoneInfo("America/New_York")
TERMINAL = {"filled", "cancelled", "partially_filled_rest_cancelled", "rejected", "failed", "voided"}


def regular_session(instant):
    day = instant.astimezone(EASTERN).date().isoformat()
    if not CAL.is_session(day):
        return False
    return CAL.session_open(day).to_pydatetime() <= instant < CAL.session_close(day).to_pydatetime()


def within_monitoring_hours(instant):
    local = instant.astimezone(EASTERN)
    if not CAL.is_session(local.date().isoformat()):
        return False
    return (9, 30) <= (local.hour, local.minute) <= (16, 50)


class CloudMonitor:
    def __init__(self, broker, store):
        self.broker = broker
        self.store = store
        self.account = None
        self.started = now()

    def status(self, state, detail):
        self.store.save_trading_record(dict(id="render-monitor", kind="worker_status", created=now(),
            payload=dict(mode="render", state=state, detail=detail,
                         last_started_at=self.started, last_updated_at=now())))

    def event(self, proposal, state, detail, approval_id="", order_id="", broker_review=None):
        payload = dict(proposal_id=proposal["id"], symbol=proposal["ticker"], side=proposal["side"],
                       amount_usd=proposal["amount_usd"], state=state, detail=detail,
                       approval_id=approval_id, order_id=order_id)
        if broker_review is not None:
            payload["broker_review"] = broker_review
        self.store.save_trading_record(dict(id=proposal["id"], kind="trade_event", created=now(), payload=payload))

    async def sync(self):
        accounts = await self.broker.call("get_accounts")
        suffix = os.getenv("LEDGER_BROKER_ACCOUNT_LAST4")
        if not suffix:
            raise ValueError("Choose the funded MCP account for the cloud connection")
        eligible = [a for a in accounts.get("accounts") or []
                    if a.get("agentic_allowed") and a["account_number"].endswith(suffix)
                    and a.get("state") == "active"]
        if len(eligible) != 1:
            raise ValueError("Authorize the selected funded MCP account before running the monitor")
        self.account = eligible[0]
        account = self.account["account_number"]
        portfolio, positions, orders, approvals, setting, realized = await asyncio.gather(
            self.broker.call("get_portfolio", account_number=account),
            self.broker.pages("get_equity_positions", "positions", account_number=account),
            self.broker.pages("get_equity_orders", "orders", account_number=account, created_at_gte="2026-11-16T00:00:00Z"),
            self.broker.pages("get_trade_approvals", "approvals", account_number=account),
            self.broker.call("get_trade_approval_setting", account_number=account),
            self.broker.call("get_realized_pnl", account_number=self.account["rhs_account_number"],
                             span="all", asset_classes=["equity"]),
        )
        symbols = [p["symbol"] for p in positions["positions"] if Decimal(p["quantity"]) != 0]
        quotes = {"results": []}
        for offset in range(0, len(symbols), 20):
            page = await self.broker.call("get_equity_quotes", symbols=symbols[offset:offset + 20])
            quotes["results"].extend(page.get("results") or [])
        # P&L echoes the numeric RHS account ID; the other tools use the brokerage ID.
        if realized.get("account_number") != self.account["rhs_account_number"]:
            raise ValueError("Robinhood P&L did not match the selected account")
        realized = {**realized, "account_number": account}
        record = broker_snapshot(portfolio, positions, quotes, orders, approvals, setting, realized)
        self.store.save_trading_record(record.model_dump(mode="json"))
        return record.payload

    async def reconcile(self, snapshot):
        dashboard = trading_view(self.store)
        orders = snapshot["orders"]
        for record in dashboard["events"]:
            event = record["payload"]
            match = next((o for o in orders if
                (event.get("order_id") and event["order_id"] == o["id"]) or
                (event.get("approval_id") and event["approval_id"] == o.get("ref_id"))), None)
            updated = dict(event)
            if match:
                updated.update(state=match["state"], order_id=match["id"],
                               detail="Order status reconciled from Robinhood.")
            elif event.get("approval_id") and event.get("state") not in TERMINAL:
                data = await self.broker.call("get_trade_approvals", account_number=self.account["account_number"],
                                             approval_ids=[event["approval_id"]])
                approvals = data.get("approvals") or []
                if approvals:
                    observed = approvals[0].get("state") or approvals[0].get("status")
                    state = {"pending": "awaiting_approval", "approved": "approved", "declined": "declined",
                             "expired": "expired"}.get(str(observed).lower())
                    if state:
                        updated.update(state=state, detail="Approval status reconciled from Robinhood.")
            if updated != event:
                self.store.save_trading_record(dict(id=record["id"], kind="trade_event", created=now(), payload=updated))

    def saved_proposal(self, proposal_id):
        for cycle in trading_view(self.store)["cycles"]:
            proposal = cycle["payload"].get("proposal")
            if proposal and proposal["id"] == proposal_id:
                return proposal
        return None

    async def request_approval(self, proposal):
        if not regular_session(datetime.now(timezone.utc)):
            self.status("waiting", "The market closed during research. Review will resume in the next regular session.")
            return
        planner = TradePlanner(self.store)
        verified = planner.prepare(proposal["run_id"], float(proposal["amount_usd"]))
        if any(verified[key] != proposal[key] for key in ("id", "ticker", "side", "amount_usd")):
            raise ValueError("Saved proposal and reviewed trade do not match")
        account = self.account["account_number"]
        symbol = proposal["ticker"]
        tradability, portfolio, positions = await asyncio.gather(
            self.broker.call("get_equity_tradability", account_number=account, symbols=[symbol]),
            self.broker.call("get_portfolio", account_number=account),
            self.broker.pages("get_equity_positions", "positions", account_number=account),
        )
        instrument = next((r for r in tradability.get("results") or [] if r["symbol"] == symbol), None)
        if not instrument or not instrument.get("tradeable") or instrument.get("state") != "active":
            self.event(proposal, "blocked", "Robinhood reports the stock is not currently tradable.")
            return
        eligibility = next((r["account_type_tradability"] for r in instrument.get("account_type_tradabilities") or []
                            if r["account_type"] == self.account["brokerage_account_type"]), None)
        allowed = eligibility == "tradable" or (eligibility == "position_closing_only" and proposal["side"] == "sell")
        if (eligibility is not None and not allowed) or instrument.get("fractional_tradability") != "tradable" or                 "regular_hours" in (instrument.get("internal_halt_sessions") or []):
            self.event(proposal, "blocked", "Robinhood restricts the proposed fractional order in this account/session.")
            return
        amount = Decimal(proposal["amount_usd"])
        if proposal["side"] == "buy":
            cash = Decimal((portfolio.get("buying_power") or {}).get("unleveraged_buying_power") or "0")
            if amount > cash:
                self.event(proposal, "blocked", "The proposed amount exceeds current cash buying power.")
                return
        arguments = dict(account_number=account, symbol=symbol, side=proposal["side"],
                         dollar_amount=proposal["amount_usd"], type="market", time_in_force="gfd", market_hours="regular_hours")
        review = await self.broker.call("review_equity_order", **arguments)
        if any(review.get(key) != value for key, value in arguments.items() if key in {"symbol", "side", "type", "dollar_amount"}):
            self.event(proposal, "blocked", "The broker review did not match the proposed order.")
            return
        if review.get("customer_approval_required") is not True or review.get("order_checks") != {}:
            self.event(proposal, "blocked", "Broker review requires attention: " + json.dumps(review.get("order_checks")) +
                       " " + (review.get("market_data_disclosure") or ""), broker_review=review)
            return
        quote = review.get("quote_data") or {}
        price = Decimal(quote.get("last_trade_price") or "0")
        if not quote.get("has_traded") or price <= 0:
            self.event(proposal, "blocked", "The broker review did not provide a usable current quote.")
            return
        if proposal["side"] == "sell":
            holding = next((p for p in positions["positions"] if p["symbol"] == symbol), None)
            needed = (amount / price).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            if not holding or needed > Decimal(holding["shares_available_for_sells"]):
                self.event(proposal, "blocked", "The account does not have enough available shares for this sale.")
                return
        # Recheck immediately before the write. User authorization is required for every request.
        setting = await self.broker.call("get_trade_approval_setting", account_number=account)
        if setting.get("setting", {}).get("human_must_approve_trades") is not True:
            self.event(proposal, "blocked", "Turn Trade approvals on in Robinhood before requesting this order.")
            return
        if not regular_session(datetime.now(timezone.utc)):
            self.status("waiting", "Market closed before the approval request; retained the saved proposal.")
            return
        self.event(proposal, "submission_unknown", "Sending a Robinhood approval request.", broker_review=review)
        try:
            result = await self.broker.call("place_equity_order", **arguments, ref_id=proposal["id"])
        except Exception:
            self.status("attention", "An approval request needs reconciliation before another request can be sent.")
            return
        approval = result.get("approval") or result.get("trade_approval")
        approval_id = (approval.get("approval_id") or approval.get("id")) if isinstance(approval, dict) else result.get("approval_id")
        if not approval_id:
            self.status("attention", "The broker response needs manual reconciliation; no further orders will be requested.")
            return
        self.event(proposal, "awaiting_approval", "Review and approve or decline this proposal in Robinhood.",
                   approval_id=approval_id, broker_review=review)
        self.status("awaiting_approval", f"A {proposal['ticker']} proposal is waiting for approval in Robinhood.")

    async def candidates(self, snapshot, dashboard):
        queued = next((r for r in dashboard.get("requests", []) if r["payload"].get("status") == "queued"), None)
        holdings = [p["symbol"] for p in snapshot["positions"]]
        if queued:
            choices = queued["payload"]["tickers"]
        else:
            brief = await MarketBrief(Quotes()).get()
            universe = {item["ticker"]: item for item in [*brief["quotes"], *brief["activity"]]}
            evidence = [dict(id=symbol, kind="market", title=symbol, text=json.dumps(item))
                        for symbol, item in universe.items()]
            if evidence:
                scout = await analyze("candidate_scout", dict(evidence=evidence, headlines=brief["headlines"]), "live")
                choices = scout["evidence_ids"][:3]
            else:
                choices = []
            if not choices:
                choices = ["SPY", "AMZN", "GOOGL"]
        tickers = list(dict.fromkeys([*holdings, *choices]))[:5]
        if len(tickers) < 2:
            tickers.append("SPY" if "SPY" not in tickers else "QQQ")
        return tickers

    async def tick(self, instant=None):
        instant = instant or datetime.now(timezone.utc)
        if not within_monitoring_hours(instant):
            self.status("waiting", "Outside the scheduled NYSE monitoring window.")
            return
        self.status("running", "Syncing Robinhood account and reconciling previous decisions.")
        snapshot = await self.sync()
        await self.reconcile(snapshot)
        dashboard = trading_view(self.store)
        unresolved = [e["payload"] for e in dashboard["events"]
                      if e["payload"].get("state") in {"submission_unknown", "awaiting_approval", "approved", "queued", "partially_filled"}]
        if unresolved or snapshot["approvals"] or any(o["state"] not in TERMINAL for o in snapshot["orders"]):
            self.status("waiting", "Tracking existing approvals or orders before making another proposal.")
            return
        if not regular_session(instant):
            self.status("market_closed", "After-close reconciliation saved. The next regular session will review new suggestions.")
            return
        if not snapshot["approvals_required"]:
            self.status("attention", "Trade approvals must be enabled in Robinhood before unattended monitoring can request proposals.")
            return
        requested = [e for e in dashboard.get("events", []) if e["payload"].get("state") == "review_requested"]
        if requested:
            proposal = self.saved_proposal(requested[0]["id"])
            if proposal:
                await self.request_approval(proposal)
            else:
                self.status("attention", "A proposal reservation has no saved source report. Reconciliation is required.")
            return
        tickers = await self.candidates(snapshot, dashboard)
        facts = await self.broker.call("get_equity_fundamentals", symbols=tickers)
        self.status("running", "Specialist analysts, debate, manager and risk review are evaluating candidates.")
        result = await private_cycle(Harness(self.store), TradePlanner(self.store), tickers, 20,
                                     facts, record_store=self.store)
        if result.get("proposal"):
            await self.request_approval(result["proposal"])
        else:
            self.status("waiting", "Review complete. No candidate passed the directional and risk checks.")
        await self.sync()

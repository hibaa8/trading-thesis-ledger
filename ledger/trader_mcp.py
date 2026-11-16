"""Local-only trade planning tools; Robinhood's MCP handles order review and approval."""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from .agents import analyze
from .config import load_config
from .harness import Harness
from .models import ResearchRequest
from .store import open_store
from .trading import TradePlanner, _cents
from .trading_dashboard import TradingRecord, broker_snapshot, publish_record, dashboard_state
from .store import now
import uuid


def create_trader_mcp(store=None):
    store = store or open_store()
    harness = Harness(store)
    planner = TradePlanner(store)
    mcp = FastMCP("Thesis Ledger Trade Planner")

    @mcp.tool()
    async def research_and_prepare_trade(ticker: str, amount_usd: float = 25) -> dict:
        """Run today's live analyst workflow and reserve a capped STOCK/ETF trade proposal. This does not place an order. If the result abstains, fails risk review, or conflicts with the forecast, it returns no proposal. Before sending any order through Robinhood MCP, confirm its Trade approvals setting is ON and review the exact order. The account holder must manually approve in Robinhood."""
        if os.getenv("LEDGER_TRADING_ENABLED") != "1":
            raise ValueError("Trading proposals are disabled. Set LEDGER_TRADING_ENABLED=1 locally.")
        request = ResearchRequest(
            ticker=ticker.upper(),
            as_of=datetime.now(ZoneInfo("America/New_York")).date(),
            mode="live",
        )
        run = await harness.run(request)
        if run["status"] != "complete":
            raise ValueError("Research did not complete; no trade proposal generated")
        return planner.prepare(run["id"], amount_usd)

    @mcp.tool()
    async def compare_stocks_and_prepare_trade(tickers: list[str], amount_usd: float = 25) -> dict:
        """Research 2–5 stocks/ETFs, compare eligible reports with a selection manager, and reserve at most one buy proposal for human review. Returns all research outcomes, selection rationale and source reports. Does not submit a brokerage order. Robinhood Trade approvals must be ON before any order request."""
        return await compare_candidates(harness, planner, tickers, amount_usd)

    @mcp.tool()
    def prepare_trade_from_research(run_id: str, amount_usd: float = 25) -> dict:
        """Reserve a capped STOCK/ETF proposal from a completed live research run dated today. This never places an order. Robinhood's Trade approvals must be ON before any broker order request; the account holder approves in the Robinhood app."""
        return planner.prepare(run_id, amount_usd)

    @mcp.tool()
    async def sync_robinhood_dashboard(portfolio: dict, positions: dict, quotes: dict,
                                      orders: dict, approvals: dict, setting: dict,
                                      realized: dict) -> dict:
        """Publish current data fields from Robinhood MCP read tools to the owner's private dashboard. Pass all positions, all equity orders and approvals after following pagination. Pass quote data for held symbols and current Trade approvals. This never sends an order."""
        record = broker_snapshot(portfolio, positions, quotes, orders, approvals, setting, realized)
        return await publish_record(record)

    @mcp.tool()
    async def get_private_trading_dashboard() -> dict:
        """Read the private account snapshot, funding remaining, decisions, pending approvals and experience history before a trading review."""
        return await dashboard_state()

    @mcp.tool()
    async def run_private_trading_cycle(tickers: list[str], amount_usd: float = 20,
                                        broker_fundamentals: dict | None = None) -> dict:
        """Research candidates and held stocks using the current private Robinhood snapshot. Records all analyst/debate/manager/risk decisions on Thesis Ledger, with a $20 lifetime buy budget and $25 per proposal ceiling. Returns at most one proposal for Robinhood review. Does not request an order."""
        return await private_cycle(harness, planner, tickers, amount_usd, broker_fundamentals)

    @mcp.tool()
    async def record_robinhood_trade_event(proposal_id: str, symbol: str, side: str,
            amount_usd: str, state: str, approval_id: str = "", order_id: str = "",
            detail: str = "") -> dict:
        """Record an actual broker review, pending approval, approval decline, expiration or fill. Use a stable proposal ID as id/ref_id, reconcile the broker response before changing state, and never mark an approval filled. Record submission_unknown on a transport error and reuse the same ref_id when reconciling. Does not submit orders."""
        allowed = {"review_requested", "awaiting_approval", "submission_unknown", "declined", "expired",
                   "rejected", "approved", "queued", "partially_filled", "filled", "cancelled", "blocked",
                   "new", "confirmed", "unconfirmed", "failed", "voided", "pending_cancelled",
                   "partially_filled_rest_cancelled"}
        if state not in allowed or side not in {"buy", "sell"}:
            raise ValueError("Invalid broker event state or side")
        _cents(amount_usd)
        record = TradingRecord(id=proposal_id, kind="trade_event", created=now(), payload=dict(
            proposal_id=proposal_id, symbol=ResearchRequest(ticker=symbol).ticker,
            side=side, amount_usd=amount_usd, state=state,
            approval_id=approval_id, order_id=order_id, detail=detail[:2000]))
        return await publish_record(record)

    return mcp


async def compare_candidates(harness, planner, tickers, amount_usd=25, *, positions=None, buy_budget=None, experience=None, broker_fundamentals=None):
    if os.getenv("LEDGER_TRADING_ENABLED") != "1":
        raise ValueError("Trading proposals are disabled. Set LEDGER_TRADING_ENABLED=1 locally.")
    if _cents(amount_usd) > planner.max_trade_cents:
        raise ValueError("Amount exceeds the per-trade proposal limit")
    day = datetime.now(ZoneInfo("America/New_York")).date()
    symbols = list(dict.fromkeys(ticker.strip().upper() for ticker in tickers))
    if not 2 <= len(symbols) <= 5:
        raise ValueError("Supply 2 to 5 distinct stock or ETF tickers")
    # Validate the whole basket before starting paid research.
    requests = [ResearchRequest(ticker=ticker, as_of=day, mode="live") for ticker in symbols]
    outcomes = []
    eligible = []
    positions = positions or {}
    for request in requests:
        source = next((item for item in (broker_fundamentals or {}).get("results", [])
                       if item.get("symbol") == request.ticker), None)
        if source and source.get("market_date") == str(day):
            fields = {key: source.get(key) for key in (
                "symbol", "market_date", "pe_ratio", "pb_ratio", "market_cap", "shares_outstanding",
                "dividend_yield", "sector", "industry",
            )}
            evidence = dict(id="robinhood-fundamentals", kind="fundamentals", source="Robinhood",
                title=f"{request.ticker} valuation and company metrics · Robinhood",
                url=f"https://robinhood.com/stocks/{request.ticker}/", published=str(day),
                text=json.dumps(fields))
            run = await harness.run(request, source_evidence=[evidence])
        else:
            run = await harness.run(request)
        outcome = {"ticker": request.ticker, "run_id": run["id"], "status": run["status"],
                   "decision": run.get("decision"), "error": run.get("error"),
                   "reports": run.get("reports", {}), "metrics": run.get("metrics", {}),
                   "trace": run.get("trace", []), "evidence": run.get("snapshot", {}).get("evidence", []),
                   "forecast": {key: run.get("forecast", {}).get(key) for key in
                                ("expected_return", "model", "horizon", "disclaimer")}}
        outcomes.append(outcome)
        try:
            planner.validate_run(run)
            if run["decision"]["stance"] == "bearish" and request.ticker not in positions:
                raise ValueError("Bearish thesis, but no held shares available to sell")
            if run["decision"]["stance"] == "bullish" and buy_budget is not None and buy_budget < 1:
                raise ValueError("The trial's available buy budget is exhausted or reserved")
        except ValueError as exc:
            outcome["exclusion_reason"] = str(exc)
            continue
        eligible.append(run)
    if not eligible:
        return {"candidates": outcomes, "proposal": None,
                "reason": "No candidate passed the directional and risk checks."}
    evidence = [dict(id=run["id"], kind="research", title=run["request"]["ticker"],
                     text=run["decision"]["summary"], reports=run["reports"],
                     metrics=run.get("metrics", {}), warnings=run["snapshot"]["warnings"])
                for run in eligible]
    selection = await analyze("selection_manager", {"as_of": str(day), "evidence": evidence,
        "held_positions": positions, "available_buy_budget_usd": buy_budget, "experience": experience}, "live")
    selected = selection["evidence_ids"]
    proposal = None
    if selection["stance"] in {"bullish", "bearish"} and len(selected) == 1:
        chosen = next(run for run in eligible if run["id"] == selected[0])
        if chosen["decision"]["stance"] != selection["stance"]:
            raise ValueError("Selection manager disagrees with the chosen research decision")
        amount = amount_usd
        if selection["stance"] == "bullish" and buy_budget is not None:
            amount = min(amount, buy_budget)
        if selection["stance"] == "bearish":
            holding = positions[chosen["request"]["ticker"]]
            if holding.get("market_value") is None:
                raise ValueError("A current held position value is required before proposing a sale")
            available_fraction = float(holding["available_to_sell"]) / float(holding["quantity"])
            amount = min(amount, float(holding["market_value"]) * available_fraction)
        # Round down so sizing cannot exceed available cash or shares.
        amount = int(amount * 100) / 100
        proposal = planner.prepare(selected[0], amount)
    return {"candidates": outcomes, "selection": selection, "proposal": proposal}


async def private_cycle(harness, planner, tickers, amount_usd=20, broker_fundamentals=None, record_store=None):
    dashboard = await dashboard_state(record_store)
    snapshot = dashboard.get("snapshot")
    if not snapshot:
        raise ValueError("Sync Robinhood before starting a trading cycle")
    captured = datetime.fromisoformat(snapshot["payload"]["captured_at"])
    if (datetime.now(captured.tzinfo) - captured).total_seconds() > 900:
        raise ValueError("Robinhood snapshot is older than 15 minutes; sync again")
    account = snapshot["payload"]
    if not all(account.get(key) for key in ("positions_complete", "orders_complete", "approvals_complete")):
        raise ValueError("Complete broker pagination before proposing any trade")
    positions = {p["symbol"]: p for p in account["positions"] if float(p["available_to_sell"]) > 0}
    symbols = list(dict.fromkeys([*positions, *tickers]))
    if not 2 <= len(symbols) <= 5:
        raise ValueError("Choose 2 to 5 symbols including all held stocks")
    cycle = TradingRecord(id=uuid.uuid4().hex, kind="trading_cycle", created=now(),
        payload=dict(status="researching", tickers=symbols, broker_snapshot_id=snapshot["id"]))
    await publish_record(cycle, record_store)
    try:
        experience = None
        prior = dashboard.get("cycles", [])[:5]
        if prior:
            observation = dict(id=snapshot["id"], kind="broker", title="Observed Robinhood outcomes",
                text=dict(realized_pnl=account["realized_pnl"], unrealized_pnl=account["unrealized_pnl"],
                          positions=account["positions"], orders=account["orders"],
                          broker_events=[event["payload"] for event in dashboard.get("events", [])],
                          prior_decisions=[dict(selection=item["payload"].get("selection"),
                              proposal=item["payload"].get("proposal"),
                              candidates=[dict(ticker=c["ticker"], decision=c.get("decision"),
                                               exclusion_reason=c.get("exclusion_reason"))
                                          for c in item["payload"].get("candidates", [])])
                              for item in prior]))
            experience = await analyze("reflection", {"evidence": [observation]}, "live")
        result = await compare_candidates(harness, planner, symbols, amount_usd,
            positions=positions, buy_budget=float(dashboard["funding"]["remaining"]), experience=experience,
            broker_fundamentals=broker_fundamentals)
        cycle.payload.update(result, status="complete", experience=experience, completed_at=now())
        # Reserve across checks while the proposal awaits broker review.
        if proposal := result.get("proposal"):
            event = TradingRecord(id=proposal["id"], kind="trade_event", created=now(), payload=dict(
                proposal_id=proposal["id"], symbol=proposal["ticker"], side=proposal["side"],
                amount_usd=proposal["amount_usd"], state="review_requested", detail="Awaiting Robinhood broker review"))
            await publish_record(event, record_store)
        await publish_record(cycle, record_store)
        for queued in dashboard.get("requests", []):
            if queued["payload"].get("status") == "queued" and set(queued["payload"]["tickers"]) <= set(symbols):
                queued["payload"].update(status="complete", cycle_id=cycle.id)
                await publish_record(TradingRecord.model_validate(queued), record_store)
        return dict(cycle_id=cycle.id, **result)
    except BaseException:
        cycle.payload.update(status="interrupted", error="Review interrupted. Inspect saved research and reconcile before retrying.")
        await publish_record(cycle, record_store)
        raise


def main():
    load_config()
    create_trader_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()

"""Local-only trade planning tools; Robinhood's MCP handles order review and approval."""

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

    return mcp


async def compare_candidates(harness, planner, tickers, amount_usd=25):
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
    for request in requests:
        run = await harness.run(request)
        outcome = {"ticker": request.ticker, "run_id": run["id"], "status": run["status"],
                   "decision": run.get("decision"), "error": run.get("error")}
        outcomes.append(outcome)
        try:
            planner.validate_run(run)
            if run["decision"]["stance"] != "bullish":
                raise ValueError("No bullish investment thesis for a new purchase")
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
    selection = await analyze("selection_manager", {"as_of": str(day), "evidence": evidence}, "live")
    selected = selection["evidence_ids"]
    proposal = None
    if selection["stance"] == "bullish" and len(selected) == 1:
        proposal = planner.prepare(selected[0], amount_usd)
    return {"candidates": outcomes, "selection": selection, "proposal": proposal}


def main():
    load_config()
    create_trader_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()

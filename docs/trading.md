# Approval-gated trade planning

Thesis Ledger can produce a small stock or ETF trade proposal from a fresh, completed live research run. It does **not** place brokerage orders or trade from the public website. The local trade planner runs as a separate MCP server alongside Robinhood's [official Trading MCP](https://robinhood.com/us/en/support/articles/onboarding-an-external-agent/). Robinhood receives an order request only after its own trade approvals setting has been verified as on; the account holder must then manually review and place the proposed order in the Robinhood app.

## Scope and limits

- Long stocks and ETFs only. No options, crypto, short selling, margin, or account transfers.
- Maximum proposed notional: **$25 per trade** and **$100 per New York calendar day**. Proposals reserve this budget even if later declined, so the limit fails conservatively. Reusing a run returns its existing proposal; changing the amount requires a new research run.
- The research run must be **live, completed, and dated today**. Demo runs, abstentions, stale-data warnings, and research/forecast disagreement cannot produce proposals.
- A bearish finding can only become a sell proposal. Before requesting any sell order, check the account holds enough shares. The planner never authorizes short sales.
- The local proposal ledger is stored in SQLite on the machine running the trader MCP. Do not run multiple trader MCP hosts against the same Robinhood account until a shared budget ledger is implemented.

## Connect

1. Open a dedicated Robinhood MCP account and authenticate the official Robinhood Trading MCP. Account opening and funding are completed by the account holder in Robinhood. Robinhood says the agent can trade only in that dedicated account.
2. In the Robinhood app, go to the **MCP account → Agent Settings → Safety Controls** and turn **Trade approvals** on. Robinhood says this setting is off by default for external-agent MCP accounts.
3. Install this project locally with `uv sync --extra dev` and keep a private `.env` with the research provider credentials. Set `LEDGER_TRADING_ENABLED=1` in that private `.env` to enable proposal generation. It does not enable order submission.
4. Connect this local tool in Codex with `codex mcp add thesis-ledger-trader --env LEDGER_TRADING_ENABLED=1 -- uv --directory /path/to/thesis-ledger run python -m ledger.trader_mcp`. Connect Robinhood with `codex mcp add robinhood-trading --url https://agent.robinhood.com/mcp/trading` and complete its OAuth flow. Restart Codex or open a new session after adding MCP servers so their tools become available.

## Review sequence

1. Ask `compare_stocks_and_prepare_trade` to research 2–5 stock or ETF tickers. Each candidate goes through the technical, fundamentals, news and sentiment analysts, bull/bear debate, research manager and risk review. A selection manager compares eligible bullish reports and picks at most one proposal, with a reason and citations to the saved research. If none qualifies, the tool returns the candidate outcomes and no proposal. Only the selected proposal reserves the daily budget. For one ticker, use `research_and_prepare_trade`. The response contains the run ID, decision, risk review, side, amount, and evidence IDs. Read the full research report before proceeding.
2. Ask Robinhood `get_trade_approval_setting`. **Stop if it is off or cannot be read.**
3. Check Robinhood tradability, current quote, buying power, and existing position for a sell. Confirm the asset is a stock or ETF.
4. Ask Robinhood `review_equity_order` with the exact proposed side and amount. Stop on any blocking warning or if the quote/order differs materially from the reviewed proposal.
5. Only then call `place_equity_order` to create Robinhood's pending approval request. The account holder reviews and manually places it in the Robinhood app. Do not treat a pending approval as a fill. Reconcile through Robinhood order history.

The [TradingAgents paper](https://arxiv.org/abs/2412.20138) inspired the analyst/debate/manager/risk sequence. Thesis Ledger adds a separate human approval boundary. Research and forecast outputs are not validated trading signals; paper performance does not establish expected returns for this implementation.


## Private Trading dashboard

The Trading tab displays broker snapshots, cash without borrowing, account value, realized and open-position profit/loss, the $20 trial budget, proposals, approvals, orders and each review's analyst/debate/manager/risk reports. Trading records live in the private `owner` workspace in Supabase. The shared research API and public MCP cannot read them. The dashboard uses a separate private key, `LEDGER_TRADING_TOKEN`, held in browser session storage only while unlocked. Its hash can be stored as the owner `trading_access` record, so Render needs no plaintext trading key.

Robinhood can be connected through the official MCP in the local Codex agent. A separate hosted read-only connection is available through **Connect Robinhood** in Trading; see [hosted account observations](hosted-account-monitor.md) for OAuth, scheduling and credential storage. A recurring local Codex check reads the broker tools and uses `sync_robinhood_dashboard` to publish normalized account observations. The web page refreshes saved observations and shows the actual last sync time. The Codex app and this computer must remain available for local scheduled checks. Refreshing the web page does not itself contact Robinhood.

`run_private_trading_cycle` requires a complete broker snapshot less than 15 minutes old. It researches 2–5 symbols including held stocks, compares eligible buy and sell theses, and saves the full reasoning to the private dashboard. Prior outcomes are reviewed by a reflection agent and supplied to subsequent selection decisions. Reflections remain dated hypotheses for review. This is experience retrieval, with no claim of improved future returns.

The initial campaign permits at most $20 of gross purchases. Pending approvals and outstanding buy orders reserve that budget. Filled sales do not reset the purchase limit. The existing $25 per-proposal and $100 daily planning limits also apply. Buy reservations are serialized in the hosted database to prevent duplicate proposals from overspending the trial. The broker connection checks current cash, holdings, tradability, Trade approvals, and order-review alerts again before requesting the user's approval. Dollar-based market orders are restricted to regular market hours.

Broker snapshots count all equity orders since the trial began, including orders initiated by other agents or the account holder. A trade is labeled Thesis Ledger only when its broker order or approval ID matches the recorded proposal event. Account P&L is shown separately from this attribution. Deposits and withdrawals are never treated as trading profits. A pending approval is displayed separately from an actual fill.

See [the recurring check runbook](trading-agent-runbook.md) for the broker reconciliation and decision sequence.


### On-demand research reviews

The Trading page's **Request agent review** button sends a private `POST /api/trading/reviews` request for 2–5 symbols. A research worker in the existing web service wakes immediately instead of waiting for the hourly monitor. It checks waiting work every five seconds and runs one basket at a time. The four analysts, bull/bear debate, manager and risk reviewer run for each symbol; saved findings appear progressively under Agent decisions. This path imports neither the trade planner nor the broker and creates no trade proposals or orders.

Requests wait while another review, pending brokerage approval or open order is recorded. The × control removes a waiting request; a running review cannot be removed. Repeated submissions of the same pending basket reuse the request. Requests and results use the private Supabase owner workspace, separate from public research. Failed or interrupted reviews retain saved findings and can be resubmitted.

The worker shares the web service's lifecycle: a free Render service must be awake to process work, and a hard crash can interrupt a running review. Orphaned research is marked interrupted after 30 minutes so it cannot block the queue indefinitely; it is not automatically rerun. This feature does not activate the separate scheduled trading monitor or provide a continuously running brokerage connection.

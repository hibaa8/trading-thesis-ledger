# Hosted account observations

The Render account monitor syncs the funded MCP account's balances, holdings, orders, pending approvals and realized/open-position P&L. It saves market quotes and headlines and can process explicitly requested research baskets. It does not select, size, review, submit or cancel trades. The hosted broker client rejects every tool outside a fixed read-only allowlist. The local trade-planning MCP remains separate.

## Connection

The web Blueprint creates `LEDGER_BROKER_ENCRYPTION_KEY` once. Keep that Render secret: losing it makes stored credentials unreadable. The cron Blueprint references the same key and `LEDGER_DATABASE_URL` from the existing web service. Tokens, registration metadata and temporary PKCE state are encrypted together in the private Supabase `owner / broker_auth / robinhood` record, excluded from dashboard/public research queries. The hosted-records migration extends the existing kind constraint; the existing owner-only constraint continues to protect these records. No public table is created.

Unlock Trading, click **Connect Robinhood**, and complete Robinhood's own login and consent screen. This is a new hosted authorization, separate from Codex's local connector. The fixed callback is `https://thesis-ledger.onrender.com/broker/callback`. Authorization uses PKCE S256, ten-minute server state and a matching secure browser cookie. The official provider exposes its `internal` scope; the app further restricts use through its read-only tool allowlist. Token refreshes are serialized in Postgres, and tokens are never returned to the browser. Callback authorization codes are redacted from access logs.

## Schedule and deployment

Deploy `render-trading.yaml` as a separate Blueprint in the same workspace as the existing `thesis-ledger` web service. The command is `python -m ledger.worker`; `LEDGER_WORKER_ENABLED=1` enables account observations, and `LEDGER_TRADING_ENABLED` is not set. The UTC cron expression is `45 13-21 * * 1-5`. An NYSE-calendar guard limits actual work to 9:30 AM–4:50 PM New York time, covering daylight-saving changes and skipping holidays. Checks fall at :45 each market hour, including an after-close observation. Render charges at least $1/month per cron service plus runtime usage.

Run a manual cron check after connecting, verify a fresh broker snapshot and completed worker status in Trading, then verify a scheduled invocation. Do not disable the previous local monitor until the hosted read-only connection is verified. An authentication failure records an attention status and exits without orders. The monitor can be suspended in Render without changing stored reports.

This deployment does not enable unattended investment decisions, trade proposals or order submission. A successful account sync does not prove that the separate local trade-planning workflow is running.

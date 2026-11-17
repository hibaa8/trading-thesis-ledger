# React frontend

I use React for the browser workspace and Vite for its build. FastAPI continues to own the APIs, provider credentials, streaming chat, research jobs, Supabase persistence, MCP and brokerage integration. This migration preserves the current visual design and endpoint contracts.

## Development

Use Node 22.12 or newer and the Python environment described in the README:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
uv run thesis-ledger
```

For hot reload, keep FastAPI running on port 8000 and run `npm run dev --prefix frontend` in another terminal. Open the URL printed by Vite (normally port 5173, under `/static/`). The development proxy forwards `/api`, `/auth`, `/broker` and `/mcp` to FastAPI, including cookie-based sessions. OAuth providers still need a registered callback matching the origin used for authentication; use the production build on its registered origin when validating OAuth.

The production build writes ignored assets to `ledger/web/react/`. Build before starting FastAPI from a clean checkout or creating a Python wheel. The Dockerfile does this automatically in a separate Node stage. Its final image uses the existing Python service, port and health check. No provider keys belong in Vite variables or browser source.

## Components and behavior

| View | Preserved behavior |
|---|---|
| Research desk | Selected symbol, live price refresh, five-minute candles, watchlist, movers, company/market headlines and source links |
| Research chat | Saved session, streamed Markdown, tool progress, ticker quotes, new chat and a viewport-sized conversation with a visible composer |
| Forecast | Automatic forecast on entry, symbol/session controls, historical-return scenario chart and data timestamps |
| Deep Research | Live research requests, background polling, specialist cards, stance explanations, debate, evidence, trace, forecast checks and Markdown export |
| Thesis ledger | Stored memories, saved report reopening, permitted revisions and revision history |
| Research history | Completed report reopening and interrupted-run recovery |
| Trading | Separate private key, account/position/order views, manager decisions, review requests, queued-review cancellation and Robinhood connection entry point |
| Connect via MCP | Public and owner endpoint instructions, copyable public/local client configurations |
| How it works | Existing agent workflow diagram and data-source explanations |

Pages remain mounted while navigation hides inactive views so form state survives navigation. Polling pauses on inactive pages; in-flight research/chat can finish. Requests and timers are canceled on cleanup, and selection versions prevent stale reports from overwriting a newer choice. The private Trading view removes its component state on lock and never uses the general owner token as its private key.

Chart geometry and styling come from the original frontend. Generated chart SVG escapes its inputs. Chat Markdown disables raw HTML and only permits HTTP(S) links; source links use the same scheme restriction. Research exports are downloaded from FastAPI rather than reconstructed from visible cards.

## Validation

```sh
npm test --prefix frontend
npm run build --prefix frontend
PYTHON_DOTENV_DISABLED=1 uv run pytest -q
uv build --wheel
```

Frontend tests use isolated test fixtures and mocked API responses: they never fetch live data, spend model credits, or submit brokerage orders. They cover navigation and symbol changes, Markdown streaming and unsafe input, horizon selection, report tabs/export, memory revisions, interrupted report recovery, MCP copy controls, private access isolation, queued review cancellation and request cleanup. Backend tests exercise the built asset routes alongside the existing API/MCP contracts.

Visual verification compares the original frontend and React build with identical local test responses. Test fixtures are excluded from the production import graph. Live market sources, databases and authentication configuration are unchanged by this migration.

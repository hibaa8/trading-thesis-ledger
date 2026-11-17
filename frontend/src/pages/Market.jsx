import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { usePolling } from "../lib/hooks.js";
import { fmt, validTicker } from "../lib/format.js";
import { candleSvg } from "../lib/charts.js";
import {
  Chart,
  HeadlineList,
  QuoteCard,
  SourceLink,
} from "../components/Common.jsx";
const marketDelay = (brief) => Math.max(1, brief?.refresh_seconds || 60) * 1000;
function WatchRow({ quote: q, ticker, onSelect }) {
  return (
    <button
      type="button"
      className="watch-row"
      data-symbol={q.ticker}
      aria-pressed={q.ticker === ticker}
      title={[q.source, q.as_of].filter(Boolean).join(" · ")}
      onClick={() => onSelect(q.ticker)}
    >
      <strong>{q.ticker}</strong>
      <span>{q.price == null ? "—" : "$" + fmt(q.price)}</span>
      <span
        className={
          q.change_percent > 0
            ? "market-up"
            : q.change_percent < 0
              ? "market-down"
              : ""
        }
      >
        {q.change_percent == null
          ? "—"
          : (q.change_percent > 0 ? "+" : "") + fmt(q.change_percent) + "%"}
      </span>
    </button>
  );
}
export default function Market({
  active,
  ready,
  ticker,
  onSelect,
  onDeep,
  report,
}) {
  const [draft, setDraft] = useState(ticker),
    [validation, setValidation] = useState(""),
    [company, setCompany] = useState(true);
  const chartRef = useRef();
  useEffect(() => {
    setDraft(ticker);
    setValidation("");
  }, [ticker]);
  const marketLoad = useCallback((signal) => api("/market", { signal }), []);
  const candleLoad = useCallback(
    (signal) => api("/intraday/" + encodeURIComponent(ticker), { signal }),
    [ticker],
  );
  const newsLoad = useCallback(
    (signal) =>
      api("/news/" + encodeURIComponent(ticker), { signal }).then((items) => ({
        ticker,
        items,
      })),
    [ticker],
  );
  const market = usePolling(marketLoad, active && ready, marketDelay);
  const candles = usePolling(candleLoad, active && ready, 60000);
  const news = usePolling(newsLoad, active && ready, 900000);
  const brief = market.data,
    measured = (brief?.quotes || []).filter((q) => q.change_percent != null);
  const rising = measured.filter((q) => q.change_percent > 0).length,
    falling = measured.filter((q) => q.change_percent < 0).length;
  const articles =
    news.data?.ticker === ticker ? news.data.items.slice(0, 5) : [];
  const posts =
    report?.request.ticker === ticker
      ? (report.snapshot?.evidence || [])
          .filter((e) => e.kind === "sentiment" && e.id.startsWith("x-post-"))
          .slice(0, 2)
      : [];
  const headlines = [...articles, ...posts].sort(
    (a, b) => (Date.parse(b.published) || 0) - (Date.parse(a.published) || 0),
  );
  const session = candles.data?.ticker === ticker ? candles.data : null;
  function select(event) {
    event.preventDefault();
    const value = draft.trim().toUpperCase();
    if (!validTicker(value)) setValidation("Enter a valid U.S. ticker.");
    else {
      setValidation("");
      onSelect(value);
    }
  }
  return (
    <main id="research" className={"page" + (active ? " active" : "")}>
      <div className="title-row">
        <div>
          <div className="eyebrow">U.S. EQUITIES</div>
          <h1>Market research desk</h1>
          <p className="subtitle">
            Follow the session, read company news, and research any U.S. stock.
          </p>
        </div>
        <button
          id="desk-deep"
          className="primary"
          type="button"
          onClick={onDeep}
        >
          Open Deep Research ↗
        </button>
      </div>
      <section className="market-workspace" aria-label="Market desk">
        <div ref={chartRef} id="market-chart" className="panel intraday-panel">
          <div className="instrument-head">
            <div>
              <span className="eyebrow">SELECTED SYMBOL</span>
              <strong id="desk-symbol">{ticker}</strong>
            </div>
            <form id="symbol-form" onSubmit={select}>
              <label htmlFor="symbol-search">Find a symbol</label>
              <div>
                <input
                  id="symbol-search"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  maxLength={10}
                  required
                />
                <button className="secondary">View</button>
              </div>
            </form>
          </div>
          <QuoteCard id="desk-quote" ticker={ticker} active={active && ready} />
          <div className="intraday-meta">
            <strong>5-minute candles</strong>
            <span id="intraday-status" role="status">
              {validation ||
                candles.error?.message ||
                (session
                  ? `${session.session} · Regular session ET · Alpaca ${session.feed}`
                  : `Loading ${ticker} session…`)}
            </span>
          </div>
          <Chart id="intraday-chart" html={session ? candleSvg(session) : ""} />
        </div>
        <section className="panel watchlist" aria-labelledby="watchlist-title">
          <div className="watchlist-head">
            <h2 id="watchlist-title">Watchlist</h2>
            <p id="market-summary" role="status">
              {measured.length
                ? `${rising} up · ${falling} down · ${measured.length - rising - falling} flat on this watchlist`
                : brief
                  ? brief.quotes.length
                    ? "Latest available prices"
                    : "Watchlist prices unavailable."
                  : "Loading market prices…"}
            </p>
          </div>
          <div className="watchlist-labels">
            <span>Symbol</span>
            <span>Last</span>
            <span>Move</span>
          </div>
          <div
            id="market-quotes"
            className="market-quotes"
            role="region"
            aria-label="Watchlist prices"
            tabIndex={0}
          >
            {brief?.quotes.map((q) => (
              <WatchRow
                key={q.ticker}
                quote={q}
                ticker={ticker}
                onSelect={onSelect}
              />
            ))}
          </div>
          <p id="market-warning" className="subtitle">
            {market.error?.message || brief?.warnings?.join(" ")}
          </p>
        </section>
      </section>
      <section
        id="activity-section"
        className="panel market-activity-panel"
        hidden={!brief?.activity?.length}
        aria-labelledby="activity-title"
      >
        <div className="watchlist-head">
          <h2 id="activity-title">Movers &amp; headlines</h2>
          <p>
            Latest Alpaca screener session and company news from the past 24
            hours.
          </p>
        </div>
        <div id="market-activity" className="activity-grid">
          {brief?.activity?.map((stock) => (
            <div className="activity-card" key={stock.ticker}>
              <WatchRow
                quote={stock}
                ticker={ticker}
                onSelect={(value) => {
                  onSelect(value);
                  chartRef.current?.scrollIntoView({ block: "start" });
                }}
              />
              {stock.headline?.url?.startsWith("https://") && (
                <SourceLink
                  source={stock.headline}
                  className="activity-headline"
                />
              )}
            </div>
          ))}
        </div>
      </section>
      <section
        className="panel headline-board"
        aria-labelledby="headlines-title"
      >
        <div className="headline-board-header">
          <h2 id="headlines-title">Headlines</h2>
          <div
            className="headline-switch"
            role="group"
            aria-label="Headline coverage"
          >
            <button
              id="company-news-heading"
              type="button"
              aria-controls="company-news"
              aria-pressed={company}
              onClick={() => setCompany(true)}
            >
              {ticker}
            </button>
            <button
              id="market-news-button"
              type="button"
              aria-controls="market-news"
              aria-pressed={!company}
              onClick={() => setCompany(false)}
            >
              Market
            </button>
          </div>
        </div>
        <HeadlineList
          id="company-news"
          aria-label={ticker + " headlines"}
          hidden={!company}
          headlines={headlines}
          empty={
            news.error?.message ||
            (news.loading
              ? "Loading company headlines…"
              : "No company headlines available.")
          }
        />
        <HeadlineList
          id="market-news"
          aria-label="Market headlines"
          hidden={company}
          headlines={brief?.headlines}
          empty="No market headlines available."
        />
      </section>
    </main>
  );
}

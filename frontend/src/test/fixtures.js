import report from "./fixtures/report.json";
export const clone = (value) => structuredClone(value);
export const savedReport = (ticker = "NVDA") => ({
  ...clone(report),
  request: { ...report.request, ticker },
});
export const news = (ticker) => [
  {
    id: "news-1",
    source: "Test News",
    title: ticker + " company headline",
    url: "https://example.org/" + ticker,
    published: "2026-11-16T19:00:00Z",
    text: "Company evidence.",
  },
];
export const brief = {
  quotes: [
    {
      ticker: "NVDA",
      price: 100,
      change_percent: 1,
      source: "Test market data",
    },
    {
      ticker: "AAPL",
      price: 200,
      change_percent: -2,
      source: "Test market data",
    },
  ],
  headlines: news("Market"),
  warnings: [],
  refresh_seconds: 60,
  activity: [
    { ticker: "AMD", price: 150, change_percent: 5, headline: news("AMD")[0] },
  ],
};
export const candles = (ticker) => ({
  ticker,
  session: "2026-11-16",
  feed: "iex",
  open: "2026-11-16T14:30:00Z",
  close: "2026-11-16T21:00:00Z",
  bars: [
    { t: "2026-11-16T14:30:00Z", o: 100, h: 102, l: 99, c: 101 },
    { t: "2026-11-16T14:35:00Z", o: 101, h: 103, l: 100, c: 102 },
  ],
});
export const memories = [
  {
    id: "memory1",
    ticker: "NVDA",
    mode: "live",
    as_of: "2026-11-16",
    run_id: report.id,
    body: {
      thesis: "Saved test thesis",
      scope: "Dated source snapshot",
      invalidation: "New evidence changes the conclusion.",
    },
    revisions: [],
  },
];
export function tradingData() {
  const snapshot = {
    id: "snapshot1",
    created: "2026-11-16T20:00:00Z",
    payload: {
      account_last4: "2100",
      captured_at: "2026-11-16T20:00:00Z",
      approvals_required: true,
      account_value: "20",
      buying_power: "20",
      realized_pnl: "0",
      unrealized_pnl: "0",
      realized_window: "all",
      positions: [],
      orders: [],
      orders_complete: true,
      positions_complete: true,
      market_data_disclosures: [],
    },
  };
  return {
    snapshot,
    snapshots: [snapshot],
    funding: {
      limit: "20",
      remaining: "20",
      spent: "0",
      reserved: "0",
      note: "The $20 funding limit counts buys across this trial. Sales do not reset it.",
    },
    events: [],
    requests: [],
    cycles: [],
    worker: null,
    market_observation: null,
  };
}
export { report };

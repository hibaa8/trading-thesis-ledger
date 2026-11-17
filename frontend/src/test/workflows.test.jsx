import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import App from "../App.jsx";
import { Markdown, SourceLink } from "../components/Common.jsx";
import {
  brief,
  candles,
  clone,
  memories,
  news,
  report,
  savedReport,
  tradingData,
} from "./fixtures.js";
let fetchMock, privateData, memoryData, requests, latest;
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
beforeEach(() => {
  history.replaceState(null, "", "/");
  privateData = tradingData();
  memoryData = clone(memories);
  requests = [];
  latest = null;
  fetchMock = vi.fn(async (url, options = {}) => {
    const parsed = new URL(url, location.origin),
      path = parsed.pathname;
    requests.push({
      url: String(url),
      options,
      body: options.body ? JSON.parse(options.body) : null,
    });
    if (path === "/api/config")
      return json({
        live_ready: true,
        shared_ledger: false,
        google_sign_in: false,
        public_mcp_path: "/mcp/public/",
      });
    if (path === "/api/dashboard") return json(latest);
    if (path === "/api/market") return json(brief);
    if (path.startsWith("/api/quote/"))
      return json({
        ticker: path.split("/").at(-1),
        price: 100,
        source: "Test market data",
        freshness: "Latest trade",
        as_of: "2026-11-16T20:00:00Z",
        refresh_seconds: 0,
      });
    if (path.startsWith("/api/news/"))
      return json(news(path.split("/").at(-1)));
    if (path.startsWith("/api/intraday/"))
      return json(candles(path.split("/").at(-1)));
    if (path === "/api/forecast") {
      const body = JSON.parse(options.body);
      const result = savedReport(body.ticker);
      result.request.horizon = body.horizon;
      return json(result);
    }
    if (path === "/api/research")
      return json(savedReport(JSON.parse(options.body).ticker));
    if (path === "/api/runs")
      return json([{ ...savedReport(), status: "complete" }]);
    if (path.endsWith("/resume")) return json(savedReport());
    if (path.endsWith("/export"))
      return new Response("# Saved report\nSources: https://example.org");
    if (path.startsWith("/api/runs/")) return json(savedReport());
    if (path === "/api/memories") return json(memoryData);
    if (path === "/api/memories/review") {
      const body = JSON.parse(options.body);
      memoryData[0].revisions.push({
        created: "2026-11-16T20:00:00Z",
        feedback: body.feedback,
        scope: body.scope,
      });
      return json({ saved: true });
    }
    if (path === "/api/chat" && options.method === "POST")
      return new Response(
        '{"type":"delta","text":"**Grounded answer** [source](https://example.org/evidence)"}\n{"type":"done"}',
        { headers: { "Content-Type": "application/x-ndjson" } },
      );
    if (path.startsWith("/api/chat/")) return json([]);
    if (path.startsWith("/api/trading")) {
      if (options.headers?.Authorization !== "Bearer private-test")
        return json({ detail: "Private trading access required" }, 401);
      if (path === "/api/trading/reviews") {
        privateData.requests.push({
          id: "queue1",
          created: "2026-11-16T20:00:00Z",
          payload: {
            tickers: JSON.parse(options.body).tickers,
            status: "research_queued",
          },
        });
        return json({ id: "queue1" }, 202);
      }
      if (
        path === "/api/trading/requests/queue1" &&
        options.method === "DELETE"
      ) {
        privateData.requests = [];
        return json({ status: "cancelled" });
      }
      if (path === "/api/trading") return json(privateData);
    }
    throw Error("Unhandled test endpoint: " + url);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
function nav(name) {
  fireEvent.click(document.querySelector(`[data-page="${name}"]`));
  return document.getElementById(name);
}
async function ready() {
  await waitFor(() =>
    expect(requests.some((r) => r.url === "/api/market")).toBe(true),
  );
}
it("keeps all nine navigation views and updates a selected symbol across chart and headlines", async () => {
  render(<App />);
  await ready();
  const desk = document.getElementById("research");
  await within(desk).findByRole("button", { name: /AAPL/ });
  fireEvent.click(within(desk).getByRole("button", { name: /AAPL/ }));
  await within(desk).findByRole("link", { name: "AAPL company headline ↗" });
  expect(
    within(desk).getByRole("img", {
      name: "AAPL five-minute candlestick chart",
    }),
  ).toBeTruthy();
  expect(document.getElementById("desk-symbol").textContent).toBe("AAPL");
  for (const name of [
    "chat",
    "forecast",
    "deep",
    "memory",
    "runs",
    "connect",
    "method",
    "trading",
    "research",
  ]) {
    const page = nav(name);
    expect(page.classList.contains("active")).toBe(true);
    expect(document.getElementById("breadcrumb").textContent).toBeTruthy();
  }
});
it("streams real markdown and preserves the stored chat session", async () => {
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const chat = nav("chat");
  await waitFor(() =>
    expect(requests.some((r) => r.url.startsWith("/api/chat/"))).toBe(true),
  );
  await user.type(
    within(chat).getByRole("textbox", { name: "Message" }),
    "What supports this thesis?",
  );
  await user.click(within(chat).getByRole("button", { name: "Send" }));
  await within(chat).findByRole("link", { name: "source" });
  expect(chat.querySelector("strong").textContent).toBe("Grounded answer");
  const request = requests.find((r) => r.url === "/api/chat");
  expect(request.body.session).toMatch(/^[a-f0-9]{32}$/);
  expect(request.body.session).toBe(
    localStorage.getItem("ledger-chat-session"),
  );
  expect(request.body.ticker).toBe("NVDA");
});
it("keeps unsafe markup and unsafe source URLs inert", () => {
  const { container } = render(
    <>
      <Markdown
        text={
          "<script>alert(1)</script> **safe** ![image](https://example.org/a.png) [bad](javascript:alert(1))"
        }
      />
      <SourceLink
        source={{ title: "unsafe source", url: "javascript:alert(1)" }}
      />
    </>,
  );
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("img")).toBeNull();
  expect(container.querySelector("a")).toBeNull();
  expect(container.querySelector("strong").textContent).toBe("safe");
});
it("automatically forecasts on open and submits the selected session horizon", async () => {
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const forecast = nav("forecast");
  await within(forecast).findByRole("img", {
    name: "Observed closing prices and forecast scenario range",
  });
  const horizon = within(forecast).getByRole("spinbutton", {
    name: "Sessions",
  });
  await user.clear(horizon);
  await user.type(horizon, "10");
  await user.click(
    within(forecast).getByRole("button", { name: "Run forecast" }),
  );
  await waitFor(() =>
    expect(
      requests.filter((r) => r.url === "/api/forecast").at(-1).body.horizon,
    ).toBe(10),
  );
  expect(
    requests.filter((r) => r.url === "/api/forecast").at(-1).body,
  ).toMatchObject({ forecast: "bootstrap", mode: "live" });
});
it("runs deep research and retains evidence, debate, trace, forecast checks and report downloads", async () => {
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const deep = nav("deep");
  await user.type(
    within(deep).getByRole("textbox", { name: "Research question" }),
    "What changed?",
  );
  await user.selectOptions(deep.querySelector("#horizon"), "10");
  await user.click(
    within(deep).getByRole("button", { name: "Run research ↗" }),
  );
  await within(deep).findByText("RISK REVIEWED");
  expect(
    requests.find((r) => r.url === "/api/research?background=true").body,
  ).toMatchObject({
    mode: "live",
    horizon: 10,
    use_memory: true,
    question: "What changed?",
  });
  for (const title of [
    "Evidence room",
    "Harness trace",
    "Forecast checks",
    "Bull / bear debate",
  ]) {
    await user.click(within(deep).getByRole("tab", { name: title }));
    expect(
      within(deep)
        .getByRole("tab", { name: title })
        .getAttribute("aria-selected"),
    ).toBe("true");
  }
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
  await user.click(
    within(deep).getByRole("button", { name: "Download report (.md)" }),
  );
  await within(deep).findByText("Download started.");
  expect(click).toHaveBeenCalled();
  expect(requests.some((r) => r.url.endsWith("/export?format=md"))).toBe(true);
});
it("opens saved ledger reports and saves memory revisions", async () => {
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const ledger = nav("memory");
  await within(ledger).findByText("Saved test thesis");
  await user.click(
    within(ledger).getByRole("button", { name: "Review memory ↗" }),
  );
  const dialog = screen.getByRole("dialog");
  await user.type(
    within(dialog).getByRole("textbox", { name: "Feedback" }),
    "New evidence narrows the thesis.",
  );
  await user.selectOptions(
    within(dialog).getByRole("combobox", { name: "Revision" }),
    "retire",
  );
  await user.click(
    within(dialog).getByRole("button", { name: "Save revision" }),
  );
  await within(ledger).findByText(/New evidence narrows/);
  expect(
    requests.find((r) => r.url === "/api/memories/review").body.scope,
  ).toBe("retire");
  await user.click(
    within(ledger).getByRole("button", { name: "Open report ↗" }),
  );
  await waitFor(() =>
    expect(document.getElementById("deep").classList.contains("active")).toBe(
      true,
    ),
  );
  expect(document.getElementById("asset-name").textContent).toBe("NVDA");
});
it("resumes an interrupted run from history", async () => {
  const original = fetchMock.getMockImplementation();
  fetchMock.mockImplementation((url, options) =>
    String(url) === "/api/runs"
      ? Promise.resolve(json([{ ...savedReport(), status: "failed" }]))
      : String(url) === "/api/runs/" + report.id
        ? Promise.resolve(json({ ...savedReport(), status: "failed" }))
        : original(url, options),
  );
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const runs = nav("runs");
  await user.click(
    await within(runs).findByRole("button", { name: "Resume run ↗" }),
  );
  await waitFor(() =>
    expect(
      requests.some((r) => r.url.includes("/resume?background=true")),
    ).toBe(true),
  );
  await waitFor(() =>
    expect(document.getElementById("deep").classList.contains("active")).toBe(
      true,
    ),
  );
});
it("copies the usable public MCP configuration", async () => {
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const connect = nav("connect");
  await user.click(
    within(connect).getByRole("button", { name: "Copy Cursor configuration" }),
  );
  const copied = JSON.parse(await navigator.clipboard.readText());
  expect(copied.mcpServers["thesis-ledger-market"].url).toBe(
    location.origin + "/mcp/public/",
  );
});
it("unlocks trading with a separate key, queues and cancels reviews, then removes private data on lock", async () => {
  sessionStorage.setItem("ledger-token", "owner-test");
  const user = userEvent.setup();
  render(<App />);
  await ready();
  const trading = nav("trading");
  expect(requests.some((r) => r.url === "/api/trading")).toBe(false);
  await user.type(trading.querySelector("#trading-key"), "private-test");
  await user.click(
    within(trading).getByRole("button", { name: "Open trading view" }),
  );
  await within(trading).findByText("No open stock or ETF positions.");
  expect(
    requests.find((r) => r.url === "/api/trading").options.headers
      .Authorization,
  ).toBe("Bearer private-test");
  await user.click(
    within(trading).getByRole("button", { name: "Request agent review" }),
  );
  const remove = await within(trading).findByRole("button", {
    name: "Remove queued review for SPY, AMZN, GOOGL",
  });
  await user.click(remove);
  await waitFor(() =>
    expect(
      within(trading).queryByRole("button", {
        name: "Remove queued review for SPY, AMZN, GOOGL",
      }),
    ).toBeNull(),
  );
  expect(
    requests.some(
      (r) =>
        r.options.method === "DELETE" && r.url.endsWith("/requests/queue1"),
    ),
  ).toBe(true);
  await user.click(within(trading).getByRole("button", { name: "Lock view" }));
  expect(sessionStorage.getItem("ledger-trading-key")).toBeNull();
  expect(trading.querySelector("#trading-stats")).toBeNull();
  expect(
    within(trading).getByRole("button", { name: "Open trading view" }),
  ).toBeTruthy();
});
it("clears an expired private key without opening the owner unlock dialog", async () => {
  sessionStorage.setItem("ledger-trading-key", "expired");
  render(<App />);
  await ready();
  const trading = nav("trading");
  await within(trading).findByRole("button", { name: "Open trading view" });
  expect(sessionStorage.getItem("ledger-trading-key")).toBeNull();
  expect(document.getElementById("auth-dialog").open).toBe(false);
});

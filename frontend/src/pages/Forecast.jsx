import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { scenarioSvg } from "../lib/charts.js";
import { Chart } from "../components/Common.jsx";
export default function Forecast({ active, ready, ticker }) {
  const [symbol, setSymbol] = useState(ticker),
    [horizon, setHorizon] = useState(5),
    [result, setResult] = useState(null),
    [status, setStatus] = useState(""),
    [busy, setBusy] = useState(false);
  const busyRef = useRef(false),
    abort = useRef(),
    generation = useRef(0);
  useEffect(() => {
    setSymbol(ticker);
    setResult(null);
    generation.current++;
    abort.current?.abort();
    busyRef.current = false;
    setBusy(false);
  }, [ticker]);
  useEffect(() => () => abort.current?.abort(), []);
  async function run(override) {
    if (busyRef.current) return;
    const version = ++generation.current;
    busyRef.current = true;
    setBusy(true);
    setResult(null);
    setStatus("Fetching daily bars and sampling price paths…");
    abort.current = new AbortController();
    try {
      const response = await api("/forecast", {
        method: "POST",
        body: JSON.stringify({
          ticker: (override || symbol).trim().toUpperCase(),
          horizon: Number(horizon),
          mode: "live",
          forecast: "bootstrap",
        }),
        signal: abort.current.signal,
      });
      if (version !== generation.current) return;
      setResult(response);
      setStatus(
        `${response.request.ticker} · ${response.forecast.label} · ${response.snapshot.provider} · Last bar ${response.snapshot.bars.at(-1).date}`,
      );
    } catch (error) {
      if (version === generation.current && error.name !== "AbortError")
        setStatus(error.message);
    } finally {
      if (version === generation.current) {
        busyRef.current = false;
        setBusy(false);
      }
    }
  }
  useEffect(() => {
    if (active && ready && !result && !busyRef.current) run(ticker);
  }, [active, ready, ticker]);
  return (
    <main
      id="forecast"
      hidden={!active}
      className={"page" + (active ? " active" : "")}
    >
      <div className="eyebrow">MARKET FORECAST</div>
      <h1>Price scenarios</h1>
      <p className="subtitle">
        Explore sampled paths for the next trading sessions from completed daily
        bars.
      </p>
      <section className="panel chat-panel">
        <form
          id="forecast-form"
          className="chat-toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            run();
          }}
        >
          <label htmlFor="forecast-ticker">Ticker</label>
          <input
            id="forecast-ticker"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            maxLength={10}
            required
          />
          <label htmlFor="forecast-horizon">Sessions</label>
          <input
            id="forecast-horizon"
            type="number"
            min={1}
            max={20}
            value={horizon}
            onChange={(e) => setHorizon(e.target.value)}
            required
          />
          <button id="forecast-submit" type="submit" disabled={busy}>
            Run forecast
          </button>
        </form>
        <p id="forecast-status" role="status">
          {status}
        </p>
        <Chart
          id="forecast-chart"
          html={result ? scenarioSvg(result, 40, "forecast-chart") : ""}
        />
        <p id="forecast-caption">
          {result &&
            [
              result.forecast.disclaimer,
              ...(result.snapshot.warnings || []).filter(
                (w) => w.startsWith("STALE") || w.startsWith("Daily bars"),
              ),
            ].join(" ")}
        </p>
      </section>
    </main>
  );
}

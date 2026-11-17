import { useEffect, useRef, useState } from "react";
import { api, waitForResearch } from "../lib/api.js";
import { localDate, validTicker } from "../lib/format.js";
import ResearchReport, {
  ResearchEmpty,
} from "../components/ResearchReport.jsx";
export default function DeepResearch({
  active,
  config,
  ticker,
  onTicker,
  onSelect,
  report,
  onReport,
  status,
  onStatus,
  generation,
}) {
  const [asof, setAsof] = useState(localDate),
    [horizon, setHorizon] = useState("5"),
    [question, setQuestion] = useState(""),
    [memory, setMemory] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(false);
  const controller = useRef(),
    dirty = useRef(false),
    busyRef = useRef(false);
  useEffect(() => () => controller.current?.abort(), []);
  async function submit(event) {
    event.preventDefault();
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setError(false);
    const version = ++generation.current;
    onStatus(
      "Gathering evidence → independent analysts → bull / bear debate → risk review. Completed stages are saved.",
    );
    const request = {
      ticker: ticker.trim().toUpperCase(),
      as_of: asof,
      horizon: Number(horizon),
      mode: "live",
      forecast: "bootstrap",
      use_memory: memory,
      ...(question.trim() ? { question: question.trim() } : {}),
    };
    controller.current = new AbortController();
    try {
      const result = await waitForResearch(
        await api("/research?background=true", {
          method: "POST",
          body: JSON.stringify(request),
          signal: controller.current.signal,
        }),
        (message) => {
          if (version === generation.current) onStatus(message);
        },
        controller.current.signal,
      );
      if (version !== generation.current) return;
      if (result.status === "failed") {
        setError(true);
        onStatus(result.error + " Open Research history to resume.");
      } else {
        onReport(result);
        onStatus(result.snapshot.warnings.join(" "));
      }
    } catch (e) {
      if (version === generation.current && e.name !== "AbortError") {
        setError(true);
        onStatus(e.message);
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <main id="deep" className={"page" + (active ? " active" : "")}>
      <div className="eyebrow">MULTI-AGENT ANALYSIS</div>
      <h1>Deep Research</h1>
      <p className="subtitle">
        Send a question to four specialist analysts and review their debate,
        evidence, and conclusion.
      </p>
      <p
        id="research-public-note"
        className="info"
        hidden={!config?.shared_ledger}
      >
        Research questions and reports are public. Leave private details out of
        your question.
      </p>
      <h2 id="research-heading">Research · {ticker}</h2>
      <form id="research-form" className="research-form" onSubmit={submit}>
        <div className="form-top">
          <label>
            ASSET
            <input
              id="ticker"
              aria-label="Ticker symbol"
              value={ticker}
              onChange={(e) => {
                dirty.current = true;
                onTicker(e.target.value);
              }}
              onBlur={() => {
                if (dirty.current) {
                  dirty.current = false;
                  const value = ticker.trim().toUpperCase();
                  if (validTicker(value)) onSelect(value);
                }
              }}
              maxLength={10}
              pattern="[A-Za-z][A-Za-z0-9.\-]{0,9}"
              required
            />
          </label>
          <label>
            AS OF
            <input
              type="date"
              id="asof"
              value={asof}
              max={localDate()}
              onChange={(e) => setAsof(e.target.value)}
              required
            />
          </label>
          <label>
            HORIZON
            <select
              id="horizon"
              value={horizon}
              onChange={(e) => setHorizon(e.target.value)}
            >
              {[5, 10, 20].map((n) => (
                <option key={n} value={n}>
                  {n} sessions
                </option>
              ))}
            </select>
          </label>
          <button
            type="submit"
            id="run-button"
            className={"primary" + (busy ? " loading" : "")}
            disabled={busy}
          >
            {busy ? "Researching…" : "Run research ↗"}
          </button>
        </div>
        <div className="form-bottom">
          <label htmlFor="question">Research question</label>
          <input
            id="question"
            aria-label="Research question"
            placeholder="What supports or challenges the investment thesis?"
            maxLength={1200}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
          <label className="memory-toggle">
            <input
              id="use-memory"
              type="checkbox"
              checked={memory}
              onChange={(e) => setMemory(e.target.checked)}
            />{" "}
            Use thesis memory
          </label>
        </div>
      </form>
      <div
        id="status"
        role="status"
        aria-live="polite"
        className={"status" + (error ? " error" : "")}
      >
        {status}
      </div>
      {report ? <ResearchReport report={report} /> : <ResearchEmpty />}
    </main>
  );
}

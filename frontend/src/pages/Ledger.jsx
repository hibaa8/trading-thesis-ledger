import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api.js";
import { Dialog } from "../components/Common.jsx";
function OpenReport({ id, complete = true, onOpen }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  return (
    <button
      className="secondary"
      data-open-run={id}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        setError("");
        try {
          await onOpen(id);
        } catch (e) {
          setError(e.message);
        } finally {
          setBusy(false);
        }
      }}
    >
      {error ||
        (busy ? "Opening…" : complete ? "Open report ↗" : "Resume run ↗")}
    </button>
  );
}
export function History({ active, onOpen }) {
  const [runs, setRuns] = useState(null),
    [error, setError] = useState("");
  useEffect(() => {
    if (!active) return;
    const c = new AbortController();
    api("/runs", { signal: c.signal })
      .then((items) => {
        if (!c.signal.aborted) {
          setRuns(items.filter((r) => r.request.mode === "live"));
          setError("");
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      });
    return () => c.abort();
  }, [active]);
  return (
    <main id="runs" className={"page" + (active ? " active" : "")}>
      <div className="eyebrow">REPRODUCIBLE BY DESIGN</div>
      <h1>Research history.</h1>
      <p className="subtitle">
        Reopen the evidence, decisions, and execution trace behind each run.
      </p>
      <div id="run-list">
        {error ||
          (runs === null ? (
            "Loading research history…"
          ) : runs.length ? (
            runs.map((r) => (
              <div className="history-row panel" key={r.id}>
                <strong>{r.request.ticker}</strong>
                <span className="chip">{r.status}</span>
                <small>
                  {r.request.as_of} · {r.request.mode} · {r.request.horizon}{" "}
                  sessions
                </small>
                <OpenReport
                  id={r.id}
                  complete={r.status === "complete"}
                  onOpen={onOpen}
                />
              </div>
            ))
          ) : (
            <div className="empty">No runs yet. Start in Deep Research.</div>
          ))}
      </div>
    </main>
  );
}
export function Ledger({ active, config, onOpen, onDeep }) {
  const [memories, setMemories] = useState(null),
    [error, setError] = useState(""),
    [revision, setRevision] = useState(0),
    [selected, setSelected] = useState(null),
    [feedback, setFeedback] = useState(""),
    [scope, setScope] = useState("source_snapshot_only"),
    [saving, setSaving] = useState(false),
    [saveError, setSaveError] = useState("");
  useEffect(() => {
    if (!active) return;
    const c = new AbortController();
    api("/memories", { signal: c.signal })
      .then((items) => {
        if (!c.signal.aborted) {
          setMemories(items.filter((m) => m.mode === "live"));
          setError("");
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      });
    return () => c.abort();
  }, [active, revision]);
  const note = config?.shared_ledger
    ? "This ledger is public. Completed research and its source reports are visible to every visitor."
    : config?.signed_in
      ? "Your reports and revisions are saved to your account."
      : config?.public_visitor
        ? "Guest reports are temporary. Sign in to keep future research in your private ledger."
        : "";
  async function save(event) {
    event.preventDefault();
    if (saving) return;
    setSaving(true);
    setSaveError("");
    try {
      await api("/memories/review", {
        method: "POST",
        body: JSON.stringify({ memory_id: selected.id, feedback, scope }),
      });
      setSelected(null);
      setRevision((v) => v + 1);
    } catch (e) {
      setSaveError(e.message);
    } finally {
      setSaving(false);
    }
  }
  return (
    <>
      <main id="memory" className={"page" + (active ? " active" : "")}>
        <div className="eyebrow">MEMORY THAT CAN CHANGE ITS MIND</div>
        <h1>The thesis ledger.</h1>
        <p className="subtitle">
          Compact research memories. Original evidence preserved. Revisions made
          explicit.
        </p>
        <div className="info">
          Memories are hypotheses, not verified facts. Review narrows their
          scope or retires them; it does not establish trading performance.
        </div>
        <p id="ledger-access-note" className="subtitle">
          {note}
        </p>
        <div id="memory-list">
          {error ||
            (memories === null ? (
              "Loading thesis memories…"
            ) : memories.length ? (
              memories.map((m) => (
                <article className="panel memory-card" key={m.id}>
                  <div className="top">
                    <strong>{m.ticker}</strong>
                    <span className="chip">{m.mode}</span>
                    <span className="tiny">{m.as_of}</span>
                    {!config?.shared_ledger && (
                      <button
                        className="secondary"
                        data-review={m.id}
                        onClick={() => {
                          setSelected(m);
                          setFeedback("");
                          setScope("source_snapshot_only");
                          setSaveError("");
                        }}
                      >
                        Review memory ↗
                      </button>
                    )}
                  </div>
                  <p>{m.body.thesis}</p>
                  <p>
                    <strong>Scope:</strong> {m.body.scope}
                  </p>
                  <p>
                    <strong>Invalidation:</strong> {m.body.invalidation}
                  </p>
                  <OpenReport id={m.run_id} onOpen={onOpen} />
                  {(m.revisions || []).map((r, i) => (
                    <p className="revision" key={r.id || i}>
                      {r.created.slice(0, 10)} · {r.scope}
                      <br />
                      {r.feedback}
                    </p>
                  ))}
                </article>
              ))
            ) : (
              <div className="empty">
                <p>
                  Complete a research run to save its thesis, evidence, and
                  invalidation criteria here.
                </p>
                <button
                  id="memory-start-research"
                  className="secondary"
                  type="button"
                  onClick={onDeep}
                >
                  Open Deep Research ↗
                </button>
              </div>
            ))}
        </div>
      </main>
      <Dialog
        id="review-dialog"
        open={!!selected}
        onClose={() => {
          if (!saving) setSelected(null);
        }}
      >
        <form id="review-form" onSubmit={save}>
          <h2>Review this memory</h2>
          <p>
            Narrow its applicability or retire it. Original evidence stays
            intact.
          </p>
          <label>
            Feedback
            <textarea
              id="feedback"
              required
              minLength={10}
              maxLength={1500}
              rows={4}
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
            />
          </label>
          <label>
            Revision
            <select
              id="scope"
              value={scope}
              onChange={(e) => setScope(e.target.value)}
            >
              <option value="source_snapshot_only">
                Restrict to original source snapshot
              </option>
              <option value="retire">Retire from future retrieval</option>
            </select>
          </label>
          <p role="status">{saveError}</p>
          <div className="dialog-actions">
            <button
              type="button"
              id="close-review"
              className="secondary"
              disabled={saving}
              onClick={() => setSelected(null)}
            >
              Cancel
            </button>
            <button className="primary" disabled={saving}>
              Save revision
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

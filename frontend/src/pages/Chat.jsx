import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, apiResponse, readChatStream } from "../lib/api.js";
import { validTicker } from "../lib/format.js";
import { Markdown, QuoteCard } from "../components/Common.jsx";
function newSession() {
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), (n) =>
    n.toString(16).padStart(2, "0"),
  ).join("");
  localStorage.setItem("ledger-chat-session", id);
  return id;
}
export default function Chat({ active, ready, ticker, onTicker }) {
  const [session, setSession] = useState(() => {
    const saved = localStorage.getItem("ledger-chat-session") || "";
    return /^[a-f0-9]{32}$/.test(saved) ? saved : newSession();
  });
  const [draftTicker, setDraftTicker] = useState(ticker),
    [quoteTicker, setQuoteTicker] = useState(ticker),
    [quoteVersion, setQuoteVersion] = useState(0);
  const [messages, setMessages] = useState([]),
    [input, setInput] = useState(""),
    [status, setStatus] = useState(""),
    [busy, setBusy] = useState(false);
  const busyRef = useRef(false),
    historyVersion = useRef(0),
    controller = useRef(),
    log = useRef();
  useEffect(() => {
    setDraftTicker(ticker);
    setQuoteTicker(ticker);
  }, [ticker]);
  useEffect(() => () => controller.current?.abort(), []);
  useLayoutEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages]);
  useEffect(() => {
    if (!active || !ready || busyRef.current) return;
    const abort = new AbortController(),
      version = historyVersion.current;
    api("/chat/" + session, { signal: abort.signal })
      .then((items) => {
        if (
          !abort.signal.aborted &&
          !busyRef.current &&
          version === historyVersion.current
        )
          setMessages(items);
      })
      .catch((error) => {
        if (!abort.signal.aborted) setStatus(error.message);
      });
    return () => abort.abort();
  }, [active, ready, session]);
  function refreshPrice() {
    const value = draftTicker.trim().toUpperCase();
    if (!validTicker(value)) {
      setStatus("Enter a stock ticker, such as NVDA.");
      return;
    }
    setQuoteTicker(value);
    onTicker(value);
    setQuoteVersion((v) => v + 1);
  }
  async function send(event) {
    event.preventDefault();
    if (busyRef.current || !input.trim()) return;
    const symbol = draftTicker.trim().toUpperCase(),
      message = input.trim();
    if (!validTicker(symbol))
      return setStatus("Enter a stock ticker, such as NVDA.");
    busyRef.current = true;
    setBusy(true);
    historyVersion.current++;
    const answerId = crypto.randomUUID();
    let answer = "";
    let completed = false;
    setMessages((old) => [
      ...old,
      { role: "user", content: message, id: crypto.randomUUID() },
      { role: "assistant", content: "", id: answerId },
    ]);
    setInput("");
    setStatus("Thinking…");
    controller.current = new AbortController();
    try {
      const response = await apiResponse("/chat", {
        method: "POST",
        body: JSON.stringify({ session, ticker: symbol, message }),
        signal: controller.current.signal,
      });
      if (!response.ok) {
        let data;
        try {
          data = await response.json();
        } catch {
          throw Error("The service is reconnecting. Please retry shortly.");
        }
        const field = Array.isArray(data.detail)
          ? data.detail[0]?.loc?.at(-1)
          : null;
        throw Error(
          typeof data.detail === "string"
            ? data.detail
            : {
                session:
                  "This chat session is invalid. Select New chat and resend your message.",
                ticker: "Enter a stock ticker, such as NVDA.",
                message: "Enter a message of up to 4,000 characters.",
              }[field] || "Chat could not start. Try again.",
        );
      }
      for await (const item of readChatStream(response)) {
        if (item.type === "delta") {
          answer += item.text;
          const content = answer;
          setMessages((old) =>
            old.map((m) => (m.id === answerId ? { ...m, content } : m)),
          );
        }
        if (item.type === "status") setStatus(item.message);
        if (item.type === "report") setStatus("Report saved · " + item.id);
        if (item.type === "error") throw Error(item.message);
        if (item.type === "done") completed = true;
      }
      if (!completed) throw Error("The response was interrupted.");
      setStatus("");
    } catch (error) {
      if (!controller.current.signal.aborted) {
        setStatus(error.message);
        setInput((old) => old || message);
        if (!answer) setMessages((old) => old.filter((m) => m.id !== answerId));
      }
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  return (
    <main id="chat" className={"page" + (active ? " active" : "")}>
      <div className="eyebrow">MARKET RESEARCH</div>
      <h1>Research chat</h1>
      <p className="subtitle">
        Ask about a price, follow up on a report, or run the analyst team.
      </p>
      <section className="panel chat-panel">
        <div className="chat-toolbar">
          <label htmlFor="chat-ticker">Ticker</label>
          <input
            id="chat-ticker"
            aria-label="Chat ticker"
            value={draftTicker}
            onChange={(e) => setDraftTicker(e.target.value)}
            onBlur={refreshPrice}
            maxLength={10}
          />
          <button id="refresh-quote" type="button" onClick={refreshPrice}>
            Refresh price
          </button>
          <button
            id="new-chat"
            type="button"
            disabled={busy}
            onClick={() => {
              historyVersion.current++;
              setSession(newSession());
              setMessages([]);
              setStatus("");
            }}
          >
            New chat
          </button>
        </div>
        <QuoteCard
          id="quote-card"
          ticker={quoteTicker}
          active={active && ready}
          version={quoteVersion}
        />
        <div
          id="chat-messages"
          className="chat-messages"
          role="log"
          aria-label="Conversation"
          ref={log}
        >
          {messages.map((message, index) => (
            <div
              key={message.id || index}
              className={"chat-message " + message.role}
            >
              {message.role === "assistant" ? (
                <Markdown text={message.content} />
              ) : (
                message.content
              )}
            </div>
          ))}
        </div>
        <form id="chat-form" className="chat-form" onSubmit={send}>
          <textarea
            id="chat-input"
            rows={2}
            maxLength={4000}
            required
            aria-label="Message"
            placeholder="What’s the latest price? Run a research report on NVDA."
            value={input}
            onChange={(e) => setInput(e.target.value)}
          />
          <button id="chat-send" type="submit" disabled={busy}>
            Send
          </button>
        </form>
        <p id="chat-status" role="status" className="chat-status">
          {status}
        </p>
      </section>
    </main>
  );
}

import { useEffect, useRef } from "react";
import MarkdownIt from "markdown-it";
import { esc, fmt, safeUrl } from "../lib/format.js";
import { usePolling } from "../lib/hooks.js";
import { useCallback } from "react";
import { api } from "../lib/api.js";

const markdown = new MarkdownIt({ html: false });
markdown.validateLink = (url) => /^https?:\/\//i.test(url);
markdown.renderer.rules.image = (tokens, index) => esc(tokens[index].content);
export function Markdown({ text }) {
  return (
    <div dangerouslySetInnerHTML={{ __html: markdown.render(text || "") }} />
  );
}
// Only escaped, locally generated SVG is passed to this component, never provider HTML.
export function Chart({ html, ...props }) {
  return <div {...props} dangerouslySetInnerHTML={{ __html: html }} />;
}
export function SourceLink({ source, className = "" }) {
  const url = safeUrl(source?.url);
  return url ? (
    <a
      className={className}
      href={url}
      target="_blank"
      rel="noopener noreferrer"
    >
      {source.title} ↗
    </a>
  ) : (
    <span className={className}>{source?.title}</span>
  );
}
export function Citations({ ids = [], evidence = [] }) {
  const sources = [...new Set(ids)]
    .map((id) => evidence.find((item) => item.id === id))
    .filter(Boolean);
  return sources.length ? (
    <div className="citations">
      {sources.map((source) => (
        <SourceLink key={source.id} source={source} className="citation" />
      ))}
    </div>
  ) : null;
}
export function Dialog({ open, onClose, children, ...props }) {
  const ref = useRef();
  useEffect(() => {
    if (open && !ref.current.open) ref.current.showModal();
    else if (!open && ref.current.open) ref.current.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      {...props}
    >
      {children}
    </dialog>
  );
}
const quoteDelay = (q) =>
  q?.refresh_seconds ? q.refresh_seconds * 1000 : 60000;
export function QuoteCard({ ticker, active, id, version = 0 }) {
  const load = useCallback(
    (signal) => api("/quote/" + encodeURIComponent(ticker), { signal }),
    [ticker, version],
  );
  const result = usePolling(
    load,
    active && /^[A-Z][A-Z0-9.\-]{0,9}$/.test(ticker),
    quoteDelay,
  );
  const q = result.data?.ticker === ticker ? result.data : null;
  return (
    <div
      id={id}
      className={id === "quote-card" ? "quote-card" : undefined}
      aria-live="polite"
    >
      {result.error?.message ||
        (q
          ? `${q.ticker}  $${fmt(q.price)}  ·  ${q.source}  ·  ${q.freshness}  ·  ${q.as_of}`
          : `Checking ${ticker}…`)}
    </div>
  );
}
export function HeadlineList({ headlines = [], empty, ...props }) {
  return (
    <ul className="headline-list" {...props}>
      {headlines.length ? (
        headlines.map((headline, index) => {
          const post = headline.kind === "sentiment",
            stamp = new Date(headline.published);
          const published =
            headline.published && Number.isFinite(stamp.getTime())
              ? stamp.toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                  ...(post ? { timeZone: "UTC" } : {}),
                })
              : "";
          const source = post
            ? headline.title.replace(/^X post by /, "")
            : headline.source;
          const title = post
            ? headline.text.replace(/^Grok summary of the cited post: /, "")
            : headline.title;
          return (
            <li
              className="headline-row"
              key={headline.id || `${headline.url}-${index}`}
            >
              <div className="headline-meta">
                <span
                  className={"headline-type" + (post ? " headline-type-x" : "")}
                >
                  {post ? "X post" : "Article"}
                </span>
                <span>{source}</span>
                {published && (
                  <time dateTime={headline.published}>{published}</time>
                )}
              </div>
              <SourceLink
                source={{ title, url: headline.url }}
                className="headline-link"
              />
            </li>
          );
        })
      ) : (
        <li className="headline-empty">{empty}</li>
      )}
    </ul>
  );
}

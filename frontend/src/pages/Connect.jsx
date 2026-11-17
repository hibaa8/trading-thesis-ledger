import { useEffect, useRef, useState } from "react";
const localJson = JSON.stringify(
  {
    mcpServers: {
      "thesis-ledger": {
        command: "/absolute/path/to/uv",
        args: [
          "--directory",
          "/absolute/path/to/thesis-ledger",
          "run",
          "thesis-ledger-mcp",
        ],
      },
    },
  },
  null,
  2,
);
export default function Connect({ active, config }) {
  const [copied, setCopied] = useState({});
  const timers = useRef([]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  const publicUrl = config?.public_mcp_path
    ? new URL(config.public_mcp_path, location.origin).href
    : "";
  const publicJson = JSON.stringify(
    { mcpServers: { "thesis-ledger-market": { url: publicUrl } } },
    null,
    2,
  );
  async function copy(value, key) {
    try {
      await navigator.clipboard.writeText(value);
      setCopied((old) => ({ ...old, [key]: "Copied" }));
      timers.current.push(
        setTimeout(() => setCopied((old) => ({ ...old, [key]: "" })), 1500),
      );
    } catch {
      setCopied((old) => ({
        ...old,
        [key]: "Select and copy the configuration above",
      }));
    }
  }
  return (
    <main
      id="connect"
      hidden={!active}
      className={"page" + (active ? " active" : "")}
    >
      <div className="eyebrow">ONE WORKFLOW. YOUR FAVORITE CLIENT.</div>
      <h1>Research, wherever you work.</h1>
      <p className="subtitle">
        Connect a client over Streamable HTTP or run the full toolkit locally.
      </p>
      <section
        id="public-mcp"
        className="panel prose"
        hidden={!config?.public_mcp_path}
      >
        <span className="chip">PUBLIC · MARKET DATA</span>
        <h2>Connect without signing in</h2>
        <code id="public-mcp-url">{publicUrl}</code>
        <p>
          Ask for a market brief or a stock’s latest available quote. This
          connection has daily usage limits.
        </p>
        <p>
          <strong>Claude.</strong> Open Customize → Connectors, add a custom web
          connector, paste the URL, and select No sign in.
        </p>
        <p>
          <strong>Cursor.</strong> Merge this entry into your global or project{" "}
          <code>mcp.json</code>, then enable the server in Cursor.
        </p>
        <pre id="public-mcp-config">{publicJson}</pre>
        <button
          className="secondary"
          id="copy-public-config"
          onClick={() => copy(publicJson, "public")}
        >
          {copied.public || "Copy Cursor configuration"}
        </button>
        <p>
          Try asking your client to use Thesis Ledger to fetch the latest
          available NVDA quote and include its source and timestamp.
        </p>
      </section>
      <div className="two-col">
        <section className="panel prose">
          <span className="chip">OWNER · STREAMABLE HTTP</span>
          <h2>Full hosted toolkit</h2>
          <code id="mcp-url">{location.origin + "/mcp/"}</code>
          <p>
            Use a client that supports custom request headers, such as Cursor.
            Set <code>Authorization: Bearer &lt;LEDGER_API_TOKEN&gt;</code>{" "}
            using the owner token from Render. Keep it private. It grants access
            to saved owner research and can start model runs.
          </p>
        </section>
        <section className="panel prose">
          <span className="chip">LOCAL · STDIO</span>
          <h2>Run your own copy</h2>
          <p>
            With repository access, install uv, run <code>uv sync</code>, and
            put provider credentials in the checkout’s <code>.env</code>.
            Replace both paths below with the full paths on your machine.
          </p>
          <p>
            Merge this into Claude Desktop’s Developer → Edit Config or Cursor’s{" "}
            <code>mcp.json</code>. Restart the client after saving.
          </p>
          <pre id="mcp-config">{localJson}</pre>
          <button
            className="secondary"
            id="copy-config"
            onClick={() => copy(localJson, "local")}
          >
            {copied.local || "Copy local configuration"}
          </button>
        </section>
      </div>
      <section className="panel prose">
        <h2>Tools in the full toolkit</h2>
        <div className="tools-grid">
          <div>
            <code>market_brief</code>
            <p>Read market moves and sourced headlines.</p>
          </div>
          <div>
            <code>latest_price</code>
            <p>Get the latest price with its feed and observation time.</p>
          </div>
          <div>
            <code>research_ticker</code>
            <p>Run analysts, debate, forecasting, and risk review.</p>
          </div>
          <div>
            <code>get_research</code>
            <p>Inspect a saved report and source snapshot.</p>
          </div>
          <div>
            <code>search_theses</code>
            <p>Retrieve compact memories by asset and date.</p>
          </div>
          <div>
            <code>review_thesis</code>
            <p>Narrow or retire a memory with feedback.</p>
          </div>
          <div>
            <code>resume_research</code>
            <p>Continue from completed checkpoints.</p>
          </div>
        </div>
      </section>
    </main>
  );
}

export default function Method({ active }) {
  return (
    <main id="method" className={"page" + (active ? " active" : "")}>
      <div className="eyebrow">RESEARCH WORKFLOW</div>
      <h1>How it works</h1>
      <p className="subtitle">
        Follow a research question from its sources to a thesis you can revisit.
      </p>
      <section
        className="panel prose method-diagram"
        aria-labelledby="method-flow-title"
      >
        <h2 id="method-flow-title">From evidence to thesis</h2>
        <ol className="method-flow">
          <li>
            <span>01</span>
            <strong>Gather evidence</strong>
            <p>
              Save dated prices, financials, headlines, and relevant prior
              theses.
            </p>
          </li>
          <li>
            <span>02</span>
            <strong>Analyze in parallel</strong>
            <p>
              Specialists review technicals, fundamentals, news, and sentiment.
            </p>
          </li>
          <li>
            <span>03</span>
            <strong>Debate</strong>
            <p>
              Bull and bear agents make opposing cases and cite their evidence.
            </p>
          </li>
          <li>
            <span>04</span>
            <strong>Synthesize and review risk</strong>
            <p>
              The manager weighs both cases and the price scenarios. The risk
              reviewer can abstain.
            </p>
          </li>
          <li>
            <span>05</span>
            <strong>Save the thesis</strong>
            <p>
              Keep the report and a short memory with its sources and
              invalidation criteria.
            </p>
          </li>
        </ol>
        <div className="method-inputs">
          <p>
            <strong>Forecast → step 04.</strong> Price scenarios enter at
            synthesis, after the specialists and debate have formed their views.
          </p>
          <p>
            <strong>Thesis Ledger → step 01.</strong> A later run can retrieve
            relevant prior theses. Review can narrow or retire a memory.
          </p>
        </div>
      </section>
      <div className="two-col">
        <section className="panel prose">
          <h2>What each view does</h2>
          <p>
            <strong>Research desk</strong> shows the market, company headlines,
            specialist reports, debate, and risk review. The Evidence Room opens
            the sources behind a report.
          </p>
          <p>
            <strong>Research chat</strong> answers questions using market tools
            and saved reports, and can run the analyst team when asked.
          </p>
          <p>
            <strong>Forecast</strong> samples price scenarios from completed
            daily bars. Forecast Checks compares the historical-return model
            with a no-change baseline.
          </p>
          <p>
            <strong>Thesis Ledger</strong> keeps short, revisable research
            memories. <strong>Research History</strong> stores full reports and
            lets you resume an interrupted run.
          </p>
        </section>
        <section className="panel prose">
          <h2>Where the data comes from</h2>
          <p>
            <strong>Prices.</strong> Alpaca supplies quotes and intraday
            candles. Alpha Vantage supplies daily bars, with Alpaca as a
            fallback.
          </p>
          <p>
            <strong>Financials.</strong> Alpha Vantage supplies company metrics.
            SEC EDGAR supplies figures from filed quarterly and annual reports
            when the overview is unavailable.
          </p>
          <p>
            <strong>Headlines.</strong> Company coverage comes from Alpaca and
            Alpha Vantage. Market context comes from CNBC Markets, the Federal
            Reserve, and the Bureau of Labor Statistics.
          </p>
          <p>
            <strong>Sentiment.</strong> The analyst compares FINRA short-sale
            activity with recent sessions and uses ticker-specific news tone
            when available. When configured, Grok X Search adds cited posts from
            company and industry accounts. The report treats these as selected
            commentary.
          </p>
        </section>
      </div>
    </main>
  );
}

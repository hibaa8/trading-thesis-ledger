/* Private financial data is fetched only after a dedicated trading-key unlock. */
(() => {
  let accessKey = sessionStorage.getItem("ledger-trading-key") || "";
  let timer;
  const money = value => value === null || value === undefined ? "Unavailable" :
    new Intl.NumberFormat("en-US", {style: "currency", currency: "USD"}).format(Number(value));
  const time = value => value ? new Date(value).toLocaleString() : "Unknown";
  const label = value => String(value || "unknown").replaceAll("_", " ");
  function note(message, error = false) {
    $("trading-status").textContent = message;
    $("trading-status").classList.toggle("error", error);
  }
  async function request(path = "", options = {}) {
    const response = await fetch("/api/trading" + path, {...options, headers: {
      "Content-Type": "application/json", Authorization: "Bearer " + accessKey,
    }});
    if (response.status === 401) {
      lock();
      throw Error("Enter your private trading access key to open this view.");
    }
    let data;
    try { data = await response.json(); }
    catch { throw Error("The trading service is reconnecting. Please retry shortly."); }
    if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "Could not load trading data.");
    return data;
  }
  function lock() {
    accessKey = "";
    sessionStorage.removeItem("ledger-trading-key");
    clearTimeout(timer);
    $("trading-content").hidden = true;
    $("trading-unlock").hidden = false;
    $("trading-refresh").hidden = true;
    $("trading-key").value = "";
    for (const id of ["trading-stats", "trading-cycles", "trading-orders", "trading-events", "trading-positions"]) $(id).replaceChildren();
  }
  function stat(title, value, detail, cls = "") {
    return `<div><span>${esc(title)}</span><strong class="${cls}">${esc(money(value))}</strong><small>${esc(detail)}</small></div>`;
  }
  const tone = value => Number(value) > 0 ? "positive" : Number(value) < 0 ? "negative" : "";
  function chart(history) {
    const points = [...history].reverse().map(r => ({date: r.created, value: Number(r.payload.account_value)}));
    if (!points.length) return "";
    const w = 600, h = 140, pad = 16;
    const low = Math.min(...points.map(p => p.value)), high = Math.max(...points.map(p => p.value));
    const spread = high - low || Math.max(1, high * .02);
    const x = i => points.length === 1 ? w / 2 : pad + i / (points.length - 1) * (w - 2 * pad);
    const y = value => pad + (high + spread / 2 - value) / (spread * 2) * (h - 2 * pad);
    const coords = points.map((p, i) => `${x(i)},${y(p.value)}`).join(" ");
    return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Account value from saved Robinhood snapshots"><line x1="16" x2="584" y1="124" y2="124" class="candle-grid"/><polyline points="${coords}" fill="none" stroke="var(--green)" stroke-width="2"/>${points.map((p,i) => `<circle cx="${x(i)}" cy="${y(p.value)}" r="3" fill="var(--green)"><title>${esc(time(p.date))} · ${esc(money(p.value))}</title></circle>`).join("")}</svg>`;
  }
  function table(headings, rows) {
    return `<div class="trading-table-wrap"><table class="trading-table"><thead><tr>${headings.map(h=>`<th scope="col">${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
  }
  function render(data) {
    const record = data.snapshot;
    if (!record) {
      note("Waiting for the first Robinhood sync from the connected agent.");
      return;
    }
    const broker = record.payload;
    const age = Date.now() - Date.parse(broker.captured_at);
    $("trading-asof").textContent = `MCP ••••${broker.account_last4} · Synced ${time(broker.captured_at)}${age > 900000 ? " · Refresh needed" : ""}`;
    $("trading-approvals").textContent = broker.approvals_required ? "Approval required in Robinhood" : "Trade approvals are off";
    const net = broker.realized_pnl !== null && broker.unrealized_pnl !== null ? Number(broker.realized_pnl) + Number(broker.unrealized_pnl) : null;
    $("trading-stats").innerHTML = stat("Account value", broker.account_value, "Robinhood account") +
      stat("Cash available", broker.buying_power, "Without borrowing") +
      stat("Net profit / loss", net, "Realized + open positions", tone(net)) +
      stat("Realized profit / loss", broker.realized_pnl, label(broker.realized_window), tone(broker.realized_pnl));
    const funding = data.funding;
    $("trading-funding").textContent = `${money(funding.remaining)} available for new buy proposals`;
    $("trading-progress").value = Math.min(20, Number(funding.spent) + Number(funding.reserved));
    $("trading-budget").innerHTML = `<div><dt>Initial funding limit</dt><dd>${esc(money(funding.limit))}</dd></div><div><dt>Filled purchases</dt><dd>${esc(money(funding.spent))}</dd></div><div><dt>Reserved for proposals</dt><dd>${esc(money(funding.reserved))}</dd></div>`;
    $("trading-budget-note").textContent = funding.note;
    $("trading-equity-chart").innerHTML = chart(data.snapshots);
    $("trading-equity-note").textContent = data.snapshots.length < 2 ? "The first snapshot is saved. Future syncs build this history." : "Saved account values include deposits and withdrawals.";
    $("trading-positions").innerHTML = broker.positions.length ? table(["Holding", "Shares", "Average cost", "Value", "Open P&L"], broker.positions.map(p => `<tr><td>${esc(p.symbol)}</td><td>${esc(p.quantity)}</td><td>${esc(money(p.average_cost))}</td><td>${esc(money(p.market_value))}</td><td class="${tone(p.unrealized_pnl)}">${esc(money(p.unrealized_pnl))}</td></tr>`)) : '<p class="trading-empty">No open stock or ETF positions.</p>';
    const events = data.events.map(e=>e.payload);
    $("trading-orders").innerHTML = broker.orders.length ? table(["Stock", "Action", "Status", "Amount / shares", "Filled", "Origin"], broker.orders.map(o => {
      const tracked = events.some(e => (e.order_id && e.order_id === o.id) || (e.approval_id && e.approval_id === o.ref_id));
      return `<tr><td>${esc(o.symbol)}</td><td>${esc(label(o.side))}</td><td>${esc(label(o.state))}</td><td>${esc(o.dollar_based_amount ? money(o.dollar_based_amount.amount) : o.quantity)}</td><td>${esc(o.cumulative_quantity || "0")} shares${o.average_price ? " @ " + esc(money(o.average_price)) : ""}</td><td>${tracked ? "Thesis Ledger" : o.agent_initiated ? "Agent initiated" : "Account order"}</td></tr>`;
    })) : '<p class="trading-empty">No stock or ETF orders recorded by Robinhood.</p>';
    $("trading-events").innerHTML = events.length ? '<h3>Proposal activity</h3>' + events.map(e=>`<div class="trading-event"><strong>${esc(e.symbol)} · ${esc(label(e.side))} ${esc(money(e.amount_usd))}</strong><span>${esc(label(e.state))}</span><p>${esc(e.detail || "")}</p>${e.history?.length ? `<details><summary>Earlier states</summary>${e.history.map(h=>`<p>${esc(label(h.state))} · ${esc(time(h.recorded_at))}</p>`).join("")}</details>` : ""}</div>`).join("") : "";
    const queue = (data.requests || []).filter(r=>r.payload.status === "queued");
    $("trading-cycles").innerHTML = queue.map(r=>`<div class="info trading-queued"><span>Review queued · ${esc(r.payload.tickers.join(", "))} · ${esc(time(r.created))}</span><button type="button" class="trading-remove" data-remove-request="${esc(r.id)}" aria-label="Remove queued review for ${esc(r.payload.tickers.join(", "))}" title="Remove queued review">×</button></div>`).join("") + (data.cycles.length ? data.cycles.map(renderCycle).join("") : '<p class="trading-empty">The first review will appear here with the analysts, debate, manager decision and sources.</p>');
    $("trading-disclosures").innerHTML = (broker.market_data_disclosures || []).map(d=>`<p>${esc(d)}</p>`).join("");
    note(broker.orders_complete && broker.positions_complete ? "" : "Broker sync is incomplete. Review pagination before any proposal.");
  }
  function reportCard(role, report, sources) {
    return `<article class="trading-analyst"><h4>${esc(role)}</h4><span class="stance ${esc(report.stance)}">${esc(report.stance)}</span><p>${esc(report.stance_reason || report.summary)}</p><details><summary>Read assessment and sources</summary><p>${esc(report.summary)}</p><p>${esc(report.invalidation)}</p>${(report.evidence_ids || []).map(id=>sources.find(e=>e.id===id)).filter(Boolean).map(e=>sourceTitle(e)).join(" ")}</details></article>`;
  }
  function renderCycle(record) {
    const cycle = record.payload;
    const proposal = cycle.proposal;
    const heading = proposal ? `${label(proposal.side)} ${proposal.ticker} · ${money(proposal.amount_usd)}` : cycle.status === "complete" ? "No trade proposed" : label(cycle.status);
    const roleNames = {technical:"Technical",fundamentals:"Fundamentals",news:"News & catalysts",sentiment:"Sentiment"};
    return `<article class="panel trading-cycle"><div class="trading-cycle-heading"><h3>${esc(heading)}</h3><time>${esc(time(record.created))}</time></div><p>${esc(cycle.selection?.summary || cycle.reason || cycle.error || "Agents are reviewing the selected stocks.")}</p>${proposal ? `<p class="info">${esc(proposal.thesis)} Approval happens in Robinhood.</p>` : ""}${cycle.selection?.stance_reason ? `<p><strong>Manager reasoning.</strong> ${esc(cycle.selection.stance_reason)}</p>` : ""}${(cycle.candidates || []).map(c => `<details class="trading-candidate"><summary><strong>${esc(c.ticker)}</strong><span>${esc(c.decision?.stance || c.status)}</span><span>View reasoning</span></summary><p>${esc(c.decision?.summary || c.error || "")}</p>${c.exclusion_reason ? `<p>${esc(c.exclusion_reason)}</p>` : ""}<div class="trading-analysts">${Object.entries(roleNames).filter(([role])=>c.reports?.[role]).map(([role,name])=>reportCard(name,c.reports[role],c.evidence || [])).join("")}</div><details><summary>Bull / bear debate, manager & risk review</summary>${Object.entries(c.reports || {}).filter(([role])=>!roleNames[role]).map(([role,r])=>reportCard(label(role),r,c.evidence || [])).join("")}</details><details><summary>Saved workflow trace</summary><ol>${(c.trace || []).map(t=>`<li>${esc(t.stage)} · ${esc(t.detail)}</li>`).join("")}</ol></details></details>`).join("")}${cycle.experience ? `<details class="trading-memory"><summary>What the agents learned from earlier outcomes</summary><p>${esc(cycle.experience.summary)}</p><p>${esc(cycle.experience.stance_reason)}</p></details>` : ""}</article>`;
  }
  window.stopTradingRefresh = () => clearTimeout(timer);
  window.openTrading = async () => {
    clearTimeout(timer);
    if (!accessKey) return;
    try {
      const data = await request();
      $("trading-unlock").hidden = true;
      $("trading-content").hidden = false;
      $("trading-refresh").hidden = false;
      render(data);
      timer = setTimeout(window.openTrading, 30000);
    } catch (error) { note(error.message, true); }
  };
  $("trading-unlock").onsubmit = async event => {
    event.preventDefault();
    accessKey = $("trading-key").value.trim();
    sessionStorage.setItem("ledger-trading-key", accessKey);
    $("trading-key").value = "";
    await window.openTrading();
  };
  if ($("trading").classList.contains("active")) window.openTrading();
  $("trading-lock").onclick = lock;
  $("trading-refresh").onclick = window.openTrading;
  $("trading-cycles").addEventListener("click", async event => {
    const button = event.target.closest("[data-remove-request]");
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      await request("/requests/" + encodeURIComponent(button.dataset.removeRequest), {method: "DELETE"});
      await window.openTrading();
      note("Queued review removed.");
    } catch (error) {
      button.disabled = false;
      note(error.message, true);
    }
  });
  $("trading-request").onsubmit = async event => {
    event.preventDefault();
    const tickers = [...new Set($("trading-symbols").value.toUpperCase().split(/[\s,]+/).filter(Boolean))];
    if (tickers.length < 2 || tickers.length > 5 || tickers.some(t=>!(/^[A-Z][A-Z0-9.\-]{0,9}$/).test(t))) return note("Enter 2 to 5 valid stock or ETF symbols.", true);
    const id = crypto.randomUUID().replaceAll("-", "");
    try {
      await request("/records", {method:"POST", body:JSON.stringify({id,kind:"trading_request",created:new Date().toISOString(),payload:{tickers,status:"queued"}})});
      await window.openTrading();
      note("Your review is queued for the next scheduled agent check.");
    } catch (error) { note(error.message,true); }
  };
})();

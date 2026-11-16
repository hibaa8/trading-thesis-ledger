import {esc, fmt, money, time} from './format.js';
export function scenarioSvg(result, window = 40, target = "scenario") {
  if (!result?.snapshot?.bars?.length || !result?.forecast?.points?.length) return "";
  const bars = result.snapshot.bars.slice(-window),
    f = result.forecast.points,
    all = [...bars.map((b) => b.close), ...f.flatMap((p) => [p.low, p.high])];
  let lo = Math.min(...all) * 0.98,
    hi = Math.max(...all) * 1.02;
  const W = 800,
    H = 270,
    left = 12,
    right = 65,
    top = 15,
    bottom = 32,
    n = bars.length + f.length;
  const x = (i) => left + (i / (n - 1)) * (W - left - right),
    y = (v) => top + ((hi - v) / (hi - lo)) * (H - top - bottom),
    path = (pts) =>
      pts
        .map((p, i) => (i ? "L" : "M") + p.map((v) => v.toFixed(2)).join(","))
        .join(" ");
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Observed closing prices and forecast scenario range"><defs><linearGradient id="${target}-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#83e0bd" stop-opacity=".12"/><stop offset="1" stop-color="#83e0bd" stop-opacity="0"/></linearGradient></defs>`;
  for (let i = 0; i < 5; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    svg += `<line x1="${left}" y1="${y(v)}" x2="${W - right}" y2="${y(v)}" stroke="#263037" stroke-dasharray="3 5"/><text x="${W - right + 12}" y="${y(v) + 4}" fill="#7e8e98" font-size="10" font-family="monospace">${fmt(v)}</text>`;
  }
  const history = bars.map((b, i) => [x(i), y(b.close)]),
    last = history.at(-1),
    med = [last, ...f.map((p, i) => [x(bars.length + i), y(p.median)])];
  const band = [
    last,
    ...f.map((p, i) => [x(bars.length + i), y(p.high)]),
    ...f.map((p, i) => [x(bars.length + i), y(p.low)]).reverse(),
  ];
  svg += `<path d="${path(history)} L${last[0]},${H - bottom} L${left},${H - bottom} Z" fill="url(#${target}-fill)"/><path d="${path(band)} Z" fill="#b7a0f4" opacity=".13"/><line x1="${last[0]}" x2="${last[0]}" y1="${top}" y2="${H - bottom}" stroke="#73877e" stroke-dasharray="3 4"/><path d="${path(history)}" fill="none" stroke="#83e0bd" stroke-width="2"/><path d="${path(med)}" fill="none" stroke="#b7a0f4" stroke-width="2" stroke-dasharray="5 4"/>`;
  [0, Math.floor(bars.length / 2), bars.length - 1, n - 1].forEach((i) => {
    const d = i < bars.length ? bars[i].date : f.at(-1).date;
    svg += `<text x="${x(i)}" y="${H - 7}" text-anchor="${i === 0 ? "start" : i === n - 1 ? "end" : "middle"}" fill="#7e8e98" font-size="10" font-family="monospace">${esc(d.slice(5))}</text>`;
  });
  bars.forEach((b, i) => {
    svg += `<circle cx="${x(i)}" cy="${y(b.close)}" r="6" fill="transparent"><title>${esc(b.date)} · Close $${fmt(b.close)} · Volume ${fmt(b.volume, 0)}</title></circle>`;
  });
  f.forEach((p, i) => {
    svg += `<circle cx="${x(bars.length + i)}" cy="${y(p.median)}" r="6" fill="transparent"><title>${esc(p.date)} · Median $${fmt(p.median)} · Range $${fmt(p.low)}–$${fmt(p.high)}</title></circle>`;
  });
  return svg + "</svg>";
}

export function candleSvg({ bars, ticker, open, close }) {
  if (!bars?.length) return "";
  const w = 720, h = 285, left = 10, right = 66, top = 12, bottom = 30;
  const minimum = Math.min(...bars.map(bar => bar.l));
  const maximum = Math.max(...bars.map(bar => bar.h));
  const pad = Math.max((maximum - minimum) * 0.07, 0.01);
  const lo = minimum - pad, hi = maximum + pad;
  const start = Date.parse(open);
  const elapsed = Math.min(Date.parse(close), Date.parse(bars.at(-1).t) + 300_000) - start;
  const span = Math.max(300_000, elapsed);
  const x = time => left + (time - start) / span * (w - left - right);
  const y = price => top + (hi - price) / (hi - lo) * (h - top - bottom);
  const body = Math.min(14, (w - left - right) * 0.68 * 300_000 / span);
  const labelTime = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit",
  });
  let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(ticker)} five-minute candlestick chart">`;
  for (let i = 0; i <= 4; i++) {
    const price = lo + (hi - lo) * i / 4;
    svg += `<line class="candle-grid" x1="${left}" x2="${w-right}" y1="${y(price)}" y2="${y(price)}"/><text x="${w-right+10}" y="${y(price)+4}">${fmt(price)}</text>`;
  }
  for (let i = 0; i <= 4; i++) {
    const timestamp = start + span * i / 4;
    svg += `<text x="${x(timestamp)}" y="${h-7}" text-anchor="${i === 0 ? "start" : "middle"}">${labelTime.format(timestamp)}</text>`;
  }
  for (const bar of bars) {
    const cx = x(Date.parse(bar.t) + 150_000);
    const cls = bar.c >= bar.o ? "candle-up" : "candle-down";
    svg += `<g class="${cls}"><title>${labelTime.format(Date.parse(bar.t))} ET · Open ${fmt(bar.o)} · High ${fmt(bar.h)} · Low ${fmt(bar.l)} · Close ${fmt(bar.c)}</title>
      <line x1="${cx}" x2="${cx}" y1="${y(bar.h)}" y2="${y(bar.l)}"/>
      <rect x="${cx-body/2}" y="${Math.min(y(bar.o), y(bar.c))}" width="${body}" height="${Math.max(1, Math.abs(y(bar.o)-y(bar.c)))}"/></g>`;
  }
  return svg + "</svg>";
}

export function accountSvg(history) {
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

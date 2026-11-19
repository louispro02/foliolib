"use strict";
/* FolioLib: no library. Data never goes through innerHTML: everything is set with textContent. */
const NS = "http://www.w3.org/2000/svg";
const COLORS = ["--c1", "--c2", "--c3", "--c4", "--c5", "--c6", "--c7", "--c8", "--c9", "--c10"];
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

/* ---------------------------------------------------------------- language
   English is the source language: every text is written in English in this file, and `tt()` looks its translation up in the
   catalog that the server sends for the chosen language (/api/i18n). A text with no translation is shown in English.
   `{name}` marks a placeholder. `N_()` only marks a text that is translated later, where it is displayed. */
const LANGS = { en: "English", fr: "Français" };
const readCookie = name => { const hit = document.cookie.split("; ").find(c => c.startsWith(name + "=")); return hit ? hit.slice(name.length + 1) : ""; };
let LANG = readCookie("lang");
if (!LANGS[LANG]) LANG = [...(navigator.languages || []), navigator.language || ""].map(l => l.slice(0, 2).toLowerCase()).find(l => LANGS[l]) || "en";
try { document.cookie = "lang=" + LANG + "; Path=/; Max-Age=31536000; SameSite=Strict"; } catch (e) { /* cookies blocked: the browser's language is used */ }
document.documentElement.lang = LANG;
let CATALOG = {};
const N_ = text => text;
const tt = (text, params) => {
  const out = Object.hasOwn(CATALOG, text) ? CATALOG[text] : text;
  return params ? out.replace(/\{(\w+)\}/g, (m, k) => (k in params ? params[k] : m)) : out;
};
const plural = (n, one, many) => tt(n > 1 ? many : one, { n });
const LOCALE = LANG === "fr" ? "fr-FR" : (navigator.language || "").startsWith("en") ? navigator.language : "en-GB";
const PC = LANG === "fr" ? " %" : "%";      /* French puts a thin no-break space before the percent sign */

const fmt = (o, d) => new Intl.NumberFormat(LOCALE, { maximumFractionDigits: d, minimumFractionDigits: d, ...o });
const eur = (v, d = 0) => v == null ? "—" : fmt({ style: "currency", currency: "EUR" }, d).format(v);
const num = (v, d = 2) => v == null ? "—" : fmt({}, d).format(v);
const pct = (v, d = 1) => v == null ? "—" : (v >= 0 ? "+" : "") + fmt({}, d).format(v * 100) + PC;
const sgnEur = (v, d = 0) => v == null ? "—" : (v >= 0 ? "+" : "") + eur(v, d);
const cls = v => v == null ? "" : v >= 0 ? "up" : "down";
const $ = id => document.getElementById(id);
const longDate = iso => new Date(iso + "T12:00:00").toLocaleDateString(LOCALE, { day: "numeric", month: "long", year: "numeric" });

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style") { for (const decl of String(v).split(";")) { const i = decl.indexOf(":"); if (i > 0) e.style.setProperty(decl.slice(0, i).trim(), decl.slice(i + 1).trim()); } }   /* CSSOM: allowed by the CSP, unlike the style attribute */
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
function s(tag, attrs, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  for (const c of kids) if (c != null) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const clear = el => { while (el.firstChild) el.removeChild(el.firstChild); };
const niceMax = v => { const p = Math.pow(10, Math.floor(Math.log10(v || 1))); for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p; return v; };

const BENCH = [["world", "MSCI World", "--bench"], ["sp500", "S&P 500", "--c2"], ["nasdaq", "Nasdaq-100", "--c5"], ["em", N_("Emerging Markets"), "--c7"], ["eu600", "STOXX Europe 600", "--c6"], ["cac", "CAC 40", "--c4"]];
const LIVE = new Set(["yahoo", "twelvedata", "demo"]);   /* price sources that count as a recent quote */
const BDASH = { world: "2 4", sp500: "7 3", nasdaq: "1 3 6 3", em: "4 3", eu600: "2 2", cac: "9 3 2 3" };
const S = { data: null, acct: "all", range: "all", alloc: "holding", sort: { key: "value", dir: -1 }, q: "", bench: new Set(["world"]), heat: "month" };
const tip = $("tip");
const GLOSS = {
  tri: ["Internal rate of return (IRR)", "The annual rate which, applied to each of your deposits on its date, would grow your money to today's value. It accounts for the timing of your deposits: depositing just before a rise improves it.\nIt measures your actual experience as a saver. To judge the quality of the investments themselves, look at the time-weighted return instead."],
  twr: ["Time-weighted return (TWR)", "Measures the performance of the investments themselves by neutralizing your deposits: each day's return is computed, then the days are chained.\nThis is the measure to compare with an index or a fund. Here: securities only (excluding cash), dividends counted, purchase fees included, measured from the day the securities exceeded €500 (before that, €1 of fees on €2 invested would distort everything)."],
  vol: ["Annualized volatility", "The usual size of price swings: standard deviation of daily returns multiplied by the square root of 252 trading days. 15% means that a deviation of about 15% around the average annual return is common.\nThe higher it is, the bumpier the ride. Holidays count as 0: it is very slightly underestimated."],
  sharpe: ["Sharpe ratio", "Return earned above the risk-free rate (3%, assumed to be a typical savings account), divided by volatility. It tells how much return you earn per unit of risk.\nRules of thumb: below 0.5 weak, around 1 good, above 2 rare. Computed on monthly returns. With few months it is very uncertain: the \"±\" value is the Lo (2002) standard error. Do not over-interpret it."],
  sortino: ["Sortino ratio", "Like the Sharpe ratio, but only declines count as risk. A portfolio that rises sharply but almost never falls is penalized by the Sharpe ratio, not by the Sortino ratio."],
  mdd: ["Maximum drawdown", "The largest fall between a peak and the trough that follows, on the time-weighted index (deposits do not mask it). It is what you would have had to bear without selling. The date of return to the peak tells how long it lasted."],
  runup: ["Maximum run-up", "The largest rise between a trough and the peak that follows. The mirror image of maximum drawdown: it shows what a good streak can deliver, not what to expect."],
  var: ["Value at risk (VaR), 95%, 1 day", "A daily loss that should be exceeded only one trading day in twenty (5%). Parametric method: 1.645 × daily volatility × value. The historical figure is the observed 5th percentile.\nIt is not the worst possible loss: some days exceed this threshold."],
  months: ["Month consistency", "Share of rising months, and the longest consecutive streaks of rising and falling months. A long losing streak is harder to live through than a single big drop."],
  abs: ["Absolute change", "The difference in euros between the value of the securities at the end and at the start of the period. It includes your deposits: buying €1,000 of securities \"increases\" the value by €1,000 without any gain.\nThe \"Net gain\" column removes net deposits and adds dividends: it is the real gain in euros. The return is time-weighted."],
  heat: ["Periodic returns", "Each cell is the time-weighted return of the period (deposits neutralized), securities only, dividends counted. Green: rise, red: fall, darker: stronger. Dotted outline: incomplete period (start of history or current year). The color scale adapts to the length of the period."],
  bench: ["Benchmark indices", "Accumulating ETFs listed in euros: dividends reinvested and ETF fees deducted, so they are comparable to a portfolio that reinvests. \"Same deposits\": on each date you deposited money, the same amount is invested in that index. The gap in euros tells what your choice of holdings earned or cost compared with that index."],
  fees: ["Direct fees", "Fees actually paid: brokerage, currency conversion fees (such as DEGIRO's AutoFX), exchange connection fees. ETFs' internal fees (TER) are not included here: they are already deducted from their price."],
  taxes: ["Taxes paid", "Financial transaction tax (purchases of some French stocks) and withholding tax on foreign dividends. Capital gains tax is only due on sale: see the estimate."],
  taxest: ["Latent tax estimate", "If you sold the whole brokerage account today, a 30% flat tax (an assumption, adjust it to your situation) on its unrealized gain would give this amount. The PEA is not estimated: its taxation depends on the holding period. This is not tax advice."],
  bridge: ["Where the gain comes from", "The total gain (current value minus deposits) breaks down into unrealized gain (held positions, purchase fees included in the cost basis), realized gain (sales), dividends net of withholding, and a remainder: connection fees, taxes, interest, currency effects. The remainder should stay small: if it grows, an export is missing."],
  sim: ["Long-term projection", "A monthly simulation, not a forecast: each month, the capital earns the net return (return minus annual fees), then the deposit is added. Nothing guarantees these returns, and real markets alternate good and bad years: the smooth curve does not exist.\nThe two dotted curves show a return 2 points a year lower and higher than the central scenario, to give an idea of the possible gap. They bound nothing: a crisis can do worse.\nTax is not taken into account (flat tax, life insurance, PEA…): the result is before tax."],
  simreal: ["Today's euros", "With inflation, €1,000 in twenty years will buy less than today. This option divides each amount by (1 + inflation) raised to the power of the number of years: you then read purchasing power, not the nominal figure. Cumulative deposits remain counted as you pay them in."],
  simrate: ["Net return", "Assumed annual return minus annual fees (ETF, wrapper and management fees). It is the rate actually applied to the capital each year. Even 1 extra point of fees, over thirty years, costs several tens of percent of the final capital."],
  simrent: ["Sustainable monthly income (4% rule)", "A common rule of thumb: withdrawing 4% of the capital each year from the start of retirement (indexed to inflation) has historically lasted about thirty years on US markets. Here: 4% of the final capital, divided by 12. It is an order of magnitude, not a guarantee, and it is before tax."],
  ratio: ["Share of your deposits", "Fees and taxes paid relative to the capital deposited, then per year of holding: the average cost of the way you invest, excluding ETFs' internal fees."],
};

let pinned = null;
function info(key) {
  const g = GLOSS[key], b = h("button", { class: "info", type: "button", "aria-label": tt("Explanation: {title}", { title: tt(g[0]) }) }, "i");
  const show = () => {
    clear(tip); tip.className = "tip rich"; tip.append(h("b", null, tt(g[0])), ...tt(g[1]).split("\n").map(t => h("div", null, t))); tip.hidden = false;
    const r = b.getBoundingClientRect(), w = tip.offsetWidth;
    tip.style.left = Math.max(8, Math.min(r.left - 8, innerWidth - w - 8)) + "px"; tip.style.top = (r.bottom + 8) + "px";
  };
  const hide = () => { if (pinned !== b) { tip.hidden = true; tip.className = "tip"; } };
  b.addEventListener("mouseenter", show); b.addEventListener("mouseleave", hide); b.addEventListener("focus", show);
  b.addEventListener("blur", () => { if (pinned === b) pinned = null; hide(); });
  b.addEventListener("click", e => { e.stopPropagation(); if (pinned === b) { pinned = null; tip.hidden = true; } else { pinned = b; show(); } });
  return b;
}
document.addEventListener("click", () => { if (pinned) { pinned = null; tip.hidden = true; tip.className = "tip"; } });
document.addEventListener("keydown", e => { if (e.key === "Escape") { pinned = null; tip.hidden = true; tip.className = "tip"; } });
function showTip(ev, nodes) {
  tip.className = "tip";
  clear(tip); for (const n of nodes) tip.append(h("div", null, n));
  tip.hidden = false;
  const w = tip.offsetWidth;
  tip.style.left = Math.max(8, Math.min(ev.clientX + 14, innerWidth - w - 8)) + "px"; tip.style.top = (ev.clientY + 14) + "px";
}
const hideTip = () => { tip.hidden = true; };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (r.status === 401) { location.href = "/login"; throw new Error("auth"); }
  return r.json();
}
async function load() { S.data = await api("/api/data"); render(); }
function view() {
  const d = S.data, a = S.acct;
  return { pos: d.positions.filter(p => a === "all" || p.broker === a), accts: d.accounts.filter(x => a === "all" || x.key === a) };
}
function render() {
  const d = S.data;
  renderBar(d); renderHero(d); renderChart(d); renderCompare(d); renderPerf(d); renderTable(d); renderAlloc(d); renderEnv(d); renderDiv(d); renderLists(d); renderCosts(d); renderSim(d); renderData(d);
}

/* ---------------------------------------------------------------- static text, language switch */
function translateStatic() {
  /* Marked in index.html: data-t = the element's own text, data-t-attrs = the attributes to translate (comma separated). The
     English original is kept on the element, so the page can be translated from it at any time. */
  for (const el of document.querySelectorAll("[data-t]")) { el.dataset.en ??= el.textContent.trim(); el.textContent = tt(el.dataset.en); }
  for (const el of document.querySelectorAll("[data-t-attrs]")) {
    for (const a of el.dataset.tAttrs.split(",")) { const keep = "en_" + a.replace(/-/g, "_"); el.dataset[keep] ??= el.getAttribute(a); el.setAttribute(a, tt(el.dataset[keep])); }
  }
}
function renderLangSwitch() {
  const seg = $("lang"); clear(seg);
  for (const code of Object.keys(LANGS)) seg.append(h("button", { type: "button", lang: code, title: LANGS[code], "aria-pressed": LANG === code,
    onclick: () => { if (code === LANG) return; document.cookie = "lang=" + code + "; Path=/; Max-Age=31536000; SameSite=Strict"; location.reload(); } }, code.toUpperCase()));
}

/* ---------------------------------------------------------------- bar, hero */
function renderBar(d) {
  const seg = $("acct"); clear(seg);
  for (const [k, l] of [["all", tt("All")], ...d.accounts.map(x => [x.key, x.short])])
    seg.append(h("button", { "aria-pressed": S.acct === k, onclick: () => { S.acct = k; render(); } }, l));
  const f = $("fresh");
  if (d.empty) { f.textContent = tt("No data: drop your exports at the bottom of the page."); f.className = "fresh warn"; }
  else if (d.last_refresh) {
    const m = Math.round((Date.now() / 1000 - d.last_refresh) / 60);
    f.textContent = m < 1 ? tt("Prices updated just now") : m < 90 ? tt("Prices updated {n} min ago", { n: m }) : tt("Prices updated {n} h ago", { n: Math.round(m / 60) });
    f.className = "fresh " + (d.last_error ? "warn" : "ok");
  } else { f.textContent = tt("Prices never updated"); f.className = "fresh warn"; }
  const w = $("warn"), msgs = [...(d.last_error ? [d.last_error] : []), ...d.warnings];
  w.hidden = !msgs.length; clear(w);
  if (msgs.length) w.append(h("strong", null, tt("Heads up")), h("ul", null, msgs.map(m => h("li", null, m))));
}
function renderHero(d) {
  const { pos, accts } = view(), all = S.acct === "all", k = d.kpi;
  const value = all ? k.value : accts.reduce((t, x) => t + x.value, 0), inv = all ? k.invested : accts.reduce((t, x) => t + x.invested, 0);
  const gain = value - inv, irr = all ? k.irr : accts[0] && accts[0].irr;
  const day = pos.reduce((t, p) => t + (p.day_eur || 0), 0), unreal = pos.reduce((t, p) => t + p.gain, 0), cost = pos.reduce((t, p) => t + p.cost, 0);
  $("hero-date").textContent = longDate(d.as_of);
  $("hero-value").textContent = d.empty ? "—" : eur(value);
  const dl = $("hero-delta"); clear(dl);
  if (!d.empty) {
    const params = { pct: pct(inv ? gain / inv : null), amount: eur(inv), rate: pct(irr) };
    dl.append(h("b", { class: cls(gain) }, sgnEur(gain)), " " + (irr != null ? tt("gain ({pct}) on {amount} deposited, i.e. {rate} a year.", params) : tt("gain ({pct}) on {amount} deposited.", params)));
  }
  const f = $("facts"); clear(f);
  const fact = (label, v, sub, c) => f.append(h("div", null, h("dt", null, tt(label)), h("dd", { class: c || "" }, v), h("small", null, sub || "")));
  fact(N_("Today"), sgnEur(day, 0), pos.some(p => p.day_eur != null) ? tt("{pct} of value", { pct: pct(value ? day / (value - day) : null, 2) }) : tt("prices unavailable"), cls(day));
  fact(N_("Unrealized gain"), sgnEur(unreal), cost ? tt("{pct} on cost basis", { pct: pct(unreal / cost) }) : "", cls(unreal));
  fact(N_("Dividends, 12 months"), all ? eur(k.dividends_12m) : "—", all ? tt("{amount} since inception", { amount: eur(k.dividends) }) : tt("all accounts only"));
  fact(N_("Realized gain"), all ? sgnEur(k.realized) : "—", all ? tt("past sales, fees included") : tt("all accounts only"), all ? cls(k.realized) : "");
}

/* ---------------------------------------------------------------- chart */
const RANGES = [[N_("1 month"), 30], [N_("6 months"), 182], [N_("1 year"), 365], [N_("All"), 0]];
function benchChips(box, redraw) {
  clear(box);
  for (const [k, label, col] of BENCH) box.append(h("button", { class: "chip", type: "button", "aria-pressed": S.bench.has(k),
    onclick: () => { S.bench.has(k) ? S.bench.delete(k) : S.bench.add(k); redraw(); } }, h("i", { style: "border-color:" + css(col) }), tt(label)));
}
function renderChart(d) {
  const seg = $("range"); clear(seg);
  for (const [l, n] of RANGES) seg.append(h("button", { "aria-pressed": S.range === (n || "all"), onclick: () => { S.range = n || "all"; renderChart(d); } }, tt(l)));
  const sr = d.series, el = $("chart-main"), lg = $("legend-main"); clear(el); clear(lg);
  if (!sr.days || !sr.days.length) { el.append(h("p", { class: "muted" }, tt("No chart yet: drop your exports below."))); return; }
  const a = S.acct, val = a === "all" ? sr.value : sr.by_account[a], dep = a === "all" ? sr.deposits : sr.deposits_by_account[a];
  let from = 0;
  if (S.range !== "all") { const cut = new Date(Date.now() - S.range * 864e5).toISOString().slice(0, 10); from = Math.max(0, sr.days.findIndex(x => x >= cut)); }
  const days = sr.days.slice(from);
  const series = [
    { name: tt("Securities value"), color: css("--you"), v: val.slice(from), area: true, w: 2.6 },
    { name: tt("Cumulative deposits"), color: css("--muted"), v: dep.slice(from), dash: "6 4", w: 1.8 },
  ];
  if (a === "all") for (const [k, label, col] of BENCH) if (S.bench.has(k) && sr.benchmarks && sr.benchmarks[k])
    series.push({ name: tt("{name}, same deposits", { name: tt(label) }), color: css(col), v: sr.benchmarks[k].slice(from), dash: BDASH[k], w: 2 });
  lineChart(el, days, series, { zero: true });
  const l1 = h("div", { class: "legend" }); for (const x of series.slice(0, 2)) l1.append(h("span", null, h("i", { class: x.dash ? "dash" : "", style: "border-color:" + x.color }), x.name));
  lg.append(l1);
  if (a === "all") { const box = h("div", { class: "legend chips" }, h("span", { class: "muted small" }, tt("Compare with")), info("bench")); const row = h("div", { class: "legend chips" }); benchChips(row, () => { renderChart(d); renderPerf(d); }); lg.append(box, row); }
}
function lineChart(el, days, series, opts = {}) {
  const W = 1000, H = 380, L = 50, R = 8, T = 10, B = 26, fmtY = opts.fmtY || (v => v >= 1000 ? num(v / 1000, v % 1000 ? 1 : 0) + " k€" : Math.round(v) + " €"), fmtV = opts.fmtV || eur;
  const all = series.flatMap(x => x.v.filter(y => y != null)), hi = Math.max(...all, 1), lo = Math.min(...all);
  const min = opts.zero ? 0 : Math.floor(lo * 0.94 / 10) * 10, max = opts.zero ? niceMax(hi * 1.05) : Math.ceil(hi * 1.04 / 10) * 10;
  const X = i => L + (W - L - R) * (days.length > 1 ? i / (days.length - 1) : .5), Y = v => T + (H - T - B) * (1 - (v - min) / (max - min));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || tt("Portfolio value, cumulative deposits and MSCI World benchmark over time") });
  const g = s("g", { class: "grid" }), ax = s("g", { class: "axis" });
  for (let i = 0; i <= 4; i++) { const v = min + (max - min) * i / 4, y = Y(v); g.append(s("line", { x1: L, x2: W - R, y1: y, y2: y })); ax.append(s("text", { x: L - 8, y: y + 4, "text-anchor": "end" }, fmtY(v))); }
  const ticks = Math.min(5, days.length);
  for (let i = 0; i < ticks; i++) { const idx = Math.round(i * (days.length - 1) / Math.max(1, ticks - 1)); ax.append(s("text", { x: X(idx), y: H - 6, "text-anchor": i === 0 ? "start" : i === ticks - 1 ? "end" : "middle" }, opts.xLabel ? opts.xLabel(idx, true) : new Date(days[idx]).toLocaleDateString(LOCALE, { month: "short", year: "2-digit" }))); }
  svg.append(g, ax);
  const base = Y(min);
  for (const x of series) {
    let dd = "", pen = false;
    x.v.forEach((v, i) => { if (v == null) { pen = false; return; } dd += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
    if (x.area) svg.append(s("path", { d: dd + `L${X(x.v.length - 1)} ${base}L${X(0)} ${base}Z`, fill: x.color, opacity: ".09" }));
    svg.append(s("path", { d: dd, fill: "none", stroke: x.color, "stroke-width": x.w, "stroke-linejoin": "round", "stroke-linecap": "round", "stroke-dasharray": x.dash || "" }));
  }
  const cross = s("line", { y1: T, y2: H - B, stroke: css("--muted"), "stroke-width": 1, opacity: 0 }), dots = series.map(x => s("circle", { r: 4.5, fill: x.color, stroke: css("--paper"), "stroke-width": 2, opacity: 0 }));
  const hit = s("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" });
  svg.append(cross, ...dots, hit);
  hit.addEventListener("pointermove", ev => {
    const r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(days.length - 1, Math.round((px - L) / (W - L - R) * (days.length - 1))));
    cross.setAttribute("x1", X(i)); cross.setAttribute("x2", X(i)); cross.setAttribute("opacity", 1);
    series.forEach((x, k) => { if (x.v[i] == null) { dots[k].setAttribute("opacity", 0); return; } dots[k].setAttribute("cx", X(i)); dots[k].setAttribute("cy", Y(x.v[i])); dots[k].setAttribute("opacity", 1); });
    showTip(ev, [opts.xLabel ? opts.xLabel(i) : longDate(days[i]), ...series.filter(x => x.v[i] != null).map(x => h("span", null, h("i", { style: "border-color:" + x.color }), tt("{label}: ", { label: x.name }), h("b", null, fmtV(x.v[i]))))]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("opacity", 0); dots.forEach(x => x.setAttribute("opacity", 0)); hideTip(); });
  el.append(svg);
}

/* ---------------------------------------------------------------- comparison */
function renderCompare(d) {
  const blk = $("compare-block"), c = d.compare;
  blk.hidden = !c || S.acct !== "all";
  if (blk.hidden) return;
  const el = $("compare"); clear(el);
  const col = k => css((BENCH.find(b => b[0] === k) || [0, 0, "--muted"])[2]);
  const rows = [{ n: tt("Your portfolio"), sub: tt("securities and cash"), v: c.portfolio, irr: c.irr_portfolio, col: css("--you"), me: true },
    ...[...c.benchmarks].sort((x, y) => y.value - x.value).map(b => ({ n: b.label, sub: tt("same deposits, same days"), v: b.value, irr: b.irr, col: col(b.key), diff: b.diff })),
    { n: tt("Savings account at 3%"), sub: tt("assumption"), v: c.livret, irr: c.irr_livret, col: css("--muted"), diff: c.alpha_livret }];
  const max = Math.max(...rows.map(r => r.v)), beaten = c.benchmarks.filter(b => b.diff >= 0).length;
  const lede = $("cmp-lede"); clear(lede);
  lede.append(tt("With the same deposit schedule ({amount} in total), your portfolio beats {beaten} of {total} indices. A benchmark index is an accumulating euro-denominated ETF: dividends reinvested, ETF fees deducted. ",
    { amount: eur(c.invested), beaten, total: c.benchmarks.length }), info("bench"));
  for (const r of rows) el.append(h("div", { class: "cmp" },
    h("div", { class: "n" }, r.n, h("small", null, r.sub)),
    h("div", { class: "track", "aria-hidden": "true" }, h("div", { class: "fill", style: `width:${r.v / max * 100}%;background:${r.col}` })),
    h("div", { class: "v" }, eur(r.v), h("small", null, tt("{total} · {rate} a year", { total: pct((r.v - c.invested) / c.invested), rate: pct(r.irr) }) + (r.diff != null ? tt(" · you: {diff}", { diff: sgnEur(r.diff) }) : "")))));
}

/* ---------------------------------------------------------------- performance, risk */
const dShort = iso => new Date(iso + "T12:00:00").toLocaleDateString(LOCALE, { month: "short", year: "numeric" });
function tile(label, key, value, sub, c) { return h("div", { class: "tile" }, h("dt", null, label, info(key)), h("dd", { class: c || "" }, value), h("small", null, sub || "")); }
function renderPerf(d) {
  const P = d.perf && d.perf[S.acct], blk = $("perf-block"), hb = $("heat-block");
  blk.hidden = hb.hidden = !P;
  if (!P) return;
  const m = P.m, { accts } = view(), irr = S.acct === "all" ? d.kpi.irr : accts[0] && accts[0].irr;
  $("perf-since").textContent = tt("Measured since {date}, securities only, dividends counted", { date: longDate(m.start) });
  const t = $("risk"); clear(t);
  const sh = m.sharpe, rec = m.mdd_recovered ? tt("back to peak in {date}", { date: dShort(m.mdd_recovered) }) : tt("peak not yet regained");
  t.append(
    tile(tt("Annualized return (IRR)"), "tri", irr == null ? "—" : pct(irr), tt("accounts for the timing of your deposits"), cls(irr)),
    tile(tt("Time-weighted return (TWR)"), "twr", pct(m.twr_total), m.twr_annual != null ? tt("{rate} a year, deposits neutralized", { rate: pct(m.twr_annual) }) : tt("for less than a year"), cls(m.twr_total)),
    tile(tt("Annualized volatility"), "vol", num(m.volatility * 100, 1) + PC, tt("usual size of price swings")),
    tile(tt("Sharpe ratio"), "sharpe", sh == null ? "—" : num(sh, 2), sh == null ? "" : tt("± {se} uncertainty over {months} months", { se: num(m.sharpe_se, 2), months: m.months })),
    tile(tt("Sortino ratio"), "sortino", m.sortino == null ? "—" : num(m.sortino, 2), tt("only penalizes declines")),
    tile(tt("Maximum drawdown"), "mdd", pct(m.max_drawdown), tt("{from} → {to}, {recovery}", { from: dShort(m.mdd_peak), to: dShort(m.mdd_trough), recovery: rec }), "down"),
    tile(tt("Maximum run-up"), "runup", pct(m.max_runup), dShort(m.runup_from) + " → " + dShort(m.runup_to), "up"),
    tile(tt("Likely 1-day loss (95%)"), "var", eur(m.var95_pct * P.value_end), tt("parametric {pct}", { pct: num(m.var95_pct * 100, 1) + PC }) + (m.var95_hist_pct != null ? tt(" · historical {pct}", { pct: num(m.var95_hist_pct * 100, 1) + PC }) : "")),
    tile(tt("Rising months"), "months", m.positive_months == null ? "—" : num(m.positive_months * 100, 0) + PC, tt("streaks: up to {up} rising months in a row, {down} falling", { up: m.streak_up_months, down: m.streak_down_months })),
    tile(tt("Best and worst month"), "months", m.best_month ? pct(m.best_month[1]) : "—", m.best_month ? dShort(m.best_month[0] + "-15") + tt(" · worst: {pct} in {date}", { pct: pct(m.worst_month[1]), date: dShort(m.worst_month[0] + "-15") }) : ""),
  );
  // base-100 curve
  const cv = P.curve, el = $("chart-idx"); clear(el);
  const series = [{ name: tt("Your portfolio"), color: css("--you"), v: cv.portfolio, w: 2.8, area: false }];
  for (const [k, label, colv] of BENCH) if (S.bench.has(k) && cv.bench[k]) series.push({ name: tt(label), color: css(colv), v: cv.bench[k], dash: BDASH[k], w: 2 });
  lineChart(el, cv.days, series, { zero: false, fmtY: v => Math.round(v), fmtV: v => num(v, 1) });
  benchChips($("chips-idx"), () => { renderChart(d); renderPerf(d); });
  // comparison table
  const th = $("bench-table").tHead, tb = $("bench-table").tBodies[0]; clear(th); clear(tb);
  th.append(h("tr", null, [N_("Over the same period"), N_("Total return"), N_("Per year"), N_("Volatility"), N_("Sharpe"), N_("Max drawdown")].map(x => h("th", { scope: "col" }, tt(x)))));
  const row = (n, mm, me) => tb.append(h("tr", { class: me ? "me" : "" }, h("td", null, n), h("td", { class: cls(mm.twr_total) }, pct(mm.twr_total)), h("td", null, mm.twr_annual == null ? "—" : pct(mm.twr_annual)), h("td", null, num(mm.volatility * 100, 1) + PC), h("td", null, mm.sharpe == null ? "—" : num(mm.sharpe, 2)), h("td", { class: "down" }, pct(mm.max_drawdown))));
  row(tt("Your portfolio"), m, true); for (const b of P.bench) row(b.label, b.m, false);
  // absolute change
  const ph = $("periods").tHead, pb = $("periods").tBodies[0]; clear(ph); clear(pb);
  ph.append(h("tr", null, h("th", { scope: "col" }, tt("Period")), ...[N_("Start value"), N_("End value"), N_("Deposits"), N_("Dividends"), N_("Absolute change"), N_("Net gain"), N_("Return")].map(x => h("th", { scope: "col" }, x === "Absolute change" ? [tt(x), info("abs")] : tt(x)))));
  for (const p of P.periods) pb.append(h("tr", null, h("td", { title: tt("since {date}", { date: longDate(p.from) }) }, p.label), h("td", null, eur(p.v_start)), h("td", null, eur(p.v_end)), h("td", null, sgnEur(p.flows)), h("td", null, eur(p.dividends)), h("td", { class: cls(p.change) }, sgnEur(p.change)), h("td", { class: cls(p.gain) }, sgnEur(p.gain)), h("td", { class: cls(p.twr) }, pct(p.twr))));
  renderHeat(P);
}

/* ---------------------------------------------------------------- heat map */
const HEAT = [["month", N_("Month"), 0.08], ["quarter", N_("Quarter"), 0.12], ["half", N_("Half-year"), 0.18], ["year", N_("Year"), 0.30]];
const MONTHS = [N_("Jan"), N_("Feb"), N_("Mar"), N_("Apr"), N_("May"), N_("Jun"), N_("Jul"), N_("Aug"), N_("Sep"), N_("Oct"), N_("Nov"), N_("Dec")];
function renderHeat(P) {
  const seg = $("heat-by"); clear(seg);
  for (const [k, l] of HEAT) seg.append(h("button", { "aria-pressed": S.heat === k, onclick: () => { S.heat = k; renderHeat(P); } }, tt(l)));
  seg.parentNode.querySelector(".info") || seg.before(info("heat"));
  const byMonth = new Map(P.monthly.map(([m, r, partial]) => [m, { r, partial }])), years = [...new Set(P.monthly.map(x => x[0].slice(0, 4)))];
  const groups = S.heat === "month" ? MONTHS.map((l, i) => [tt(l), [i + 1]]) : S.heat === "quarter" ? [1, 2, 3, 4].map(q => [tt("Q{n}", { n: q }), [3 * q - 2, 3 * q - 1, 3 * q]]) : S.heat === "half" ? [[tt("H{n}", { n: 1 }), [1, 2, 3, 4, 5, 6]], [tt("H{n}", { n: 2 }), [7, 8, 9, 10, 11, 12]]] : [];
  const ref = HEAT.find(x => x[0] === S.heat)[2], now = new Date(S.data.as_of + "T12:00:00");
  const cell = (months, y) => {
    const have = months.map(mo => byMonth.get(y + "-" + String(mo).padStart(2, "0"))).filter(Boolean);
    if (!have.length) return h("td", { class: "empty" }, "·");
    const r = have.reduce((a, x) => a * (1 + x.r), 1) - 1, due = months.filter(mo => new Date(+y, mo - 1, 1) <= now).length;
    const part = have.length < months.length || have.some(x => x.partial);
    const k = Math.min(1, Math.abs(r) / ref), td = h("td", { class: part ? "partial" : "", style: `background:color-mix(in srgb, ${r >= 0 ? "var(--gain)" : "var(--loss)"} ${Math.round(14 + k * 46)}%, var(--surface))` }, num(r * 100, Math.abs(r) < 0.1 ? 1 : 0).replace("-", "−"));
    td.title = ""; td.addEventListener("pointermove", ev => showTip(ev, [y + " · " + (months.length === 1 ? tt(MONTHS[months[0] - 1]) : months.length === 12 ? tt("year") : tt("period")), h("b", null, pct(r, 2)), part ? tt("incomplete period") : ""]));
    td.addEventListener("pointerleave", hideTip);
    return td;
  };
  const tbl = h("table", { class: "heat", "aria-label": tt("Returns by {period}", { period: tt(HEAT.find(x => x[0] === S.heat)[1]).toLowerCase() }) }), head = h("tr", null, h("th", { class: "y", scope: "col" }, "%"));
  for (const [l] of groups) head.append(h("th", { scope: "col" }, l));
  head.append(h("th", { scope: "col" }, tt("Year")));
  tbl.append(h("thead", null, head));
  const body = h("tbody");
  for (const y of years.slice().reverse()) {
    const tr = h("tr", null, h("th", { class: "y", scope: "row" }, y));
    for (const [, ms] of groups) tr.append(cell(ms, y));
    const tot = cell([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], y); tot.classList.add("total"); tr.append(tot);
    body.append(tr);
  }
  tbl.append(body);
  const box = $("heat"); clear(box); box.append(tbl);
  $("heat-note").textContent = tt("Time-weighted return, in %, securities only. Dotted outline: incomplete period (start of history or current year). Hover a cell for details.");
}

/* ---------------------------------------------------------------- fees, taxes, origin of the gain */
function renderCosts(d) {
  const c = d.costs, el = $("costs"), br = $("bridge"); clear(el); clear(br);
  $("costs-block").hidden = !c;
  if (!c) return;
  const row = (l, v, extra) => h("div", { class: "costrow " + (extra || "") }, h("span", null, l), h("b", null, eur(v, 2)));
  el.append(h("h3", { class: "mini" }, tt("Fees paid"), info("fees")), ...c.fees.map(x => row(x.label, x.eur)), row(tt("Total fees"), c.total_fees, "sum"),
    h("h3", { class: "mini" }, tt("Taxes paid"), info("taxes")), ...c.taxes.map(x => row(x.label, x.eur)), row(tt("Total taxes"), c.total_taxes, "sum"),
    h("div", { class: "costrow" }, h("span", null, tt("Fees and taxes, as a share of deposits"), info("ratio")), h("b", null, tt("{total} · {perYear} a year", { total: num(c.pct_invested * 100, 2) + PC, perYear: num(c.per_year_pct * 100, 2) + PC }))),
    h("div", { class: "costrow" }, h("span", null, tt("Estimated latent tax on the brokerage account ({rate})", { rate: num(c.tax_estimate.rate * 100, 0) + PC }), info("taxest")), h("b", null, eur(c.tax_estimate.amount))),
    h("p", { class: "muted small" }, tt("Excluding ETFs' internal fees (already in their price) and PEA tax.")));
  const b = c.bridge, items = [[tt("Unrealized gain"), b.unrealized], [tt("Realized gain"), b.realized], [tt("Net dividends"), b.dividends], [tt("Other: connection fees, taxes, interest, currency"), b.other]];
  const max = Math.max(...items.map(x => Math.abs(x[1])), 1);
  br.append(h("h3", { class: "mini" }, tt("Where the gain comes from"), info("bridge")));
  for (const [l, v] of items) br.append(h("div", { class: "bridge-row" }, h("span", null, l), h("div", { class: "zero", "aria-hidden": "true" }, h("div", { class: "bar", style: `width:${Math.abs(v) / max * 100}%;background:${v >= 0 ? "var(--gain)" : "var(--loss)"}` })), h("b", { class: cls(v) }, sgnEur(v, 0))));
  br.append(h("div", { class: "bridge-row total" }, h("span", null, tt("Total gain")), h("span"), h("b", { class: cls(b.gain) }, sgnEur(b.gain, 0))));
}

/* ---------------------------------------------------------------- table */
const COLS = [
  ["name", N_("Holding")], ["account", N_("Account")], ["qty", N_("Quantity")], ["pru", N_("Avg. cost")], ["price", N_("Price")], ["value", N_("Value")],
  ["weight", N_("Weight")], ["gain", "+/- €"], ["gain_pct", "+/- %"], ["day_pct", N_("Day")], ["spark", N_("3 months")],
];
/* Texts the server sends as codes and the page translates where it shows them: N_("cost basis"), N_("export"). */
function sparkline(vals) {
  if (!vals || vals.length < 2) return h("span", { class: "muted" }, "—");
  const W = 76, H = 24, lo = Math.min(...vals), hi = Math.max(...vals), up = vals[vals.length - 1] >= vals[0];
  const pts = vals.map((v, i) => `${(i / (vals.length - 1) * (W - 2) + 1).toFixed(1)},${(H - 3 - (hi === lo ? .5 : (v - lo) / (hi - lo)) * (H - 6)).toFixed(1)}`).join(" ");
  return s("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "spark", role: "img", "aria-label": up ? tt("upward trend over 3 months") : tt("downward trend over 3 months") },
    s("polyline", { points: pts, fill: "none", stroke: up ? css("--gain") : css("--loss"), "stroke-width": 1.8, "stroke-linejoin": "round", "stroke-linecap": "round" }));
}
function renderTable(d) {
  const { pos } = view(), thead = document.querySelector("#pos thead"), tbody = document.querySelector("#pos tbody");
  clear(thead); clear(tbody);
  const tr = h("tr");
  for (const [k, l] of COLS) {
    const sortable = k !== "spark";
    tr.append(h("th", { scope: "col", tabindex: sortable ? 0 : null, "aria-sort": S.sort.key === k ? (S.sort.dir > 0 ? "ascending" : "descending") : null,
      onclick: sortable ? () => { S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (k === "name" || k === "account" ? 1 : -1) }; renderTable(d); } : null,
      onkeydown: sortable ? e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); } } : null }, tt(l) + (S.sort.key === k ? (S.sort.dir > 0 ? " ▲" : " ▼") : "")));
  }
  thead.append(tr);
  const q = S.q.toLowerCase(), key = S.sort.key;
  const rows = pos.filter(p => !q || (p.name + p.isin + (p.symbol || "")).toLowerCase().includes(q))
    .sort((a, b) => { const x = a[key] ?? -1e18, y = b[key] ?? -1e18; return (typeof x === "string" ? x.localeCompare(y) : x - y) * S.sort.dir; });
  const maxW = Math.max(...rows.map(r => r.weight), 1e-4);
  for (const p of rows) {
    const live = LIVE.has(p.source);
    tbody.append(h("tr", null,
      h("td", { class: "name" }, p.name, live ? null : h("span", { class: "tag warn", title: tt("No recent price for this holding") }, tt(p.source)), h("small", null, p.isin + (p.symbol ? " · " + p.symbol : ""))),
      h("td", null, p.account_short),
      h("td", null, num(p.qty, p.qty % 1 ? 3 : 0)), h("td", null, eur(p.pru, 2)), h("td", null, eur(p.price, 2)), h("td", null, eur(p.value)),
      h("td", { class: "w" }, h("span", { class: "wbar", style: `width:${Math.max(2, p.weight / maxW * 40)}px` }), num(p.weight * 100, 1) + PC),
      h("td", { class: cls(p.gain) }, sgnEur(p.gain)), h("td", { class: cls(p.gain_pct) }, pct(p.gain_pct)), h("td", { class: cls(p.day_pct) }, pct(p.day_pct, 2)),
      h("td", null, sparkline(p.spark))));
  }
  const n = pos.filter(p => LIVE.has(p.source)).length;
  $("pos-note").textContent = tt("{rows} holding(s); {n} of {total} have a recent price. Average cost is weighted, fees included. A security held in two accounts appears twice.", { rows: rows.length, n, total: pos.length });
}

/* ---------------------------------------------------------------- allocation, wrappers */
const ALLOC = [["holding", N_("Holding")], ["account", N_("Account")], ["type", N_("Type")], ["currency", N_("Currency")]];
function renderAlloc(d) {
  const seg = $("alloc-by"); clear(seg);
  for (const [k, l] of ALLOC) seg.append(h("button", { "aria-pressed": S.alloc === k, onclick: () => { S.alloc = k; renderAlloc(d); } }, tt(l)));
  const { pos, accts } = view(), m = new Map(), add = (k, v) => m.set(k, (m.get(k) || 0) + v);
  for (const p of pos) add(S.alloc === "holding" ? p.name.replace(/UCITS|ETF|\(.*?\)/gi, "").replace(/\s+/g, " ").trim().slice(0, 30) : S.alloc === "account" ? p.account : S.alloc === "type" ? p.category : p.ccy, p.value);
  const cash = accts.reduce((t, x) => t + x.cash, 0); if (cash > 0) add(tt("Cash"), cash);
  let items = [...m].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value);
  if (items.length > 9) { const rest = items.slice(8).reduce((t, x) => t + x.value, 0); items = [...items.slice(0, 8), { label: tt("Other holdings"), value: rest }]; }
  const total = items.reduce((t, x) => t + x.value, 0), el = $("alloc"); clear(el);
  if (!total) { el.append(h("p", { class: "muted" }, "—")); return; }
  const col = i => css(COLORS[i % COLORS.length]);
  el.append(h("div", { class: "stack", role: "img", "aria-label": tt("Allocation bar") }, items.map((x, i) => h("i", { style: `width:${x.value / total * 100}%;background:${col(i)}`, title: tt("{label}: {value}", { label: x.label, value: num(x.value / total * 100, 1) + PC }) }))));
  for (const [i, x] of items.entries()) el.append(h("div", { class: "alloc-row" }, h("i", { style: "background:" + col(i) }), h("span", null, x.label), h("span", null, eur(x.value)), h("b", null, num(x.value / total * 100, 1) + PC)));
}
function renderEnv(d) {
  const el = $("env"); clear(el);
  const p = d.envelopes && d.envelopes.pea;
  if (p && (S.acct === "all" || S.acct === "fortuneo")) {
    const left = Math.round((new Date(p.five_years) - new Date(d.as_of)) / 864e5 / 30.44), yrs = Math.floor(left / 12), mo = left % 12;
    const eta = left > 0 ? " " + tt("(in {duration})", { duration: [yrs ? plural(yrs, "{n} year", "{n} years") : "", mo ? plural(mo, "{n} month", "{n} months") : ""].filter(Boolean).join(" " + tt("and") + " ") }) : "";
    el.append(h("div", { class: "gauge" },
      h("div", { class: "t" }, h("span", null, tt("PEA: deposit ceiling")), h("b", null, eur(p.invested) + " / " + eur(p.cap))),
      h("div", { class: "track", role: "img", "aria-label": tt("{pct} of ceiling used", { pct: num(p.pct * 100, 1) + PC }) }, h("div", { class: "fill", style: `width:${Math.max(0.5, p.pct * 100)}%` })),
      h("div", { class: "muted small" }, tt("{pct} used, {room} of room left. Opened on {opened}: five years reached on {five}{eta}.",
        { pct: num(p.pct * 100, 1) + PC, room: eur(p.cap - p.invested), opened: longDate(p.opened), five: longDate(p.five_years), eta }))));
  }
  const w = $("watch"); clear(w);
  const items = S.acct === "all" ? d.watch : d.watch.filter(x => x.kind !== "cash");
  if (!items.length) w.append(h("li", { class: "muted" }, tt("Nothing in particular to flag on the current figures.")));
  for (const x of items) w.append(h("li", null, x.text));
}

/* ---------------------------------------------------------------- dividends, lists */
function renderDiv(d) {
  const el = $("chart-div"); clear(el);
  const m = d.dividend_months.slice(-24);
  $("div-total").textContent = tt("{amount} received since inception", { amount: eur(d.kpi.dividends, 2) });
  if (!m.length) { el.append(h("p", { class: "muted" }, tt("No dividends in the uploaded files."))); return; }
  const W = 520, H = 190, L = 34, B = 22, T = 6, max = niceMax(Math.max(...m.map(x => x[1]), 1)), bw = (W - L) / m.length;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": tt("Dividends received per month") });
  for (let i = 0; i <= 2; i++) { const y = T + (H - T - B) * (1 - i / 2); svg.append(s("line", { x1: L, x2: W, y1: y, y2: y, stroke: css("--rule2") }), s("text", { x: L - 6, y: y + 4, "text-anchor": "end", fill: css("--muted"), "font-size": 10.5 }, Math.round(max * i / 2) + " €")); }
  m.forEach(([mo, v], i) => {
    const hgt = Math.max(1, (H - T - B) * v / max), r = s("rect", { x: L + i * bw + 2, y: H - B - hgt, width: Math.max(2, bw - 4), height: hgt, rx: 1.5, fill: css("--c2") });
    r.addEventListener("pointermove", ev => showTip(ev, [mo, h("b", null, eur(v, 2))])); r.addEventListener("pointerleave", hideTip); svg.append(r);
    if (i % Math.ceil(m.length / 6) === 0) svg.append(s("text", { x: L + i * bw, y: H - 6, fill: css("--muted"), "font-size": 10.5 }, mo.slice(2).replace("-", "/")));
  });
  el.append(svg);
}
function renderLists(d) {
  const f = $("flows"); clear(f);
  for (const x of d.flows) f.append(h("div", { class: "row" }, h("span", null, longDate(x.date), h("span", { class: "muted" }, " · " + x.account)), h("b", { class: cls(x.eur) }, sgnEur(x.eur, 2))));
  if (!d.flows.length) f.append(h("p", { class: "muted" }, "—"));
  const v = $("divlist"); clear(v);
  for (const x of d.dividend_list.slice(0, 8)) v.append(h("div", { class: "row" }, h("span", null, longDate(x.date), h("span", { class: "muted" }, " · " + x.name.slice(0, 26))), h("b", { class: cls(x.eur) }, sgnEur(x.eur, 2))));
}

/* ---------------------------------------------------------------- data, import */
const KINDS = { degiro_transactions: N_("DEGIRO · transactions"), degiro_account: N_("DEGIRO · account"), degiro_portfolio: N_("DEGIRO · portfolio"), fortuneo_ops: N_("Fortuneo · operations"), fortuneo_cash: N_("Fortuneo · account"), foliolib_csv: "FolioLib CSV" };
const kindName = kind => KINDS[kind] ? tt(KINDS[kind]) : kind;
function renderData(d) {
  const f = $("files"); clear(f);
  for (const x of d.files) f.append(h("div", { class: "row" }, h("span", null, x.name, h("span", { class: "muted" }, " · " + kindName(x.kind))), h("b", null, tt("{new} new out of {total}", { new: x.new, total: x.n }))));
  const u = $("unmapped"); clear(u);
  for (const label of d.unmapped) {
    const inp = h("input", { maxlength: 12, placeholder: "ISIN", "aria-label": tt("ISIN of {name}", { name: label }) });
    u.append(h("div", { class: "alias" }, h("span", null, tt("\"{name}\" (Fortuneo): which ISIN?", { name: label })), inp, h("button", { class: "btn", onclick: async () => { const r = await api("/api/alias", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ label, isin: inp.value }) }); if (r.error) $("upmsg").textContent = r.error; else poll(); } }, tt("Map"))));
  }
}
async function upload(files) {
  const msg = $("upmsg"); msg.textContent = ""; msg.style.whiteSpace = "pre-line";
  for (const f of files) {
    if (f.size > 8 * 1024 * 1024) { msg.textContent += tt("{name}: file too large.", { name: f.name }) + "\n"; continue; }
    const r = await api("/api/upload", { method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Filename": encodeURIComponent(f.name) }, body: await f.arrayBuffer() });
    msg.textContent += (r.error ? tt("{name}: {error}", { name: f.name, error: r.error }) : tt("{name}: {kind}, {new} new line(s) out of {total}.", { name: f.name, kind: kindName(r.kind), new: r.new, total: r.lines })) + "\n";
  }
  await load(); poll();
}
let polling = false;
async function poll() {
  if (polling) return; polling = true;
  const b = $("btn-refresh"), chip = $("fresh");
  try {
    for (let i = 0; i < 600; i++) {
      const st = await api("/api/status"); b.disabled = st.running;
      if (st.running) { clear(chip); chip.append(h("span", { class: "spin" }), st.step || "…"); chip.className = "fresh"; } else { await load(); return; }
      await new Promise(r => setTimeout(r, 1500));
    }
  } finally { polling = false; b.disabled = false; }
}

/* ---------------------------------------------------------------- long-term projection */
const SIM_DEF = { capital: null, monthly: null, ret: 6, fees: 0.3, infl: 2, years: 20, real: false };
const SIM_LIM = { monthly: [0, 3000, 10], ret: [0, 12, 0.1], fees: [0, 3, 0.05], infl: [0, 6, 0.1], years: [1, 50, 1] };
const SIM_LAB = { monthly: [N_("Monthly deposit"), v => eur(v)], ret: [N_("Annual return"), v => num(v, 1) + PC], fees: [N_("Annual fees"), v => num(v, 2) + PC], infl: [N_("Inflation"), v => num(v, 1) + PC], years: [N_("Duration"), v => plural(v, "{n} year", "{n} years")] };
function simRun(p, retPts) {
  const net = Math.max(-0.99, (p.ret + retPts - p.fees) / 100), m = Math.pow(1 + net, 1 / 12) - 1, n = p.years * 12;
  const cap = [p.capital], dep = [p.capital];
  for (let i = 1; i <= n; i++) { cap.push(cap[i - 1] * (1 + m) + p.monthly); dep.push(dep[i - 1] + p.monthly); }
  return { cap, dep };
}
function renderSim(d) {
  const box = $("sim"); if (!box) return;
  $("sim-block").hidden = !!d.empty || !d.kpi;
  if (d.empty || !d.kpi) return;
  if (!S.sim) {
    let saved = {}; try { saved = JSON.parse(localStorage.getItem("sim") || "{}"); } catch (e) { saved = {}; }
    S.sim = { ...SIM_DEF, ...saved, edited: !!saved.edited };
  }
  const p = S.sim, k = d.kpi, dep = d.series && d.series.deposits || [], dd = d.series && d.series.days || [];
  if (!p.edited || p.capital == null) p.capital = Math.round(k.value);
  if (p.monthly == null) {
    const last = dep.length - 1, i = Math.max(0, last - 365);   /* average deposits over the last year */
    const months = Math.max(1, (Date.parse(dd[last]) - Date.parse(dd[i])) / 2.63e9);
    p.monthly = last > 0 ? Math.max(0, Math.round((dep[last] - dep[i]) / months / 10) * 10) : 200;
  }
  if (!box.firstChild) buildSim(box, d);
  updateSim();
}
function saveSim() { try { localStorage.setItem("sim", JSON.stringify(S.sim)); } catch (e) { /* storage unavailable: no effect */ } }
function buildSim(box, d) {
  const p = S.sim, ctl = h("div", { class: "sim-ctl" });
  const cap = h("input", { id: "sim-capital", type: "number", min: 0, step: 100, inputmode: "numeric", value: p.capital });
  cap.addEventListener("input", () => { p.capital = Math.max(0, Number(cap.value) || 0); p.edited = true; saveSim(); updateSim(); });
  ctl.append(h("div", { class: "sim-row" }, h("label", { for: "sim-capital" }, tt("Starting capital (€)")), cap,
    h("small", { class: "muted" }, tt("Default: your total value today ({amount}).", { amount: eur(d.kpi.value) }))));
  for (const key of Object.keys(SIM_LIM)) {
    const [lo, hi, st] = SIM_LIM[key], [lab, f] = SIM_LAB[key], out = h("output", { id: "sim-o-" + key, for: "sim-" + key });
    const r = h("input", { id: "sim-" + key, type: "range", min: lo, max: hi, step: st, value: p[key] });
    r.addEventListener("input", () => { p[key] = Number(r.value); saveSim(); updateSim(); });
    ctl.append(h("div", { class: "sim-row" }, h("label", { for: "sim-" + key }, tt(lab), key === "ret" ? info("simrate") : null), out, r));
  }
  const real = h("input", { id: "sim-real", type: "checkbox" });
  real.checked = !!p.real;
  real.addEventListener("change", () => { p.real = real.checked; saveSim(); updateSim(); });
  ctl.append(h("label", { class: "sim-check", for: "sim-real" }, real, tt("Amounts in today's euros"), info("simreal")),
    h("button", { class: "btn quiet", type: "button", onclick: () => { S.sim = { ...SIM_DEF, capital: null, monthly: null }; saveSim(); clear(box); renderSim(S.data); } }, tt("Reset")));
  box.append(ctl, h("div", { class: "sim-out" }, h("dl", { id: "sim-tiles", class: "tiles" }), h("div", { id: "sim-chart", class: "chart" }), h("div", { id: "sim-legend", class: "legend" })));
}
function updateSim() {
  const p = S.sim;
  for (const key of Object.keys(SIM_LIM)) { const o = $("sim-o-" + key), r = $("sim-" + key); if (o) { o.textContent = SIM_LAB[key][1](p[key]); r.setAttribute("aria-valuetext", o.textContent); r.value = p[key]; } }
  const mid = simRun(p, 0), low = simRun(p, -2), high = simRun(p, 2), n = p.years * 12;
  const defl = i => p.real ? Math.pow(1 + p.infl / 100, -i / 12) : 1;
  const end = mid.cap[n] * defl(n), put = mid.dep[n];
  const tiles = $("sim-tiles"); clear(tiles);
  tiles.append(tile(plural(p.years, "Capital in {n} year", "Capital in {n} years"), "sim", eur(end), p.real ? tt("in today's euros") : tt("in current euros, before tax")),
    tile(tt("Of which paid in by you"), "sim", eur(put), tt("{capital} at the start + {monthly} a month", { capital: eur(p.capital), monthly: eur(p.monthly) })),
    tile(tt("Simulated gain"), "sim", sgnEur(end - put), (put > 0 ? tt("{pct} more than you will have paid in", { pct: num((end / put - 1) * 100, 0) + PC }) : ""), cls(end - put)),
    tile(tt("Monthly income at 4%"), "simrent", eur(end * 0.04 / 12), tt("order of magnitude, before tax")));
  const days = mid.cap.map((_, i) => i);
  const yl = (i, short) => short ? plural(i / 12 | 0, "{n} year", "{n} years") : tt("Month {month} (year {year})", { month: i, year: Math.ceil(i / 12) || 0 });
  const sc = (x, k) => x.cap.map((v, i) => v * defl(i));
  const chart = $("sim-chart"); clear(chart);
  const series = [{ name: tt("Cumulative deposits"), v: mid.dep, color: css("--c10"), w: 1.8, dash: "2 4" },
    { name: tt("Return −2 pts"), v: sc(low), color: css("--c7"), w: 1.6, dash: "6 4" },
    { name: tt("Central scenario"), v: sc(mid), color: css("--c1"), w: 2.6, area: true },
    { name: tt("Return +2 pts"), v: sc(high), color: css("--c2"), w: 1.6, dash: "6 4" }];
  lineChart(chart, days, series, { zero: true, xLabel: yl, label: tt("Capital projection over {n} years: central, cautious and favorable scenarios, and cumulative deposits", { n: p.years }) });
  const lg = $("sim-legend"); clear(lg);
  for (const x of series) lg.append(h("span", null, h("i", { style: "border-color:" + x.color }), tt("{label}: ", { label: x.name }), h("b", null, eur(x.v[n]))));
}

/* ---------------------------------------------------------------- startup */
$("btn-refresh").addEventListener("click", async () => { await api("/api/refresh", { method: "POST" }); poll(); });
$("btn-import").addEventListener("click", () => $("file").click());
$("file").addEventListener("change", e => upload([...e.target.files]));
const drop = $("drop");
drop.addEventListener("click", () => $("file").click());
drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } });
for (const t of ["dragenter", "dragover"]) drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); });
for (const t of ["dragleave", "drop"]) drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); });
drop.addEventListener("drop", e => upload([...e.dataTransfer.files]));
$("q").addEventListener("input", e => { S.q = e.target.value; renderTable(S.data); });
$("btn-wipe").addEventListener("click", async () => { if (confirm(tt("Erase all imported operations?"))) { await api("/api/wipe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirm: "WIPE" }) }); load(); } });
(async function boot() {
  /* The messages of the language are fetched first, so that nothing is ever drawn in English and then redrawn. */
  if (LANG !== "en") { try { CATALOG = (await api("/api/i18n")).messages || {}; } catch (e) { if (e.message === "auth") return; } }
  translateStatic(); renderLangSwitch();
  await load();
  if (!S.data.empty) api("/api/refresh", { method: "POST" }).then(poll);
})();

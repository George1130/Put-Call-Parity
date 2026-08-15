/* Put-Call Parity web UI — talks to the Flask API (app.py). */
"use strict";

const $ = (id) => document.getElementById(id);
const money2 = (x) => "$" + Number(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const money4 = (x) => "$" + Number(x).toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 4 });

const inputs = ["S", "K", "r", "T", "C", "P"];
const pvD = { current: 0.0 }; // set when a live chain row is loaded

/* ---------------- manual analysis ---------------- */

function readInputs() {
  const v = {};
  for (const k of inputs) {
    v[k] = parseFloat($(k).value);
    if (!isFinite(v[k])) return null;
  }
  if (!(v.S > 0 && v.K > 0 && v.T > 0 && v.C >= 0 && v.P >= 0)) return null;
  return v;
}

let analyzeTimer = null;
function scheduleAnalyze() {
  clearTimeout(analyzeTimer);
  analyzeTimer = setTimeout(analyze, 250);
}

async function analyze() {
  const v = readInputs();
  if (!v) { clearResults(); return; }
  $("days-note").textContent = "≈ " + (v.T * 365).toFixed(2) + " days to expiry";
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...v, pv_d: pvD.current }),
    });
    const data = await res.json();
    if (!res.ok) { clearResults(data.error); return; }
    renderResults(data);
  } catch (e) {
    clearResults("Request failed: " + e);
  }
  refreshChart();
}

function clearResults(msg) {
  for (const id of ["st-pvk", "st-rt", "st-left", "st-right", "st-fairp", "st-fairc"]) $(id).textContent = "—";
  $("verdict").className = "verdict";
  $("verdict").textContent = msg || "Enter valid inputs (S, K, T > 0; C, P ≥ 0).";
  $("trade").textContent = "";
}

function renderResults(res) {
  $("st-pvk").textContent = money4(res["PV(K)"]);
  $("st-rt").textContent = Number(res.rT).toFixed(6);
  $("st-left").textContent = money2(res.left);
  $("st-right").textContent = money2(res.right);

  const fp = $("st-fairp"), fc = $("st-fairc");
  fp.textContent = `${money2(res.fair_p)}  (mkt ${money2(res.P)})`;
  fc.textContent = `${money2(res.fair_c)}  (mkt ${money2(res.C)})`;
  fp.style.color = Math.abs(res.P - res.fair_p) <= res.tolerance ? "var(--green)" : "var(--red)";
  fc.style.color = Math.abs(res.C - res.fair_c) <= res.tolerance ? "var(--green)" : "var(--red)";

  const verdict = $("verdict");
  const hasDiv = pvD.current > 1e-9;
  const suffix = hasDiv ? `\nDividend adjustment PV(D) = ${money2(pvD.current)}` : "";
  let tradeHtml = "";

  if (res.status === "parity") {
    verdict.className = "verdict green";
    verdict.textContent =
      `PARITY HOLDS  |  |LEFT - RIGHT| = ${money2(res.abs_diff)} <= tolerance ${money2(res.tolerance)}` +
      `\nNo arbitrage. Both sides ~ ${money2((res.left + res.right) / 2)}.` + suffix;
    tradeHtml = "No trade: market prices already satisfy parity within tolerance.";
  } else {
    const leftRich = res.status === "arb_left_rich";
    verdict.className = "verdict red";
    if (leftRich) {
      verdict.textContent =
        `ARBITRAGE  |  C + PV(K) = ${money2(res.left)} is ${money2(res.abs_diff)} richer than P + S = ${money2(res.right)}` +
        `\nCall is ${((res.C / Math.max(res.fair_c, 1e-12)) - 1) * 100}% overpriced (${money2(res.C)} vs fair ${money2(res.fair_c)}). Sell rich, buy cheap.` + suffix;
    } else {
      verdict.textContent =
        `ARBITRAGE  |  P + S = ${money2(res.right)} is ${money2(res.abs_diff)} richer than C + PV(K) = ${money2(res.left)}` +
        `\nPut is ${((res.P / Math.max(res.fair_p, 1e-12)) - 1) * 100}% overpriced (${money2(res.P)} vs fair ${money2(res.fair_p)}). Sell rich, buy cheap.` + suffix;
    }
    tradeHtml = tradeTable(res);
  }
  $("trade").innerHTML = tradeHtml;
}

function tradeTable(res) {
  if (!res.trade) return "";
  let head = res.trade.direction;
  if (pvD.current > 1e-9) head = head.replace("PV(K)", "PV(K)+PV(D)");
  let total = 0, html = "";
  const sign = (x) => (x >= 0 ? "+" : "−");
  const cls = (x) => (x >= 0 ? "green" : "red");
  for (const [leg, cf] of res.trade.legs) {
    total += cf;
    html += `  <span style="color:${cls(cf)}">${sign(cf)}${money2(Math.abs(cf)).padStart(12)}</span>  ${leg}\n`;
  }
  html += `  <span style="color:var(--accent)">+${money2(total).padStart(12)}</span>  Net cash now (riskless profit today)\n`;
  html += `  <span style="color:var(--muted)">${money2(res.profit_expiry).padStart(13)}</span>  Value at expiry, any S_T\n`;
  html += `  Per contract (x100): ${money2(res.profit * 100)}`;
  return `<b>${head}</b>\n` + html;
}

function refreshChart() {
  const v = readInputs();
  if (!v) { $("chart").style.visibility = "hidden"; return; }
  const qs = new URLSearchParams({ ...v, pv_d: pvD.current });
  $("chart").src = "/api/chart?" + qs.toString();
  $("chart").style.visibility = "visible";
}

/* ---------------- buttons ---------------- */

$("example-btn").onclick = () => {
  const ex = { S: "100.00", K: "100.00", r: "5.00", T: "0.5", C: "8.00", P: "5.00" };
  for (const k of Object.keys(ex)) $(k).value = ex[k];
  pvD.current = 0;
  analyze(); refreshChart();
};

function fairP() {
  const v = readInputs(); if (!v) return;
  const pvk = v.K * Math.exp((-v.r / 100) * v.T);
  $("P").value = (v.C + pvk + pvD.current - v.S).toFixed(4);
  analyze(); refreshChart();
}
function fairC() {
  const v = readInputs(); if (!v) return;
  const pvk = v.K * Math.exp((-v.r / 100) * v.T);
  $("C").value = (v.P + v.S - pvk - pvD.current).toFixed(4);
  analyze(); refreshChart();
}
$("fair-p-btn").onclick = fairP;
$("fair-c-btn").onclick = fairC;

/* ---------------- live data ---------------- */

const ticker = $("ticker"), expirySel = $("expiry"), statusEl = $("live-status");
let liveSurface = null;

function setStatus(text, color) {
  statusEl.textContent = text;
  statusEl.style.color = color || "var(--muted)";
}

$("fetch-btn").onclick = async () => {
  const tk = ticker.value.trim();
  if (!tk) return;
  setStatus(`Fetching ${tk} ...`, "var(--yellow)");
  expirySel.disabled = true;
  expirySel.innerHTML = "<option>—</option>";
  try {
    const r = await fetch(`/api/expirations?ticker=${encodeURIComponent(tk)}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    expirySel.innerHTML = d.expirations.map((e) => `<option>${e}</option>`).join("");
    expirySel.disabled = false;
    setStatus(`${d.expirations.length} expirations for ${d.ticker}`);
    await fetchSurface(tk, d.expirations[0]);
  } catch (e) {
    setStatus("Error: " + e.message, "var(--red)");
  }
};

expirySel.onchange = () => {
  const tk = ticker.value.trim();
  if (tk && expirySel.value && expirySel.value !== "—") fetchSurface(tk, expirySel.value);
};

async function fetchSurface(tk, expiry) {
  setStatus(`Fetching ${expiry} chain ...`, "var(--yellow)");
  const useDiv = $("use-dividends").checked ? "1" : "0";
  try {
    const r = await fetch(
      `/api/live?ticker=${encodeURIComponent(tk)}&expiry=${encodeURIComponent(expiry)}&dividends=${useDiv}`);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.status);
    liveSurface = d;
    renderChain(d);
    const best = bestRow(d);
    if (best) loadRow(d, best);
  } catch (e) {
    setStatus("Error: " + e.message, "var(--red)");
  }
}

function bestRow(d) {
  const tr = d.rows.filter((r) => r.tradeable != null && r.tradeable > 0);
  let best;
  if (tr.length) best = tr.reduce((a, b) => (b.tradeable > a.tradeable ? b : a));
  else best = d.rows.reduce((a, b) => (Math.abs(b.strike - d.spot) < Math.abs(a.strike - d.spot) ? b : a), d.rows[0]);
  return best;
}

function renderChain(d) {
  const div = d.dividend || {};
  const dnote = !div.pays ? "no dividends"
    : `${div.freq_days.toFixed(0)}-day div $${Number(div.amount).toFixed(2)}/sh, ${div.dates.length} before expiry, PV(D)=${money2(div.pv)}`;
  const tr = d.rows.filter((r) => r.tradeable != null && r.tradeable > 0);
  const note = !tr.length
    ? " | no tradeable arbitrage (NET <= 0 on every fully-quoted strike)"
    : ` | BEST tradeable: K=${tr[0].strike.toFixed(2)}, NET ${tr[0].tradeable >= 0 ? "+" : ""}${tr[0].tradeable.toFixed(3)}/share`;
  setStatus(
    `${d.ticker}  |  spot ${d.currency} ${Number(d.spot).toFixed(2)} (bid ${Number(d.spot_bid).toFixed(2)}/ask ${Number(d.spot_ask).toFixed(2)})  |  ` +
    `r ${(d.rf * 100).toFixed(2)}% (${d.rf_source})  |  ${d.expiry} -> ${d.days}d  |  ${dnote}${note}`);

  const tbody = document.querySelector("#chain-table tbody");
  tbody.innerHTML = "";
  const rows = d.rows.slice().sort((a, b) => a.strike - b.strike);
  for (const r of rows) {
    const res = r.res;
    const qual = { full: "2sided", partial: "1sided", stale: "stale" }[r.qflag] || r.qflag;
    const net = r.tradeable != null ? (r.tradeable >= 0 ? "+" : "") + r.tradeable.toFixed(3) : "—";
    let cls = "stale";
    if (res.status !== "parity" && r.qflag === "full") cls = "viol";
    else if (res.status === "parity") cls = "ok";
    const trEl = document.createElement("tr");
    trEl.className = cls;
    trEl.dataset.strike = r.strike;
    trEl.innerHTML =
      `<td>${r.strike.toFixed(2)}</td><td>${money2(r.call_mid)}</td><td>${money2(r.put_mid)}</td>` +
      `<td>${money2(res.fair_c)}</td><td>${money2(res.fair_p)}</td>` +
      `<td>${res.abs_diff >= 0 ? "+" : ""}${res.abs_diff.toFixed(3)}</td><td>${net}</td>` +
      `<td>${r.call_oi}/${r.put_oi}</td><td>${qual}</td>`;
    tbody.appendChild(trEl);
  }
  // highlight the best row
  const best = bestRow(d);
  if (best) {
    const el = tbody.querySelector(`tr[data-strike="${best.strike}"]`);
    if (el) el.classList.add("best");
  }
}

$("chain-table").addEventListener("click", (e) => {
  const trEl = e.target.closest("tr[data-strike]");
  if (!trEl || !liveSurface) return;
  const strike = parseFloat(trEl.dataset.strike);
  const row = liveSurface.rows.find((r) => Math.abs(r.strike - strike) < 1e-6);
  if (row) loadRow(liveSurface, row);
});

function loadRow(d, row) {
  $("S").value = Number(d.spot).toFixed(2);
  $("K").value = row.strike.toFixed(2);
  $("r").value = (d.rf * 100).toFixed(4);
  $("T").value = Number(d.T).toFixed(6);
  $("C").value = row.call_mid.toFixed(2);
  $("P").value = row.put_mid.toFixed(2);
  pvD.current = Number(d.pv_d) || 0;
  analyze(); refreshChart();
  document.querySelectorAll("#chain-table tbody tr").forEach((el) => el.classList.remove("selected"));
  const sel = document.querySelector(`#chain-table tbody tr[data-strike="${row.strike}"]`);
  if (sel) sel.classList.add("selected");
}

/* ---------------- boot ---------------- */

for (const id of inputs) $(id).addEventListener("input", scheduleAnalyze);
$("use-dividends").addEventListener("change", () => {
  const tk = ticker.value.trim();
  if (tk && expirySel.value && expirySel.value !== "—") fetchSurface(tk, expirySel.value);
});

analyze();
refreshChart();

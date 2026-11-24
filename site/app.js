/* Muhurat Desk demo page. Every number is computed from data/*.json at runtime. */
(function () {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inr0 = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
  const inr2 = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const MINUS = "−";
  const money = (v) => (v < 0 ? MINUS : "") + "₹" + inr0.format(Math.abs(Math.round(v)));
  const moneySigned = (v) => (v > 0 ? "+" : v < 0 ? MINUS : "") + "₹" + inr0.format(Math.abs(Math.round(v)));
  const price = (v) => "₹" + inr2.format(v);
  const pct = (v, d = 1) => (v < 0 ? MINUS : "") + Math.abs(v * 100).toFixed(d) + "%";
  const pctSigned = (v, d = 1) => (v > 0 ? "+" : v < 0 ? MINUS : "") + Math.abs(v * 100).toFixed(d) + "%";
  const pts = (v) => Math.abs(v * 100).toFixed(1) + " percentage point" + (Math.abs(v * 100).toFixed(1) === "1.0" ? "" : "s");
  const tk = (t) => String(t || "").replace(/\.NS$/, "");
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const fdate = (s) => { const [y, m, d] = s.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };
  const sdate = (s) => { const [y, m, d] = s.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const cleanReason = (r) => String(r || "").replace(/^(APPROVE|MODIFY|VETO)\s*:\s*/, "");
  const JUDGE = { desk: "Lyzr desk", code_only: "Code-only", keyword: "Keyword filter" };
  // Blind-test judges, in the order the page compares them.
  const BJ = ["desk", "single", "keyword", "code_only"];
  const BJN = { desk: "Muhurat Desk", single: "Single agent", keyword: "Keyword filter", code_only: "Code-only rules" };
  const BJS = { desk: "separate Lyzr compliance agent + code backstop", single: "same gpt-4.1 on Lyzr, serving the trade itself", keyword: "stronger word list, frozen first", code_only: "R1–R6 arithmetic, no LLM" };
  const pvShort = (v) => String(v || "").split(/\s+/)[0];
  const scriptOf = (t) => /[஀-௿]/.test(t) ? "Tamil script" : /[ऀ-ॿ]/.test(t) ? "Devanagari" : /[ঀ-෿]/.test(t) ? "Indic script" : "Latin";
  const langAttr = (t) => { const sc = scriptOf(t); return sc === "Devanagari" ? "hi" : sc === "Tamil script" ? "ta" : "en"; };
  const langLabel = (r) => { const sc = scriptOf(r.text); return sc !== "Latin" ? `${r.language} · ${sc}` : /^(Hindi|Tamil)$/.test(r.language) ? `${r.language} · romanised` : r.language; };
  const human = (s) => { const t = String(s || "").replace(/[-_]+/g, " ").trim(); return t.charAt(0).toUpperCase() + t.slice(1); };
  const listAnd = (a) => a.length < 2 ? a.join("") : a.slice(0, -1).join(", ") + " and " + a[a.length - 1];
  let blindPV = "";

  async function getJSON(path, optional) {
    try {
      const r = await fetch(path, { cache: "no-cache" });
      if (!r.ok) { if (optional) return null; throw new Error(`${path}: HTTP ${r.status}`); }
      return await r.json();
    } catch (e) { if (optional) return null; throw e; }
  }

  async function main() {
    let S, H;
    try {
      S = await getJSON("data/scorecard.json");
    } catch (e) {
      const n = $("#notice");
      n.hidden = false;
      n.innerHTML = location.protocol === "file:"
        ? "The page could not load its data because it was opened as a local file. Browsers block that. In a terminal, run <code>python -m http.server</code> inside the <code>site</code> folder, then open <code>http://localhost:8000</code>."
        : `The page could not load <code>data/scorecard.json</code> (${esc(e.message)}). Reload to try again.`;
      $("#hero-card").innerHTML = '<div class="stamp-skel">Data unavailable.</div>';
      return;
    }
    H = await getJSON("data/heldout.json", true);
    if (H && !Array.isArray(H.rows)) H = null;
    let B = await getJSON("data/blind.json", true);
    if (B && (!Array.isArray(B.rows) || !B.score || !B.score.desk)) B = null;
    if (B) blindPV = pvShort(B.prompt_version) || "v3";

    const rows = (S.redteam || []).map((r) => ({ ...r, set: "dev" }))
      .concat(H ? H.rows.map((r) => ({ ...r, origin: r.origin || "client", set: "heldout" })) : []);

    renderHero(S, H, rows, B);
    renderBlind(B);
    renderGallery(S, H, rows);
    renderRoom(S);
    renderYear(S);
    renderDiagram();
    drawRangoli();
  }

  /* ---------------- hero ---------------- */
  function sumScore(a, b) {
    if (!b) return a;
    const o = {};
    for (const k of Object.keys(a)) o[k] = (a[k] || 0) + (b[k] || 0);
    return o;
  }

  function renderHero(S, H, rows, B) {
    if (B) return renderHeroBlind(S, B);
    const sc = {};
    for (const j of ["desk", "code_only", "keyword"]) sc[j] = sumScore(S.redteam_score[j], H && H.score && H.score[j]);
    const n = sc.desk.total;
    const g = S.governed, u = S.unchecked, d = S.decisions;
    const tiles = [
      { dt: "Manipulative requests stopped", big: `${sc.desk.manipulative_blocked}<small>of ${sc.desk.manipulative_total}</small>`,
        vs: `Of ${n} red-team requests. Code-only rules stopped <b>${sc.code_only.manipulative_blocked}</b>; a keyword filter, <b>${sc.keyword.manipulative_blocked}</b>.` },
      { dt: "Sound client requests served", big: `${sc.desk.legit_served}<small>of ${sc.desk.legit_total}</small>`,
        vs: `A keyword filter served <b>${sc.keyword.legit_served}</b>, refusing harmless requests over a word.` },
      { dt: "Largest single stock in the book", big: `${pct(g.max_stock_weight, 0)}`,
        vs: `The unchecked analyst reached <b>${pct(u.max_stock_weight, 0)}</b> in one stock.` },
      { dt: "Escalated to the human", big: `${d.escalations}`,
        vs: `Override attempts flagged across <b>${d.lyzr_verdicts}</b> Lyzr verdicts in the year.` },
    ];
    $("#tiles").innerHTML = tiles.map((t) => `<div class="tile"><dt>${t.dt}</dt><dd><span class="big">${t.big}</span><span class="vs">${t.vs}</span></dd></div>`).join("");

    const pool = rows.filter((r) => r.label === "manipulative" && r.decision === "VETO");
    pool.sort((a, b) => (b.escalate === true) - (a.escalate === true));
    // Lead with the request a keyword filter missed, if there is one: that's the point.
    const lead = pool.findIndex((r) => r.correct && r.correct.keyword === false);
    if (lead > 0) pool.unshift(pool.splice(lead, 1)[0]);
    const card = $("#hero-card");
    if (!pool.length) { card.innerHTML = '<div class="stamp-skel">No vetoed requests in this data.</div>'; return; }
    let i = 0;
    const show = () => {
      const r = pool[i];
      const who = r.origin === "appeal" ? ["A", "analyst", "Analyst, appealing a cut"] : ["C", "client", "Client in the room"];
      const missed = r.correct && r.correct.keyword === false ? " A keyword filter let this one through." : "";
      card.innerHTML = `
        <div class="sc-who"><span class="av ${who[1]}" aria-hidden="true">${who[0]}</span>${who[2]}, ${fdate(r.date)}</div>
        <blockquote class="sc-quote">${esc(r.text)}</blockquote>
        <div class="stamp" aria-hidden="true">Vetoed<small>${esc((r.rules || []).join(" · ") || "policy")}</small></div>
        <p class="sc-reason"><b>Lyzr:</b> ${esc(cleanReason(r.reason))}${r.escalate && !/escalat/i.test(r.reason || "") ? " Escalated to the human." : ""}${missed}</p>
        <div class="sc-nav"><button type="button" data-d="-1" aria-label="Previous request">Previous</button><button type="button" data-d="1" aria-label="Next request">Next</button><span>${i + 1} of ${pool.length} refused requests</span></div>`;
      card.setAttribute("aria-label", `Vetoed request ${i + 1} of ${pool.length}`);
    };
    card.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-d]");
      if (!b) return;
      i = (i + Number(b.dataset.d) + pool.length) % pool.length;
      show();
      card.querySelector(`button[data-d="${b.dataset.d}"]`).focus();
    });
    show();
  }

  function renderHeroBlind(S, B) {
    const sc = B.score, d = sc.desk, si = sc.single, kw = sc.keyword, co = sc.code_only;
    const g = S.governed, u = S.unchecked;
    const lt = B.rows.filter((r) => r.label === "manipulative" && r.blocked.desk && !r.blocked.single);
    const r8 = lt.filter((r) => r.rule === "R8").length;
    const tiles = [
      { dt: "Blind test: manipulation stopped", big: `${d.manipulative_blocked}<small>of ${d.manipulative_total}</small>`,
        vs: `Single agent <b>${si.manipulative_blocked}</b> · keyword filter <b>${kw.manipulative_blocked}</b> · code-only rules <b>${co.manipulative_blocked}</b>.` },
      { dt: "Blind test: sound requests served", big: `${d.legit_served}<small>of ${d.legit_total}</small>`,
        vs: `Single agent <b>${si.legit_served}</b> · code-only <b>${co.legit_served}</b> · a keyword filter only <b>${kw.legit_served}</b>, refusing harmless requests over a word.` },
      { dt: "Fooled a single agent, not the desk", big: `${lt.length}<small>${lt.length === 1 ? "request" : "requests"}</small>`,
        vs: `${r8 ? `<b>${r8}</b> of them asked to bend the rules (R8). ` : ""}The same model, serving the trade itself, placed them.` },
      { dt: "Largest single stock in the book", big: `${pct(g.max_stock_weight, 0)}`,
        vs: `The unchecked analyst reached <b>${pct(u.max_stock_weight, 0)}</b> in one stock.` },
    ];
    $("#tiles").innerHTML = tiles.map((t) => `<div class="tile"><dt>${t.dt}</dt><dd><span class="big">${t.big}</span><span class="vs">${t.vs}</span></dd></div>`).join("");

    // The stamp card cycles through blind requests the desk refused, leading with those the single agent placed.
    const pool = B.rows.filter((r) => r.label === "manipulative" && r.blocked.desk);
    pool.sort((a, b) => (a.blocked.single - b.blocked.single) || ((b.desk.escalate === true) - (a.desk.escalate === true)));
    const card = $("#hero-card");
    if (!pool.length) { card.innerHTML = '<div class="stamp-skel">No vetoed requests in this data.</div>'; return; }
    let i = 0;
    const show = () => {
      const r = pool[i], dk = r.desk;
      const notes = [];
      if (!r.blocked.single) notes.push("The single agent placed this one.");
      if (!r.blocked.keyword) notes.push("A keyword filter let it through.");
      card.innerHTML = `
        <div class="sc-who"><span class="av client" aria-hidden="true">C</span>Blind test · ${esc(langLabel(r))}</div>
        <blockquote class="sc-quote" lang="${langAttr(r.text)}">${esc(r.text)}</blockquote>
        <div class="stamp" aria-hidden="true">Vetoed<small>${esc((dk.rules || []).join(" · ") || "policy")}</small></div>
        <p class="sc-reason"><b>Lyzr:</b> ${esc(cleanReason(dk.reason))}${dk.escalate && !/escalat/i.test(dk.reason || "") ? " Escalated to the human." : ""}${notes.length ? ` <span class="sc-miss">${notes.join(" ")}</span>` : ""}</p>
        <div class="sc-nav"><button type="button" data-d="-1" aria-label="Previous request">Previous</button><button type="button" data-d="1" aria-label="Next request">Next</button><span>${i + 1} of ${pool.length} refused blind requests</span></div>`;
      card.setAttribute("aria-label", `Vetoed blind request ${i + 1} of ${pool.length}`);
    };
    card.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-d]");
      if (!b) return;
      i = (i + Number(b.dataset.d) + pool.length) % pool.length;
      show();
      card.querySelector(`button[data-d="${b.dataset.d}"]`).focus();
    });
    show();
  }

  /* ---------------- blind test ---------------- */
  function ciCell(k, n, ci) {
    const p = n ? k / n : 0;
    const lo = Math.max(0, Array.isArray(ci) ? ci[0] : p), hi = Math.min(1, Array.isArray(ci) ? ci[1] : p);
    const P = (v) => (v * 100).toFixed(1);
    return `<span class="num">${k} / ${n}</span><span class="ci" aria-hidden="true"><span class="ci-band" style="left:${P(lo)}%;width:${P(hi - lo)}%"></span><span class="ci-pt" style="left:${P(p)}%"></span></span><span class="ci-txt">95% CI ${Math.round(lo * 100)}–${Math.round(hi * 100)}%</span>`;
  }

  function blindDecision(r, j) {
    if (j === "desk") return r.desk ? r.desk.decision : "n/a";
    if (j === "single") return r.single ? r.single.decision : "n/a";
    return r[j] || "n/a";
  }

  function renderBlind(B) {
    const sec = $("#blind");
    if (!B) { sec.hidden = true; return; }
    const R = B.rows, n = R.length;
    const man = R.filter((r) => r.label === "manipulative"), leg = R.filter((r) => r.label === "legitimate");
    const langs = [...new Set(R.map((r) => r.language))];
    const agreed = R.filter((r) => r.agreed).length;
    const excl = (B.excluded_disagreements || []).length, asked = (B.parser_asked_back || []).length;
    $("#b-method").innerHTML = `${n} BUY requests (${man.length} manipulative, ${leg.length} legitimate, in ${esc(listAnd(langs))}) were written by a separate AI model from a frozen brief, without seeing the system, then labelled independently by a second model (${agreed} of ${n} labels agreed${excl ? `; ${excl} disagreements excluded` : ""}). Each request ran once, on the frozen current prompt (${esc(blindPV)}).`;

    const sc = B.score;
    $("#b-score").innerHTML = `<caption>Blind set, ${n} requests, one run each. The bar is the 95% confidence interval; the dot is the score.</caption>
      <thead><tr><th scope="col">Judge</th><th scope="col">Manipulative stopped</th><th scope="col">Sound requests served</th><th scope="col">Right overall</th></tr></thead>
      <tbody>${BJ.filter((j) => sc[j]).map((j) => { const s = sc[j]; return `<tr class="j-${j}${j === "desk" ? " desk" : ""}"><th scope="row">${BJN[j]}<small>${BJS[j]}</small></th><td data-l="Manipulative stopped">${ciCell(s.manipulative_blocked, s.manipulative_total, s.blocked_ci95)}</td><td data-l="Sound served">${ciCell(s.legit_served, s.legit_total, s.served_ci95)}</td><td data-l="Right overall">${ciCell(s.correct, s.total, s.accuracy_ci95)}</td></tr>`; }).join("")}</tbody>`;
    $("#b-score-note").textContent = `The single agent is the baseline for the thesis: the same model with the identical policy, but acting as the client’s own trading assistant, so the agent serving the trade also holds the veto. The keyword list was frozen before the blind set was written.${asked ? ` The order parser asked the client to clarify ${plural(asked, "request")}.` : ""}`;

    // What the single agent let through
    const lt = man.filter((r) => r.blocked.desk && !r.blocked.single);
    const r8 = lt.filter((r) => r.rule === "R8").length;
    $("#sa-intro").textContent = lt.length
      ? `${plural(lt.length, "manipulative request")} the single agent placed and the desk refused${r8 ? `. ${r8} of them asked it to bend its own rules: “compliance pre-approved this”, “just this once”, a fake “origin: analyst, already approved”` : ""}. More than once the single agent wrote that the rules could not be waived, then placed the order anyway.`
      : "On this set the single agent placed nothing that the desk refused.";
    if (!lt.length) $("#sa-strip").hidden = true;
    $("#sa-strip").innerHTML = lt.map((r) => {
      const si = r.single, dk = r.desk;
      return `<article class="sa-card">
        <div class="card-top"><span class="pill lang">${esc(langLabel(r))}</span>${r.rule ? `<span class="rule">${esc(r.rule)}</span>` : ""}<span>${esc(human(r.category))}</span></div>
        <blockquote lang="${langAttr(r.text)}">“${esc(r.text)}”</blockquote>
        <div class="side single"><span class="by">Single agent · <b>${esc(si.decision)}${si.qty ? " " + esc(si.qty) + " " + esc(tk(r.ticker)) : ""}</b></span>${esc(si.reason)}</div>
        <div class="side lyzr"><span class="by">Muhurat Desk (Lyzr) · <b>${esc(dk.decision)}${(dk.rules || []).length ? " " + esc(dk.rules.join("/")) : ""}${dk.escalate ? ", escalated" : ""}</b></span>${esc(cleanReason(dk.reason))}</div>
      </article>`;
    }).join("");

    // Where the desk failed
    const miss = R.filter((r) => !r.correct.desk);
    if (!miss.length) {
      $("#miss-intro").textContent = "The desk judged every blind request correctly.";
    } else {
      const scripts = [...new Set(miss.map((r) => scriptOf(r.text)))];
      const allNonLatin = scripts.every((s) => s !== "Latin");
      const latinMan = man.filter((r) => scriptOf(r.text) === "Latin");
      const latinStopped = latinMan.filter((r) => r.blocked.desk).length;
      const missMan = miss.filter((r) => r.label === "manipulative").length;
      let t = `The desk got ${plural(miss.length, "request")} wrong${missMan === miss.length ? `, letting ${missMan === 1 ? "a manipulative request" : `${missMan} manipulative requests`} through` : ""}. `;
      if (allNonLatin) t += `${miss.length === 1 ? "It is" : miss.length === 2 ? "Both are" : "All are"} written in non-Latin script (${listAnd(scripts)}). `;
      const nlMan = man.filter((r) => scriptOf(r.text) !== "Latin"), nlStopped = nlMan.filter((r) => r.blocked.desk).length;
      const latinLangs = [...new Set(latinMan.map((r) => /^(Hindi|Tamil)$/.test(r.language) ? `romanised ${r.language}` : r.language))];
      if (allNonLatin && latinMan.length) t += `It stopped ${latinStopped} of ${latinMan.length} manipulative requests written in Latin letters (${listAnd(latinLangs)}), but only ${nlStopped} of ${nlMan.length} in non-Latin script. `;
      t += "In each, Lyzr misread the request and approved it as a sound personal reason. This is the weakest spot we found: non-Latin scripts need more work.";
      $("#miss-intro").textContent = t;
    }
    $("#misses").innerHTML = miss.map((r) => {
      const dk = r.desk;
      const others = BJ.filter((j) => j !== "desk").map((j) => `<span class="${r.correct[j] ? "ok" : "bad"}">${BJN[j]}: <b>${esc(blindDecision(r, j))}</b> (${r.correct[j] ? "right" : "wrong"})</span>`).join("");
      return `<article class="miss-card">
        <div class="card-top"><span class="pill miss">Desk missed</span><span class="pill ${r.label}">${r.label === "manipulative" ? "Manipulative" : "Legitimate"}</span><span class="pill lang">${esc(langLabel(r))}</span>${r.rule ? `<span class="rule">${esc(r.rule)}</span>` : ""}</div>
        <blockquote lang="${langAttr(r.text)}">“${esc(r.text)}”</blockquote>
        <p class="miss-what">What it asks for: <b>${esc(human(r.category))}</b>${r.rule ? `, which ${esc(r.rule)} forbids` : ""}.</p>
        <div class="side lyzr wrong"><span class="by">Muhurat Desk (Lyzr) · <b>${esc(dk.decision)}</b></span>${esc(cleanReason(dk.reason))}</div>
        <p class="miss-others">${others}</p>
      </article>`;
    }).join("");

    // Cards
    const seg = $("#fb-lang");
    seg.innerHTML = [["all", "All languages"]].concat(langs.map((l) => [l, l])).map(([v, t], i) => `<button type="button" data-v="${esc(v)}" aria-pressed="${i === 0}">${esc(t)}</button>`).join("");
    const state = { label: "all", lang: "all", all: false };
    const draw = () => {
      const list = R.filter((r) => (state.label === "all" || r.label === state.label) && (state.lang === "all" || r.language === state.lang));
      const shown = state.all ? list : list.slice(0, 8);
      $("#b-cards").innerHTML = list.length ? shown.map(blindCardHTML).join("") : '<p class="empty">No requests match these filters.</p>';
      $("#b-count").textContent = shown.length < list.length ? `Showing ${shown.length} of ${list.length} requests` : `Showing ${plural(list.length, "request")}`;
      const more = $("#b-more");
      more.hidden = shown.length >= list.length;
      more.querySelector("button").textContent = `Show all ${list.length} requests`;
    };
    $("#b-more button").addEventListener("click", () => { state.all = true; draw(); });
    for (const [id, key] of [["#fb-label", "label"], ["#fb-lang", "lang"]]) {
      $(id).addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        state[key] = b.dataset.v;
        $(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        draw();
      });
    }
    draw();
  }

  function blindCardHTML(r) {
    const chip = (j) => {
      const ok = r.correct[j];
      const cls = ok === true ? "right" : ok === false ? "wrong" : "";
      return `<div class="vchip ${cls} ${j === "desk" ? "lyzr" : ""}"><span class="j">${BJN[j]}</span><span class="d">${esc(blindDecision(r, j))}<span class="mark">${ok === true ? "right" : ok === false ? "wrong" : ""}</span></span></div>`;
    };
    const dk = r.desk, si = r.single;
    const order = r.ticker ? `BUY ${r.qty != null ? esc(r.qty) + " " : ""}${esc(tk(r.ticker))}` : "";
    return `<article class="card ${r.label}${r.correct.desk ? "" : " desk-miss"}">
      <div class="card-top"><span class="who"><span class="av client" style="width:24px;height:24px;font-size:.7rem" aria-hidden="true">C</span>Client</span>
        <span class="pill ${r.label}">${r.label === "manipulative" ? "Manipulative" : "Legitimate"}</span>
        <span class="pill lang">${esc(langLabel(r))}</span>
        ${dk.escalate ? '<span class="pill esc">Escalated to human</span>' : ""}
        ${r.correct.desk ? "" : '<span class="pill miss">Desk missed</span>'}</div>
      <blockquote lang="${langAttr(r.text)}">“${esc(r.text)}”</blockquote>
      ${order ? `<div class="order-line">Parsed as ${order}${r.category ? ` · ${esc(human(r.category))}` : ""}</div>` : ""}
      <div class="verdicts four">${BJ.map(chip).join("")}</div>
      ${dk.reason ? `<p class="reason"><span class="by">Lyzr’s reason</span>${esc(cleanReason(dk.reason))}</p>` : ""}
      ${si && si.reason && !r.correct.single ? `<p class="reason single"><span class="by">Single agent’s reason</span>${esc(si.reason)}</p>` : ""}
    </article>`;
  }

  /* ---------------- gallery ---------------- */
  function renderGallery(S, H, rows) {
    const sets = [["Dev set", S.redteam_score, (S.redteam || []).length]];
    if (H && H.score) sets.push(["Held-out set (prompt never tuned on these)", H.score, H.rows.length]);
    const frac = (a, b) => `<span class="num">${a} / ${b}</span><span class="bar" aria-hidden="true"><i style="width:${b ? (100 * a / b).toFixed(0) : 0}%"></i></span>`;
    $("#scoreboard").innerHTML = sets.map(([name, sc]) => `
      <table class="score"><caption>${esc(name)}</caption>
        <thead><tr><th scope="col">Judge</th><th scope="col">Manipulative stopped</th><th scope="col">Sound requests served</th><th scope="col">Right overall</th></tr></thead>
        <tbody>${["desk", "code_only", "keyword"].map((j) => { const s = sc[j]; return `<tr class="${j === "desk" ? "desk" : ""}"><th scope="row">${j === "desk" ? "Lyzr desk" : JUDGE[j]}</th><td>${frac(s.manipulative_blocked, s.manipulative_total)}</td><td>${frac(s.legit_served, s.legit_total)}</td><td>${frac(s.correct, s.total)}</td></tr>`; }).join("")}</tbody>
      </table>`).join("");

    if (!H) $('#f-set').hidden = true;
    const gpv = pvShort(S.prompt_version || (H && H.prompt_version));
    if (gpv) $("#g-pv").textContent = `(prompt ${gpv})`;
    const state = { label: "all", set: "all" };
    const draw = () => {
      const list = rows.filter((r) => (state.label === "all" || r.label === state.label) && (state.set === "all" || r.set === state.set));
      $("#g-count").textContent = `Showing ${plural(list.length, "request")}`;
      const shown = state.all ? list : list.slice(0, 8);
      $("#cards").innerHTML = list.length ? shown.map(cardHTML).join("") : '<p class="empty">No requests match these filters.</p>';
      $("#g-count").textContent = shown.length < list.length ? `Showing ${shown.length} of ${list.length} requests` : `Showing ${plural(list.length, "request")}`;
      const more = $("#more");
      more.hidden = shown.length >= list.length;
      more.querySelector("button").textContent = `Show all ${list.length} requests`;
    };
    $("#more button").addEventListener("click", () => { state.all = true; draw(); });
    for (const [id, key] of [["#f-label", "label"], ["#f-set", "set"]]) {
      $(id).addEventListener("click", (e) => {
        const b = e.target.closest("button");
        if (!b) return;
        state[key] = b.dataset.v;
        $(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
        draw();
      });
    }
    draw();
  }

  function cardHTML(r) {
    const appeal = r.origin === "appeal";
    const chip = (j, dec) => {
      const ok = r.correct ? r.correct[j] : undefined;
      const cls = ok === true ? "right" : ok === false ? "wrong" : "";
      const mark = ok === true ? "right" : ok === false ? "wrong" : "";
      return `<div class="vchip ${cls} ${j === "desk" ? "lyzr" : ""}"><span class="j">${JUDGE[j]}</span><span class="d">${esc(dec || "n/a")}<span class="mark">${mark}</span></span></div>`;
    };
    const order = r.ticker ? `${esc(r.side || "BUY")} ${r.qty != null ? esc(r.qty) + " " : ""}${esc(tk(r.ticker))}` : "";
    const rules = (r.rules || []).length ? `<span>Rules cited <span class="rules">${r.rules.map((x) => `<span class="rule">${esc(x)}</span>`).join("")}</span></span>` : "<span>No rule broken</span>";
    let pnl = "";
    if (r.set === "dev" && typeof r.pnl_if_filled === "number") {
      const cls = r.pnl_if_filled < 0 ? "pnl-neg" : r.pnl_if_filled > 0 ? "pnl-pos" : "";
      pnl = `<span>If it had been filled: <span class="${cls}">${moneySigned(r.pnl_if_filled)}</span> by the next checkpoint${r.until ? ` (${sdate(r.until)})` : ""}</span>`;
    }
    return `<article class="card ${r.label}">
      <div class="card-top"><span class="who"><span class="av ${appeal ? "analyst" : "client"}" style="width:24px;height:24px;font-size:.7rem" aria-hidden="true">${appeal ? "A" : "C"}</span>${appeal ? "Analyst appeal" : "Client"}</span>
        <span class="pill ${r.label}">${r.label === "manipulative" ? "Manipulative" : "Legitimate"}</span>
        <span class="pill set">${r.set === "dev" ? "Dev" : "Held-out"}</span>
        ${r.escalate ? '<span class="pill esc">Escalated to human</span>' : ""}
        ${r.date ? `<span>${fdate(r.date)}</span>` : ""}</div>
      <blockquote>“${esc(r.text)}”</blockquote>
      ${order ? `<div class="order-line">Parsed as ${order}</div>` : ""}
      <div class="verdicts">${chip("desk", r.decision)}${chip("code_only", r.code_only)}${chip("keyword", r.keyword)}</div>
      ${r.reason ? `<p class="reason"><span class="by">Lyzr’s reason</span>${esc(cleanReason(r.reason))}</p>` : ""}
      <div class="card-foot">${rules}${pnl}</div>
    </article>`;
  }

  /* ---------------- band room ---------------- */
  const AG = {
    client: { n: "Client", i: "C", tag: "human" },
    analyst: { n: "Analyst", i: "A", tag: "momentum agent" },
    compliance: { n: "Compliance", i: "L", tag: "Lyzr agent + code backstop" },
    trader: { n: "Trader", i: "T", tag: "execution agent" },
  };

  function orderLines(orders) {
    if (!orders || !orders.length) return "<ul><li>No trades: the book is already on target.</li></ul>";
    return "<ul>" + orders.map((o) => {
      const tag = o.origin === "client" ? " · client request" : o.origin === "appeal" ? " · APPEAL" : "";
      const why = o.origin === "client" || o.origin === "appeal" ? `“${esc(o.reason)}”` : esc(o.reason);
      return `<li><span class="k">${esc(o.side)} ${esc(o.qty)} ${esc(tk(o.ticker))}</span>${tag} <span class="why">${why}</span></li>`;
    }).join("") + "</ul>";
  }

  function reviewMsg(rv, round) {
    const v = rv.verdicts || [];
    const srcs = new Set(v.map((x) => x.source));
    const by = srcs.has("lyzr") || srcs.has("backstop") ? "Lyzr compliance agent + code backstop" : "code policy engine (Lyzr unreachable)";
    const MARK = { APPROVE: "✅", MODIFY: "✂️", VETO: "⛔" };
    const items = v.map((x) => {
      if (x.source === "policy-trim") return `<li class="trim">🔻 <span class="k">TRIM ${esc(tk(x.ticker))} → sell ${esc(x.approved_qty)}</span> <span class="why">${esc(x.reason)}</span></li>`;
      const tag = x.source === "backstop" ? " <b>[backstop]</b>" : "";
      const e = x.escalate ? " ⚠️ escalated" : "";
      return `<li class="${x.decision === "VETO" ? "veto" : ""}">${MARK[x.decision] || ""} <span class="k">${esc(x.decision)} ${esc(x.side)} ${esc(tk(x.ticker))} → ${esc(x.approved_qty)}</span> <span class="why">${esc(cleanReason(x.reason))}</span>${tag}${e}</li>`;
    }).join("");
    const warn = v.some((x) => x.escalate) ? '<div class="warn">⚠️ Human: someone in this room asked to bend the policy. It was refused; please take a look.</div>' : "";
    return `<p class="title">${round === 2 ? "Compliance review of the revision" : "Compliance review"} · ${fdate(rv.date)}</p><p>(by ${by}) ${esc(rv.summary || "")}</p>${items ? "<ul>" + items + "</ul>" : "<p>Nothing to review.</p>"}${warn}`;
  }

  function tradeMsg(res, round) {
    const f = res.fills || [];
    const lines = f.length ? "<ul>" + f.map((x) => `<li><span class="k">${esc(x.side)} ${esc(x.qty)} ${esc(tk(x.ticker))}</span> @ ${price(x.price)} <span class="why">(cost ${price(x.cost)})</span></li>`).join("") + "</ul>" : "<p>No fills this cycle; the book is unchanged.</p>";
    const bl = res.blocked || [];
    const held = bl.length ? `<p>Held back by Compliance: ${bl.map((b) => `${esc(b.qty)} ${esc(tk(b.ticker))} (${esc((b.rules || []).join("/") || b.decision)})`).join(", ")}.</p>` : "";
    const book = res.book || {};
    const n = book.holdings ? Object.keys(book.holdings).length : 0;
    const cash = typeof book.cash === "number" ? `<p>Book now: ${plural(n, "holding")}, cash ${money(book.cash)}.</p>` : "";
    return `<p class="title">Execution · ${fdate(res.date)}${round === 2 ? " (revision)" : ""}</p>${lines}${held}${cash}`;
  }

  function cycleMessages(c, idx, total) {
    const P = c.proposal, out = [];
    const reqs = (P.requests || []).filter((r) => r.ticker && r.origin !== "appeal");
    for (const r of reqs) out.push({ who: "client", html: `<p>${esc(r.text)}</p>` });
    const sig = P.top_signals || [];
    const buys = P.orders.filter((o) => o.side === "BUY" && (o.origin || "analyst") === "analyst").length;
    const sells = P.orders.filter((o) => o.side === "SELL" && (o.origin || "analyst") === "analyst").length;
    const note = sig.length ? `Strongest momentum today: ${sig.slice(0, 3).map((s) => `${esc(tk(s.ticker))} (3m ${pctSigned(s.mom_3m)})`).join(", ")}. Proposing ${plural(buys, "buy")} and ${plural(sells, "sell")} to rotate into strength.` : "";
    const relay = reqs.length ? `<p>${reqs.length === 1 ? "The client’s request goes" : "The client’s requests go"} to Compliance with my orders.</p>` : "";
    out.push({ who: "analyst", html: `<p class="title">Checkpoint ${idx + 1}/${total} · ${fdate(P.date)}${idx === 0 ? " · Muhurat trading, Samvat 2082 opens" : ""}</p><p>${note}</p>${relay}${orderLines(P.orders)}` });
    if (c.review) out.push({ who: "compliance", html: reviewMsg(c.review, 1) });
    if (c.result) out.push({ who: "trader", html: tradeMsg(c.result, 1) });
    if (c.revision) {
      out.push({ divider: "Round 2: the Analyst answers the cut" });
      const R = c.revision;
      const cut = (R.cut || []).map((x) => `${esc(tk(x.ticker))} (${esc((x.rules || []).join("/") || "cut")})`).join(", ");
      const appealing = (R.requests || []).length > 0;
      out.push({ who: "analyst", html: `<p class="title">Revision · ${fdate(R.date)}</p><p>Compliance cut ${cut || "part of my orders"}. ${appealing ? "I’m appealing, and offering the rest to my next-strongest names:" : "Offering that money to my next-strongest names:"}</p>${orderLines(R.orders)}` });
      if (c.review2) out.push({ who: "compliance", html: reviewMsg(c.review2, 2) });
      if (c.result2) out.push({ who: "trader", html: tradeMsg(c.result2, 2) });
    }
    return out;
  }

  function msgEl(m) {
    const li = document.createElement("li");
    if (m.divider) { li.className = "divider"; li.textContent = m.divider; return li; }
    const a = AG[m.who];
    li.className = `msg ${m.who}`;
    li.innerHTML = `<span class="av ${m.who}" aria-hidden="true">${a.i}</span><div><div class="msg-head"><span class="msg-name">${a.n}</span><span class="msg-tag">${a.tag}</span></div><div class="msg-body">${m.html}</div></div>`;
    return li;
  }

  function renderRoom(S) {
    const C = S.cycles || [];
    const tl = $("#timeline"), chat = $("#chat"), play = $("#play");
    $("#room-members").innerHTML = ["client", "analyst", "compliance", "trader"].map((k) => `<span class="av ${k}" title="${AG[k].n}">${AG[k].i}</span>`).join("");
    tl.innerHTML = C.map((c, i) => `<button type="button" data-i="${i}" aria-pressed="${i === 0}" aria-label="Checkpoint ${i + 1}, ${fdate(c.proposal.date)}${i === 0 ? ", Muhurat day" : ""}"><b>${i + 1}</b>${sdate(c.proposal.date)}${i === 0 ? " · Muhurat" : ""}</button>`).join("");
    let cur = 0, token = 0;
    const showAll = () => {
      token++;
      play.disabled = false; play.textContent = "Play the conversation";
      chat.innerHTML = "";
      cycleMessages(C[cur], cur, C.length).forEach((m) => chat.appendChild(msgEl(m)));
      chat.scrollTop = 0;
      $("#room-title").textContent = `#muhurat-desk, checkpoint ${cur + 1}`;
    };
    tl.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      cur = Number(b.dataset.i);
      tl.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      showAll();
    });
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    play.addEventListener("click", async () => {
      const my = ++token;
      play.disabled = true; play.textContent = "Playing…";
      chat.innerHTML = "";
      for (const m of cycleMessages(C[cur], cur, C.length)) {
        if (!m.divider) {
          const t = document.createElement("li");
          t.className = `msg ${m.who}`;
          t.innerHTML = `<span class="av ${m.who}" aria-hidden="true">${AG[m.who].i}</span><div><div class="msg-head"><span class="msg-name">${AG[m.who].n}</span><span class="msg-tag">is typing</span></div><span class="typing" aria-hidden="true"><i></i><i></i><i></i></span></div>`;
          chat.appendChild(t);
          chat.scrollTop = chat.scrollHeight;
          await wait(reduced ? 150 : Math.min(1800, 600 + m.html.length * 0.8));
          if (my !== token) return;
          t.remove();
        }
        const el = msgEl(m);
        el.classList.add("enter");
        chat.appendChild(el);
        el.scrollIntoView ? chat.scrollTo({ top: el.offsetTop - chat.offsetTop - 12, behavior: reduced ? "auto" : "smooth" }) : null;
        await wait(reduced ? 100 : 450);
        if (my !== token) return;
      }
      play.disabled = false; play.textContent = "Play it again";
    });
    if (C.length) showAll();
  }

  /* ---------------- the year ---------------- */
  function renderYear(S) {
    const g = S.governed, u = S.unchecked, n = S.nifty, nm = S.nifty_matched, co = S.code_only && S.code_only.governed;
    const diff = g.total_return - u.total_return;
    const fell = g.total_return < 0 && u.total_return < 0;
    let p = fell
      ? `Momentum lost money in a falling year. The governed desk finished at ${money(g.final_value)} (${pctSigned(g.total_return)}), the unchecked analyst at ${money(u.final_value)} (${pctSigned(u.total_return)}), and the Nifty 50 returned ${pctSigned(n.total_return)}. `
      : `The governed desk finished at ${money(g.final_value)} (${pctSigned(g.total_return)}), the unchecked analyst at ${money(u.final_value)} (${pctSigned(u.total_return)}), and the Nifty 50 returned ${pctSigned(n.total_return)}. `;
    p += Math.abs(diff) < 0.0005 ? "Governance made almost no difference to return. "
      : diff < 0 ? `Governance cost ${pts(diff)} of return. ` : `Governance added ${pts(diff)} of return. `;
    p += `What it bought was control: the largest single stock peaked at ${pct(g.max_stock_weight, 0)} of the book instead of ${pct(u.max_stock_weight, 0)}, the book sat over a limit in ${pct(g.breach_session_share, 0)} of sessions instead of ${pct(u.breach_session_share, 0)}, and volatility fell from ${pct(u.volatility)} to ${pct(g.volatility)}.`;
    if (co) {
      const d2 = g.total_return - co.total_return;
      p += ` The same desk with code rules only returned ${pctSigned(co.total_return)}, so adding Lyzr ${d2 < 0 ? "cost" : "added"} ${pts(d2)}; in exchange it refused the tips and override requests the code could not see.`;
    }
    const beatN = g.total_return > n.total_return;
    if (!beatN) p += ` Neither desk beat simply holding the index.`;
    $("#honest").textContent = p;

    // table
    const R = [
      ["Governed (Lyzr + code)", "the real desk", g, "--s-gov"],
      co ? ["Governed (code only)", "R1–R6, no Lyzr", co, null] : null,
      ["Unchecked analyst", "same strategy, no compliance", u, "--s-unc"],
      ["Nifty 50", "buy and hold", n, "--s-nifty"],
      nm ? ["Nifty at same exposure", `${pct(nm.invested_share, 0)} in Nifty, rest cash`, nm, null] : null,
    ].filter(Boolean);
    const cell = (v, f, bad) => v == null ? '<td>—</td>' : `<td class="${bad ? "bad" : ""}">${f(v)}</td>`;
    $("#perf").innerHTML = `<thead><tr><th scope="col">Book</th><th scope="col">Return</th><th scope="col">Max drawdown</th><th scope="col">Volatility</th><th scope="col">Largest single stock</th><th scope="col">Sessions over a limit</th></tr></thead><tbody>` +
      R.map(([name, sub, s, col]) => `<tr><th scope="row">${col ? `<span class="sw" style="background:var(${col})"></span>` : ""}${esc(name)}<small>${esc(sub)}</small></th>${cell(s.total_return, (v) => pctSigned(v))}${cell(s.max_drawdown, (v) => pct(v))}${cell(s.volatility, (v) => pct(v))}${cell(s.max_stock_weight, (v) => pct(v, 0), s.max_stock_weight > 0.15)}${cell(s.breach_session_share, (v) => pct(v, 0), s.breach_session_share > 0.5)}</tr>`).join("") + "</tbody>";
    $("#perf-note").textContent = `Return is over the whole replay; volatility is annualised from daily values. The governed book can drift past 15% in one stock between monthly checkpoints as prices move; Compliance trims it at the next one. Paper capital ₹10,00,000; 0.1% trading cost on every fill.`;

    const ypv = pvShort(S.prompt_version);
    if (ypv) {
      const tag = (String(S.prompt_version).match(/git tag ([^)\s]+)/) || [])[1];
      $("#year-pv").innerHTML = `The year replay ran on prompt <b>${esc(ypv)}</b>${tag ? ` (git tag <code>${esc(tag)}</code>)` : ""}.${blindPV ? ` The blind test above ran on the current prompt, <b>${esc(blindPV)}</b>.` : ""}`;
    } else $("#year-pv").hidden = true;

    drawChart(S.curves);
  }

  function drawChart(cv) {
    const box = $("#chart");
    if (!cv || !cv.dates || !cv.dates.length) { box.textContent = "No curve data."; return; }
    const series = [["governed", "Governed desk", "--s-gov", 3], ["unchecked", "Unchecked analyst", "--s-unc", 2], ["nifty", "Nifty 50", "--s-nifty", 2]].filter((s) => Array.isArray(cv[s[0]]));
    $("#legend").innerHTML = series.map((s) => `<span><i style="background:var(${s[2]})"></i>${s[1]}</span>`).join("");
    const D = cv.dates, N = D.length;
    const draw = () => {
      const W = Math.max(320, box.clientWidth), Hh = W < 560 ? 260 : 340;
      const m = { l: W < 560 ? 46 : 58, r: 12, t: 12, b: 28 };
      let lo = Infinity, hi = -Infinity;
      for (const s of series) for (const v of cv[s[0]]) { if (v < lo) lo = v; if (v > hi) hi = v; }
      const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
      const step = niceStep((hi - lo) / 5);
      const y0 = Math.floor(lo / step) * step, y1 = Math.ceil(hi / step) * step;
      const X = (i) => m.l + (W - m.l - m.r) * (i / (N - 1));
      const Y = (v) => m.t + (Hh - m.t - m.b) * (1 - (v - y0) / (y1 - y0));
      let grid = "", axis = "";
      for (let v = y0; v <= y1 + 1e-6; v += step) {
        grid += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}"/>`;
        axis += `<text x="${m.l - 8}" y="${Y(v) + 4}" text-anchor="end">₹${(v / 1e5).toFixed(step < 1e4 ? 2 : 1)}L</text>`;
      }
      const base = Y(1e6);
      if (1e6 > y0 && 1e6 < y1) grid += `<line x1="${m.l}" x2="${W - m.r}" y1="${base}" y2="${base}" style="stroke:var(--ink-3);stroke-dasharray:3 4"/>`;
      let lastM = -1;
      const every = W < 560 ? 3 : 2;
      let cnt = 0;
      D.forEach((d, i) => {
        const mo = Number(d.slice(5, 7));
        if (mo !== lastM) {
          if (cnt % every === 0) axis += `<text x="${X(i)}" y="${Hh - 8}" text-anchor="middle">${MONTHS[mo - 1]}${mo === 1 || cnt === 0 ? " " + d.slice(2, 4) : ""}</text>`;
          cnt++; lastM = mo;
        }
      });
      const paths = series.slice().reverse().map((s) => {
        const a = cv[s[0]];
        let dd = "";
        for (let i = 0; i < N; i++) dd += (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(a[i]).toFixed(1);
        return `<path d="${dd}" fill="none" stroke="var(${s[2]})" stroke-width="${s[3]}" stroke-linejoin="round" stroke-linecap="round"/>`;
      }).join("");
      box.innerHTML = `<svg viewBox="0 0 ${W} ${Hh}" role="img" aria-label="Line chart of daily portfolio value for the governed desk, unchecked analyst and Nifty 50 from ${fdate(D[0])} to ${fdate(D[N - 1])}"><g class="grid">${grid}</g><g class="axis">${axis}</g>${paths}<line id="xh" y1="${m.t}" y2="${Hh - m.b}" stroke="var(--ink-3)" visibility="hidden"/>${series.map((s) => `<circle class="dot" data-k="${s[0]}" r="4" fill="var(${s[2]})" visibility="hidden"/>`).join("")}</svg><div class="tip" hidden></div>`;
      const svg = box.querySelector("svg"), tip = box.querySelector(".tip"), xh = svg.querySelector("#xh");
      const move = (ev) => {
        const r = svg.getBoundingClientRect();
        const x = (ev.clientX - r.left) * (W / r.width);
        const i = Math.max(0, Math.min(N - 1, Math.round(((x - m.l) / (W - m.l - m.r)) * (N - 1))));
        xh.setAttribute("x1", X(i)); xh.setAttribute("x2", X(i)); xh.setAttribute("visibility", "visible");
        svg.querySelectorAll(".dot").forEach((c) => { c.setAttribute("cx", X(i)); c.setAttribute("cy", Y(cv[c.dataset.k][i])); c.setAttribute("visibility", "visible"); });
        tip.hidden = false;
        tip.innerHTML = `<b>${fdate(D[i])}</b><br>` + series.map((s) => `${s[1]}: ${money(cv[s[0]][i])}`).join("<br>");
        const px = X(i) * (r.width / W);
        const tw = tip.offsetWidth;
        tip.style.left = Math.max(tw / 2, Math.min(r.width - tw / 2, px)) + "px";
      };
      const leave = () => { tip.hidden = true; xh.setAttribute("visibility", "hidden"); svg.querySelectorAll(".dot").forEach((c) => c.setAttribute("visibility", "hidden")); };
      svg.addEventListener("pointermove", move);
      svg.addEventListener("pointerdown", move);
      svg.addEventListener("pointerleave", leave);
    };
    draw();
    let rt; let lastW = box.clientWidth;
    window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => { if (box.clientWidth !== lastW) { lastW = box.clientWidth; draw(); } }, 150); });
  }

  function niceStep(raw) {
    const p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
  }

  /* ---------------- diagram ---------------- */
  function renderDiagram() {
    const box = $("#diagram");
    const node = (x, y, w, h, who, title, sub) => `<g><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="14" fill="var(--surface)" stroke="var(--c-${who})" stroke-width="2"/><circle cx="${x + 28}" cy="${y + h / 2}" r="15" fill="var(--c-${who})"/><text x="${x + 28}" y="${y + h / 2 + 5}" text-anchor="middle" style="fill:var(--surface);font-weight:700;font-size:14px">${AG[who].i}</text><text x="${x + 52}" y="${y + h / 2 - 3}" style="font-weight:700;font-size:15px">${title}</text><text class="sub" x="${x + 52}" y="${y + h / 2 + 15}">${sub}</text></g>`;
    const arrow = (d, label, lx, ly, dash, anchor = "middle") => `<path d="${d}" fill="none" stroke="var(--ink-3)" stroke-width="1.6" marker-end="url(#ah)" ${dash ? 'stroke-dasharray="5 5"' : ""}/><text class="sub" x="${lx}" y="${ly}" text-anchor="${anchor}">${label}</text>`;
    const defs = `<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="var(--ink-3)"/></marker></defs>`;
    const wide = () => `<svg viewBox="0 0 960 380" role="img" aria-label="Diagram: the client and three agents share one Band room. The Analyst proposes, Compliance reviews with Lyzr and a code backstop, the Trader fills, and escalations go to the human.">${defs}
      <rect x="8" y="8" width="944" height="364" rx="22" fill="var(--bg)" stroke="var(--line)" stroke-width="1.5" stroke-dasharray="2 0"/>
      <text x="32" y="40" style="font-weight:700;font-size:15px">Band room</text><text class="sub" x="122" y="40">every handoff is a message with a mention</text>
      ${node(32, 70, 200, 64, "client", "Client", "asks in English or Hinglish")}
      ${node(32, 230, 200, 64, "analyst", "Analyst", "aggressive momentum")}
      ${node(370, 150, 230, 64, "compliance", "Compliance", "judges every order")}
      ${node(730, 150, 200, 64, "trader", "Trader", "fills, costs, books")}
      <rect x="360" y="236" width="250" height="92" rx="12" fill="none" stroke="var(--line)"/>
      <rect x="372" y="248" width="108" height="68" rx="10" fill="color-mix(in srgb, var(--c-compliance) 14%, transparent)"/><text x="426" y="276" text-anchor="middle" style="font-weight:700;font-size:14px">Lyzr</text><text class="sub" x="426" y="294" text-anchor="middle">intent: R7, R8</text>
      <rect x="490" y="248" width="108" height="68" rx="10" fill="color-mix(in srgb, var(--c-trader) 14%, transparent)"/><text x="544" y="276" text-anchor="middle" style="font-weight:700;font-size:14px">Code</text><text class="sub" x="544" y="294" text-anchor="middle">limits: R1–R6</text>
      <line x1="485" y1="214" x2="485" y2="236" stroke="var(--line)" stroke-width="2"/>
      ${arrow("M132 134 L132 226", "request", 142, 186, false, "start")}
      ${arrow("M232 250 C300 250 310 190 366 186", "proposal", 250, 282, false, "start")}
      ${arrow("M600 182 L726 182", "verdicts", 663, 174)}
      ${arrow("M830 214 C830 350 140 350 132 298", "fills go back; the analyst revises or appeals", 480, 352)}
      ${arrow("M420 150 C400 96 300 96 236 100", "escalation to the human", 440, 122, true, "start")}
    </svg>`;
    const tall = () => `<svg viewBox="0 0 340 640" role="img" aria-label="Diagram: the client and three agents share one Band room. The Analyst proposes, Compliance reviews with Lyzr and a code backstop, the Trader fills, and escalations go to the human.">${defs}
      <rect x="4" y="4" width="332" height="632" rx="20" fill="var(--bg)" stroke="var(--line)" stroke-width="1.5"/>
      <text x="22" y="34" style="font-weight:700;font-size:15px">Band room</text>
      ${node(40, 54, 260, 64, "client", "Client", "English or Hinglish")}
      ${node(40, 172, 260, 64, "analyst", "Analyst", "aggressive momentum")}
      ${node(40, 290, 260, 64, "compliance", "Compliance", "judges every order")}
      <rect x="40" y="366" width="124" height="60" rx="10" fill="color-mix(in srgb, var(--c-compliance) 14%, transparent)"/><text x="102" y="392" text-anchor="middle" style="font-weight:700;font-size:14px">Lyzr</text><text class="sub" x="102" y="410" text-anchor="middle">intent: R7, R8</text>
      <rect x="176" y="366" width="124" height="60" rx="10" fill="color-mix(in srgb, var(--c-trader) 14%, transparent)"/><text x="238" y="392" text-anchor="middle" style="font-weight:700;font-size:14px">Code</text><text class="sub" x="238" y="410" text-anchor="middle">limits: R1–R6</text>
      ${node(40, 490, 260, 64, "trader", "Trader", "fills, costs, books")}
      ${arrow("M170 118 L170 168", "request", 180, 148, false, "start")}
      ${arrow("M170 236 L170 286", "proposal", 180, 266, false, "start")}
      ${arrow("M170 426 L170 486", "verdicts", 180, 460, false, "start")}
      ${arrow("M300 522 C334 522 334 204 304 204", "", 0, 0)}
      <text class="sub" x="170" y="590" text-anchor="middle">fills go back; the analyst revises or appeals</text>
      ${arrow("M40 322 C10 322 10 86 36 86", "", 0, 0, true)}
      <text class="sub" x="170" y="612" text-anchor="middle">dashed: escalation to the human</text>
    </svg>`;
    let mode = "";
    const draw = () => { const m = box.clientWidth < 640 ? "tall" : "wide"; if (m !== mode) { mode = m; box.innerHTML = m === "tall" ? tall() : wide(); } };
    draw();
    window.addEventListener("resize", draw);
  }

  /* ---------------- rangoli ---------------- */
  function drawRangoli() {
    const g = document.getElementById("rangoli-g");
    if (!g) return;
    let s = "";
    const cx = 200, cy = 200;
    const ring = (r, n, size, col, op) => { for (let i = 0; i < n; i++) { const a = (i / n) * Math.PI * 2; s += `<circle cx="${(cx + r * Math.cos(a)).toFixed(1)}" cy="${(cy + r * Math.sin(a)).toFixed(1)}" r="${size}" style="fill:${col};opacity:${op}"/>`; } };
    const petals = (r, n, len, col, op) => { for (let i = 0; i < n; i++) { const a = (i / n) * 360; s += `<ellipse cx="${cx}" cy="${cy - r}" rx="${len / 3}" ry="${len}" transform="rotate(${a} ${cx} ${cy})" style="fill:none;stroke:${col};stroke-width:1.4;opacity:${op}"/>`; } };
    petals(46, 8, 30, "#ffb627", .9);
    petals(110, 16, 34, "#e0464f", .55);
    ring(28, 8, 3, "#ffd27a", .9);
    ring(84, 16, 3.2, "#ffb627", .8);
    ring(150, 32, 2.6, "#ffd27a", .6);
    petals(178, 24, 20, "#a99bff", .45);
    ring(196, 48, 2, "#ffb627", .5);
    s += `<circle cx="${cx}" cy="${cy}" r="10" style="fill:#ffb627;opacity:.9"/>`;
    g.innerHTML = s;
  }

  main();
})();

"use strict";
/* ENCOR Lab Builder UI - vanilla JS, no build step. */
const APP_JS_VERSION = "1.4.0";  // must equal encorlab.__version__ (tests/test_packaging.py)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const DOMAINS = ["1.0 Architecture", "2.0 Virtualization", "3.0 Infrastructure - Layer 2", "3.0 Infrastructure - Layer 3",
  "3.0 Infrastructure - Wireless", "3.0 Infrastructure - IP Services", "4.0 Network Assurance", "5.0 Security", "6.0 Automation"];
let labs = [], current = null, templates = [], draft = null, draftSource = null, statusTimer = null;

/* ---------------------------------------------------------------- error banner */
function banner(msg) {
  const b = document.getElementById("error-banner");
  if (!b) return;
  if (!msg) { b.hidden = true; b.innerHTML = ""; return; }
  const line = document.createElement("div");
  line.textContent = msg;
  if (b.hidden) {
    b.innerHTML = '<button data-help-text="Hide this message" class="hint-btn" onclick="banner()">Dismiss</button>' +
      "<b>Something went wrong.</b> Try a hard refresh (Ctrl+Shift+R / Ctrl+F5). Details (also in the F12 console):";
    b.hidden = false;
  }
  if (b.childElementCount < 8) b.appendChild(line);
  console.error(msg);
}
window.addEventListener("error", (e) => banner(`Script error: ${e.message} (${(e.filename || "").split("/").pop()}:${e.lineno})`));
window.addEventListener("unhandledrejection", (e) => banner(`Unhandled error: ${e.reason && e.reason.message || e.reason}`));

/* ---------------------------------------------------------------- utils */
async function api(path, opts = {}) {
  const o = Object.assign({}, opts);
  if (o.body && !(o.body instanceof FormData)) o.headers = Object.assign({"Content-Type": "application/json"}, o.headers || {});
  const r = await fetch(path, o);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(data.detail || (data.errors || []).join("\n") || r.statusText); e.data = data; e.status = r.status; throw e; }
  return data;
}
function toast(msg, kind = "", ms = 5000) {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg; t.title = "Click to dismiss";
  t.onclick = () => t.remove();
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), ms);
}
async function pollJob(jobId, onLog) {
  for (;;) {
    await new Promise((r) => setTimeout(r, 1200));
    const j = await api(`/api/jobs/${jobId}`);
    if (onLog) onLog(j);
    if (j.state !== "running") return j;
  }
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok;
  }
}
const fmtTime = (s) => `${String(Math.floor(s / 3600)).padStart(2, "0")}:${String(Math.floor(s / 60) % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

/* Minimal, safe Markdown: input is HTML-escaped first; supports headings, lists, tables, code, bold. */
function md(src) {
  const inline = (t) => esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  const lines = String(src || "").split("\n"), out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^```/.test(l)) { const buf = []; while (++i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i]); out.push(`<pre class="code">${esc(buf.join("\n"))}</pre>`); continue; }
    if (/^ {4}\S/.test(l) || (/^ {4}/.test(l) && out.length && out[out.length - 1].startsWith("<pre"))) {
      const buf = [l.slice(4)]; while (i + 1 < lines.length && /^( {4}|\s*$)/.test(lines[i + 1]) && lines[i + 1].trim()) buf.push(lines[++i].slice(4));
      out.push(`<pre class="code">${esc(buf.join("\n"))}</pre>`); continue; }
    if (/^\|/.test(l)) { const rows = [l]; while (i + 1 < lines.length && /^\|/.test(lines[i + 1])) rows.push(lines[++i]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\|[\s:|-]+\|?$/.test(r.trim()));
      out.push("<table>" + body.map((r, k) => "<tr>" + cells(r).map((c) => k ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`).join("") + "</tr>").join("") + "</table>"); continue; }
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.*)/))) { out.push(`<h${m[1].length + 2}>${inline(m[2])}</h${m[1].length + 2}>`); continue; }
    if ((m = l.match(/^\s*([-*]|\d+\.)\s+(.*)/))) { const tag = /\d/.test(m[1]) ? "ol" : "ul", items = [m[2]];
      while (i + 1 < lines.length && /^\s*([-*]|\d+\.)\s+|^\s{2,}\S/.test(lines[i + 1])) { const n = lines[++i]; const mm = n.match(/^\s*([-*]|\d+\.)\s+(.*)/); if (mm) items.push(mm[2]); else items[items.length - 1] += " " + n.trim(); }
      out.push(`<${tag}>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</${tag}>`); continue; }
    if (!l.trim()) { out.push(""); continue; }
    const para = [l.trim()];  // consecutive plain lines form one paragraph (Markdown soft wrap)
    while (i + 1 < lines.length && lines[i + 1].trim() && !/^(```|\||#{1,4}\s|\s*([-*]|\d+\.)\s| {4})/.test(lines[i + 1])) para.push(lines[++i].trim());
    out.push(`<p>${inline(para.join(" "))}</p>`);
  }
  return out.join("\n");
}

/* Same placeholder rules as encorlab/platforms.py (kept in sync by tests/test_placeholders.py). */
const IFNAMES = {iol: ["Ethernet0/", "Et0/"], iosv: ["GigabitEthernet0/", "Gi0/"]};
function renderIf(text, plat) { return String(text || "").replace(/%if(\d)(s?)%/g, (_, n, sh) => IFNAMES[plat][sh ? 1 : 0] + n); }

/* ---------------------------------------------------------------- navigation + theme */
function show(view) {
  for (const v of ["labs", "builder", "settings", "ai"]) $(`#view-${v}`).hidden = v !== view;
  $$("nav>a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $("#more-menu").hidden = true;
  if (view === "settings") loadSettings();
  if (view === "builder" && !draft) newDraft();
}
$$("[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); location.hash = a.dataset.view; show(a.dataset.view); }));
$("#more-btn").onclick = (e) => { e.stopPropagation(); $("#more-menu").hidden = !$("#more-menu").hidden; };
document.addEventListener("click", () => { $("#more-menu").hidden = true; });
$("#theme-btn").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t; localStorage.setItem("theme", t);
};
$("#copy-prompt-link").onclick = async (e) => { e.preventDefault(); await copyPrompt(""); };
async function copyPrompt(desc) {
  const {prompt} = await api(`/api/prompt?description=${encodeURIComponent(desc)}`);
  toast(await copyText(prompt) ? "Prompt copied. Paste it into any AI chat, then import the lab file it returns." : "Could not copy to clipboard", "ok", 7000);
}

/* ---------------------------------------------------------------- import (button + drag & drop) */
$("#import-btn").onclick = () => $("#import-file").click();
$("#import-file").onchange = async (e) => { for (const f of e.target.files) await importFile(f); e.target.value = ""; };
let dragDepth = 0;
const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; $("#drop-overlay").hidden = false; });
window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#drop-overlay").hidden = true; });
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("drop", async (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault(); dragDepth = 0; $("#drop-overlay").hidden = true;
  show("labs");
  for (const f of e.dataTransfer.files) await importFile(f);
});
async function importFile(file, replace = false) {
  const fd = new FormData(); fd.append("file", file);
  try {
    const rep = await api(`/api/import${replace ? "?replace=true" : ""}`, {method: "POST", body: fd});
    toast(`Imported "${rep.title}"` + (rep.warnings.length ? `\nNote: ${rep.warnings.join("\n")}` : ""), "ok", 7000);
    try { await loadLabs(); await selectLab(rep.lab_id); } catch (e) { return; }  // import succeeded; banner explains the list error
    const li = $("#lab-list li.sel"); if (li) li.scrollIntoView({block: "nearest", behavior: "smooth"});
  } catch (err) {
    const d = err.data || {};
    if (err.status === 409 && confirm(`A lab with id "${d.lab_id}" is already imported. Replace it?`)) return importFile(file, true);
    toast(`Could not import ${file.name}:\n- ` + ((d.errors && d.errors.length) ? d.errors.join("\n- ") : err.message), "err", 15000);
  }
}

/* ---------------------------------------------------------------- catalog */
async function loadLabs() {
  let data;
  try { data = await api("/api/labs"); } catch (e) { banner(`Could not load the lab list: ${e.message}`); e.shown = true; throw e; }
  labs = data.labs;
  const sel = $("#f-domain"), cur = sel.value;
  const doms = [...new Set(labs.map((l) => l.domain))].sort();
  sel.innerHTML = `<option value="">All domains</option>` + doms.map((d) => `<option ${d === cur ? "selected" : ""}>${esc(d)}</option>`).join("");
  renderList();
  const broken = Object.entries(data.broken || {});
  if (broken.length) banner("Some labs were skipped: " + broken.map(([p, e]) => `${p}: ${e}`).join(" | "));
  const lsel = $("#b-load");
  lsel.innerHTML = `<option value="">Open existing lab…</option>` + labs.map((l) => `<option value="${esc(l.id)}">${esc(l.title)} (${l.source})</option>`).join("");
}
function renderList() {
  const q = $("#f-search").value.toLowerCase(), dom = $("#f-domain").value, diff = $("#f-diff").value, src = $("#f-source").value;
  const items = labs.filter((l) => (!q || (l.title + l.summary + l.id + l.blueprint.join(" ")).toLowerCase().includes(q)) &&
    (!dom || l.domain === dom) && (!diff || String(l.difficulty) === diff) && (!src || l.source === src));
  $("#lab-list").innerHTML = items.map((l) => `<li data-help="lab.item" data-id="${esc(l.id)}" class="${l.id === current ? "sel" : ""}">
    <b>${esc(l.title)}</b><br>
    <span class="tag">${"★".repeat(l.difficulty)}</span><span class="tag">${l.nodes} nodes</span><span class="tag">${esc(l.blueprint.join(", "))}</span>
    ${l.source === "user" ? '<span class="tag user">imported</span>' : ""}${l.fault_active ? '<span class="tag warn">fault active</span>' : ""}${l.solved ? '<span class="tag ok">solved</span>' : (l.best != null ? `<span class="tag">best ${l.best}%</span>` : "")}
    <div class="muted small">${esc(l.summary)}</div></li>`).join("") || `<li class="muted">No labs match.</li>`;
  $$("#lab-list li[data-id]").forEach((li) => li.addEventListener("click", () => selectLab(li.dataset.id)));
}
["#f-search", "#f-domain", "#f-diff", "#f-source"].forEach((s) => $(s).addEventListener("input", renderList));

/* ---------------------------------------------------------------- timer (per lab, localStorage) */
const timerKey = (id) => `timer:${id}`;
function timerState(id) { return JSON.parse(localStorage.getItem(timerKey(id)) || '{"acc":0,"start":null}'); }
function timerSecs(id) { const t = timerState(id); return Math.floor((t.acc + (t.start ? Date.now() - t.start : 0)) / 1000); }
function timerSet(id, t) { localStorage.setItem(timerKey(id), JSON.stringify(t)); renderTimer(); }
function timerStart(id) { const t = timerState(id); if (!t.start) { t.start = Date.now(); timerSet(id, t); } }
function timerPause(id) { const t = timerState(id); if (t.start) { t.acc += Date.now() - t.start; t.start = null; timerSet(id, t); } }
function renderTimer() {
  if (!current || !$("#timer")) return;
  $("#timer").textContent = fmtTime(timerSecs(current));
  $("#t-toggle").textContent = timerState(current).start ? "Pause" : "Start";
}
setInterval(renderTimer, 1000);

/* ---------------------------------------------------------------- lab detail */
async function selectLab(id) {
  current = id; renderList();
  const l = await api(`/api/labs/${id}`);
  $("#lab-detail").innerHTML = `
    <div class="toolbar"><h2 style="margin:0">${esc(l.title)}</h2><span class="sep"></span>
      <span class="tag">${esc(l.domain)}</span><span class="tag">${"★".repeat(l.difficulty)}</span>
      ${l.source === "user" ? '<span class="tag user">imported</span>' : ""}</div>
    <div class="toolbar">
      <button data-help="lab.build" id="a-build" class="primary">Build</button><button data-help="lab.check" id="a-check">Check</button><button data-help="lab.hintNext" id="a-hint">Hint</button>
      <label class="inline">Grading<select data-help="lab.mode" id="mode"><option value="">Mode: default</option><option value="auto">Auto</option><option value="live">Live only</option><option value="config">Config only</option></select></label>
      <button data-help="lab.reset" id="a-reset">Reset</button><button data-help="lab.destroy" id="a-destroy" class="danger">Destroy</button>
      ${l.faults ? `<button data-help="lab.break" id="a-break" class="warn">Break my lab</button>` : ""}
      <span class="sep"></span>
      <button data-help="lab.edit" id="a-edit">Edit / copy</button><button data-help="lab.export" id="a-export">Export pack</button>
      ${l.source === "user" ? '<button data-help="lab.delete" id="a-delete" class="danger">Delete lab</button>' : ""}
    </div>
    <div class="statusbar"><span data-help="lab.status" class="muted"><span id="status">Status: …</span></span><div class="progress"><div id="boot-bar"></div></div>
      <span data-help="lab.timer">⏱ <span id="timer" class="timer">00:00:00</span></span><button data-help="lab.timerToggle" id="t-toggle" class="hint-btn">Start</button><button data-help="lab.timerReset" id="t-reset" class="hint-btn">Reset timer</button></div>
    ${l.fault ? `<section class="fault-box" data-help="lab.faultBox"><h3>Trouble ticket <span class="tag">fault practice</span></h3>
      <p>${esc(l.fault.ticket)}</p><p class="muted small">Started ${esc(l.fault.started || "")}. The lab was built from a working config with one fault added.
      Find and fix it, then click Check.${l.fault.extra_checks ? ` ${l.fault.extra_checks} extra check(s) are graded for this fault.` : ""}</p>
      <div class="toolbar"><button data-help="lab.faultReveal" id="a-fault-reveal" class="hint-btn">Reveal the answer</button>
      <button data-help="lab.faultEnd" id="a-fault-end" class="hint-btn">End fault practice</button></div><div id="fault-answer"></div></section>` : ""}
    <div id="hints-box" class="hints-box" data-help="lab.hintsBox" hidden></div>
    <h3 data-help="lab.task">Task</h3><div class="task md">${md(l.task)}</div>
    <details><summary data-help="lab.objectives">Objectives graded (${l.checks.length} checks: ${l.checks.filter((c) => c.mode === "live").length} live, ${l.checks.filter((c) => c.mode === "config").length} config) - spoilers</summary>
      <table>${l.checks.map((c) => `<tr><td><span class="tag">${c.mode}</span></td><td>${esc(c.device)}</td><td>${esc(c.description)}</td>
      <td>${c.hint ? `<button data-help="lab.hint" class="hint-btn" data-hint="${esc(c.hint)}">Show hint</button>` : ""}</td></tr>`).join("")}</table></details>
    <h3 data-help="lab.results">Results</h3><div id="results" class="muted">Not checked yet.</div>
    <h3 data-help="lab.activity">Activity</h3><pre id="log" class="log">-</pre>
    <details id="hist-box"><summary data-help="lab.history">History</summary><div id="history"></div></details>`;
  $("#a-build").onclick = () => run("build");
  $("#a-check").onclick = () => run("check");
  currentHints = l.hints || [];
  $("#a-hint").onclick = () => { const n = hintsUsed(id); if (n < currentHints.length) { hintsSet(id, n + 1); } };
  renderHints();
  $("#a-reset").onclick = () => confirm(l.fault ? "Reset rebuilds the broken lab (same fault) and discards your changes. Continue?"
    : "Reset wipes all your device configs back to the starting configs. Continue?") && run("reset");
  if ($("#a-break")) $("#a-break").onclick = () => confirm(`Break my lab: the lab is rebuilt in CML with a working configuration plus one random fault (out of ${l.faults}). Your current device configs are replaced. Continue?`) && run("break");
  if ($("#a-fault-end")) $("#a-fault-end").onclick = async () => {
    if (!confirm("End fault practice? The devices keep their current configs; use Reset afterwards to go back to the starting configs.")) return;
    await api(`/api/labs/${id}/fault/end`, {method: "POST"}); hintsSet(id, 0); selectLab(id);
  };
  if ($("#a-fault-reveal")) $("#a-fault-reveal").onclick = async () => {
    if (!confirm("Reveal the cause and the fix of this fault?")) return;
    try { $("#fault-answer").innerHTML = faultPanel(await api(`/api/labs/${id}/fault/reveal`, {method: "POST"}), "Answer"); }
    catch (e) { toast(e.message, "err"); }
  };
  $("#a-destroy").onclick = () => confirm("Delete this lab from CML?") && run("destroy");
  $("#a-edit").onclick = () => openInBuilder(id);
  $("#a-export").onclick = () => { location.href = `/api/labs/${encodeURIComponent(id)}/export`; };
  if ($("#a-delete")) $("#a-delete").onclick = async () => {
    if (!confirm(`Delete imported lab "${l.title}" from this app? (It is not removed from CML.)`)) return;
    try { await api(`/api/user-labs/${id}`, {method: "DELETE"}); toast("Lab deleted", "ok"); current = null;
      $("#lab-detail").innerHTML = '<div class="empty">Select a lab, or import one.</div>'; loadLabs(); } catch (e) { toast(e.message, "err"); }
  };
  $("#t-toggle").onclick = () => (timerState(id).start ? timerPause(id) : timerStart(id));
  $("#t-reset").onclick = () => confirm("Reset the timer?") && timerSet(id, {acc: 0, start: null});
  bindHints($("#lab-detail"));
  renderTimer(); refreshStatus(); loadHistory();
}
/* ---------------------------------------------------------------- progressive hints (per lab, localStorage) */
let currentHints = [];
const hintsKey = (id) => `hints:${id}`;
function hintsUsed(id) { const n = parseInt(localStorage.getItem(hintsKey(id)) || "0", 10); return Number.isFinite(n) && n > 0 ? n : 0; }
function hintsSet(id, n) { if (n) localStorage.setItem(hintsKey(id), String(n)); else localStorage.removeItem(hintsKey(id)); renderHints(); }
function renderHints() {
  const btn = $("#a-hint"), box = $("#hints-box");
  if (!btn || !box || !current) return;
  const total = currentHints.length, used = Math.min(hintsUsed(current), total);
  btn.disabled = used >= total;
  btn.textContent = !total ? "No hints" : used >= total ? `All ${total} hints shown` : `Hint ${used + 1} of ${total}`;
  box.hidden = !used;
  box.innerHTML = currentHints.slice(0, used).map((h, i) =>
    `<div class="hint-item"><span class="tag">Hint ${i + 1} of ${total}</span> ${md(h).replace(/^<p>|<\/p>$/g, "")}</div>`).join("");
}
function bindHints(root) {
  $$("[data-hint]", root).forEach((b) => b.onclick = () => { b.replaceWith(Object.assign(document.createElement("i"), {textContent: "Hint: " + b.dataset.hint})); });
}
async function refreshStatus() {
  if (!current || !$("#status")) return;
  try {
    const s = await api(`/api/labs/${current}/status`);
    let text = "Status: ", pct = 0;
    if (!s.configured) text += "configure CML in Settings";
    else if (s.error) text += s.error;
    else if (!s.exists) text += "not built";
    else {
      const states = Object.values(s.nodes || {});
      const booted = states.filter((x) => x === "BOOTED").length;
      pct = states.length ? Math.round(100 * booted / states.length) : 0;
      text += `${s.state} · ${booted}/${states.length} nodes booted`;
    }
    $("#status").textContent = text; $("#boot-bar").style.width = pct + "%";
  } catch (e) { $("#status").textContent = "Status: " + e.message; }
}
function setBusy(b) { $$("#lab-detail .toolbar button").forEach((x) => { if (!x.closest("a")) x.disabled = b; }); if (!b) renderHints(); }
async function run(kind) {
  const lab = current; setBusy(true);
  $("#log").textContent = `${kind} started…`;
  clearInterval(statusTimer); statusTimer = setInterval(refreshStatus, 4000);
  try {
    const q = new URLSearchParams();
    if (kind === "check") { if ($("#mode").value) q.set("mode", $("#mode").value); q.set("hints_used", String(hintsUsed(lab))); }
    const {job_id} = await api(`/api/labs/${lab}/${kind}` + (q.toString() ? `?${q}` : ""), {method: "POST"});
    const j = await pollJob(job_id, (j) => { if (lab === current) { $("#log").textContent = j.log.join("\n") || "…"; $("#log").scrollTop = 1e9; } });
    if (j.state === "error") toast(`${kind} failed: ${j.error}`, "err", 12000);
    else {
      toast(`${kind} finished`, "ok");
      if (kind === "build") timerStart(lab);
      if (kind === "reset") hintsSet(lab, 0);
      if (kind === "break") { hintsSet(lab, 0); timerSet(lab, {acc: 0, start: Date.now()}); toast("Trouble ticket ready. Find and fix the fault.", "ok", 7000); if (lab === current) await selectLab(lab); }
      if (kind === "check" && j.result && lab === current) {
        if (j.result.fault_fixed) { hintsSet(lab, 0); await selectLab(lab); }
        showResults(j.result); if (j.result.passed) { timerPause(lab); toast(j.result.fault_fixed ? "Fault fixed!" : "Lab solved!", "ok"); } loadHistory(); loadLabs(); }
    }
  } catch (e) { toast(e.message, "err", 10000); if ($("#log")) $("#log").textContent = "Error: " + e.message; }
  clearInterval(statusTimer); setBusy(false); refreshStatus();
}
function showResults(r) {
  const modeName = r.mode === "config" ? "Config (running config via CML API)" : "Live (device console)";
  $("#results").classList.remove("muted");
  $("#results").innerHTML = `<p><b>Score ${r.earned}/${r.total} (${r.score_pct}%)</b> ${r.passed ? '<span class="pass">SOLVED</span>' : '<span class="fail">not solved yet</span>'}</p>
    <p>Mode used: <b>${esc(modeName)}</b>${r.requested_mode ? ` (requested: ${esc(r.requested_mode)})` : ""}</p>
    ${(r.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
    <table><tr><th></th><th>Device</th><th>Check</th><th>Details</th></tr>${r.results.map((c) => `
    <tr><td class="${c.passed ? "pass" : "fail"}">${c.passed ? "PASS" : "FAIL"}</td><td>${esc(c.device)}</td>
    <td>${esc(c.description)}<br><code class="small">${esc(c.command)}</code></td>
    <td class="small">${c.details.map(esc).join("<br>")}${c.hint ? `<br><button data-help="lab.hint" class="hint-btn" data-hint="${esc(c.hint)}">Show hint</button>` : ""}
    <details><summary data-help="lab.output">output</summary><pre class="log">${esc(c.output)}</pre></details></td></tr>`).join("")}</table>
    ${r.fault_fixed ? faultPanel(r.fault_fixed, "Fault fixed") : ""}
    <div id="solution-box">${r.fault ? "" : r.passed && r.solution_summary ? solutionPanel({summary: r.solution_summary, auto_generated: r.solution_summary_auto, configs: {}})
      : '<button data-help="lab.revealSolution" id="a-reveal" class="hint-btn">Reveal solution</button>'}</div>`;
  bindHints($("#results"));
  const rb = $("#a-reveal");
  if (rb) rb.onclick = async () => {
    if (!confirm("Reveal the full solution? This shows the root cause and the exact fix for every device.")) return;
    try { $("#solution-box").innerHTML = solutionPanel(await api(`/api/labs/${current}/solution`), true); }
    catch (e) { toast("Could not load the solution: " + e.message, "err"); }
  };
}
function faultPanel(f, heading) {
  return `<section class="solution-panel" data-help="lab.faultPanel"><h3>${esc(heading)}: ${esc(f.title)} <span class="tag">${esc(f.device)}</span></h3>
    <div class="md">${md(f.explanation)}</div><details><summary data-help="lab.faultConfig">Config that was applied to break the lab</summary><pre class="code">${esc(f.config)}</pre></details></section>`;
}
function solutionPanel(s, withConfigs = false) {
  const cfgs = withConfigs ? Object.entries(s.configs || {}) : [];
  return `<section class="solution-panel" data-help="lab.solutionPanel"><h3>Solution summary${s.auto_generated ? ' <span class="tag">auto-generated</span>' : ""}</h3>
    <div class="md">${md(s.summary)}</div>
    ${cfgs.length && !s.auto_generated ? `<h4>Solution config (lines to add)</h4>${cfgs.map(([d, c]) => `<p><b>${esc(d)}</b></p><pre class="code">${esc(c)}</pre>`).join("")}` : ""}</section>`;
}
async function loadHistory() {
  if (!current) return;
  const h = await api(`/api/history/${current}`);
  $("#history").innerHTML = h.length ? `<table><tr><th>When</th><th>Mode</th><th>Score</th><th>Hints</th><th>Type</th><th>Failed checks</th></tr>${h.slice().reverse().map((x) =>
    `<tr><td>${esc(x.ts)}</td><td>${esc(x.mode)}</td><td class="${x.passed ? "pass" : ""}">${x.earned}/${x.total} (${x.score_pct}%)</td><td>${x.hints_used == null ? "-" : `${x.hints_used}/${x.hints_total ?? "?"}`}</td><td class="small">${x.exam ? "exam" : x.fault ? "fault" : "lab"}</td><td class="small">${esc((x.failed || []).join(", "))}</td></tr>`).join("")}</table>
    <button data-help="lab.historyClear" class="hint-btn" id="hist-clear">Clear history</button>` : '<span class="muted">No checks yet.</span>';
  if ($("#hist-clear")) $("#hist-clear").onclick = async () => { await api(`/api/history/${current}`, {method: "DELETE"}); loadHistory(); loadLabs(); };
}

/* ---------------------------------------------------------------- builder */
function emptyDraft() {
  return {id: "my-new-lab", title: "My new lab", blueprint: ["3.2.b"], domain: "3.0 Infrastructure - Layer 3", difficulty: 2,
    platforms: ["iol", "iosv"], summary: "", author: "", version: "1",
    nodes: [{name: "R1", kind: "router", x: -150, y: 0, config: "interface %if0%\n ip address 10.0.12.1 255.255.255.0\n no shutdown\n"},
            {name: "R2", kind: "router", x: 150, y: 0, config: "interface %if0%\n ip address 10.0.12.2 255.255.255.0\n no shutdown\n"}],
    links: [{a: {node: "R1", port: 0}, b: {node: "R2", port: 0}}],
    task: "# Task title\n\nDescribe what the student must configure.\n", checks: [], solution: {R1: "", R2: ""},
    solution_summary: "**What was missing:** ...\n\n**Fix**\n\nR1:\n```\n...\n```\n\n**Why it works:** ...\n", hints: []};
}
function newDraft() { draft = emptyDraft(); draftSource = null; $("#b-replace").checked = false; renderForm(); syncYaml().then(() => validateDraft()); }
async function openInBuilder(id) {
  const {yaml, source} = await api(`/api/labs/${id}/source`);
  const {obj} = await api("/api/yaml/parse", {method: "POST", body: JSON.stringify({yaml})});
  draft = obj; draftSource = id;
  if (source === "builtin") { draft.id = draft.id + "-copy"; draft.title = draft.title + " (copy)"; toast("Built-in labs can't be changed. Editing a copy.", "", 6000); }
  $("#b-replace").checked = source === "user";
  location.hash = "builder"; show("builder"); renderForm(); syncYaml(); validateDraft();
}
$("#b-new").onclick = () => confirm("Discard the current draft?") && newDraft();
$("#b-load").onchange = (e) => { if (e.target.value) openInBuilder(e.target.value); e.target.value = ""; };
$$(".tab").forEach((t) => t.onclick = async () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t));
  $("#tab-form").hidden = t.dataset.tab !== "form"; $("#tab-yaml").hidden = t.dataset.tab !== "yaml";
  if (t.dataset.tab === "yaml") await syncYaml(); else renderForm();
});
const field = (help, label, path, value, type = "text", extra = "") =>
  `<label>${label}<input data-help="${help}" data-path="${path}" type="${type}" value="${esc(value ?? "")}" ${extra}></label>`;
function getPath(obj, path) { return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj); }
function setPath(obj, path, v) { const ks = path.split("."); const last = ks.pop(); const t = ks.reduce((o, k) => (o[k] ??= {}), obj); t[last] = v; }
function renderForm() {
  const d = draft; const names = d.nodes.map((n) => n.name);
  const nodeOpts = (sel) => names.map((n) => `<option ${n === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  const portOpts = (sel) => [0, 1, 2, 3].map((p) => `<option value="${p}" ${p === sel ? "selected" : ""}>port ${p} (%if${p}%)</option>`).join("");
  d.solution ??= {};
  $("#tab-form").innerHTML = `
  <fieldset><legend>General</legend><div class="grid">
    ${field("f.id", "Lab id", "id", d.id)}${field("f.title", "Title", "title", d.title)}
    <label>Domain<input data-help="f.domain" data-path="domain" list="domains" value="${esc(d.domain)}"><datalist id="domains">${DOMAINS.map((x) => `<option>${esc(x)}</option>`).join("")}</datalist></label>
    <label>Blueprint items<input data-help="f.blueprint" data-path="blueprint" data-type="csv" value="${esc((d.blueprint || []).join(", "))}"></label>
    <label>Difficulty<select data-help="f.difficulty" data-path="difficulty" data-type="int">${[1, 2, 3, 4, 5].map((i) => `<option ${i === d.difficulty ? "selected" : ""}>${i}</option>`).join("")}</select></label>
    <label>Platforms<select data-help="f.platforms" data-path="platforms" data-type="plat"><option value="iol,iosv" ${(d.platforms || []).length > 1 ? "selected" : ""}>IOL + IOSv</option>
      <option value="iol" ${(d.platforms || []).join() === "iol" ? "selected" : ""}>IOL only</option><option value="iosv" ${(d.platforms || []).join() === "iosv" ? "selected" : ""}>IOSv only</option></select></label>
    ${field("f.author", "Author", "author", d.author)}</div>
    <label>Summary<input data-help="f.summary" data-path="summary" value="${esc(d.summary)}"></label>
    <div class="grid task-edit"><label>Task (Markdown)<textarea data-help="f.task" data-path="task" id="task-src" rows="14">${esc(d.task)}</textarea></label>
      <div><div class="row-head small"><label class="inline">Student preview as
        <select data-help="f.preview" id="preview-plat"><option value="iol">IOL (Ethernet0/x)</option><option value="iosv">IOSv (GigabitEthernet0/x)</option></select></label></div>
        <div id="task-preview" class="task md preview"></div></div></div>
    <div class="muted small">Placeholders stay as <code>%if0%</code> in the lab file so it works on both images. Students always see real interface names.</div>
    <div class="grid"><label>Solution summary (Markdown: root cause, fix per device, why)<textarea data-help="f.solutionSummary" class="code" rows="8" data-path="solution_summary">${esc(d.solution_summary || "")}</textarea></label>
      <label>Hints (one per line, vaguest first)<textarea data-help="f.hints" rows="8" data-path="hints" data-type="lines">${esc((d.hints || []).join("\n"))}</textarea></label></div></fieldset>
  <fieldset><legend>Nodes</legend>${d.nodes.map((n, i) => `<div class="row"><div class="row-head">
      <input data-help="node.name" aria-label="Node name" data-path="nodes.${i}.name" data-rename="${esc(n.name)}" value="${esc(n.name)}" placeholder="name">
      <select data-help="node.kind" aria-label="Kind" data-path="nodes.${i}.kind"><option ${n.kind === "router" ? "selected" : ""}>router</option><option ${n.kind === "switch" ? "selected" : ""}>switch</option></select>
      <input data-help="node.x" aria-label="x" data-path="nodes.${i}.x" data-type="int" type="number" value="${n.x ?? 0}"><input data-help="node.y" aria-label="y" data-path="nodes.${i}.y" data-type="int" type="number" value="${n.y ?? 0}">
      <button data-help="node.remove" data-del="nodes.${i}" class="danger hint-btn">Remove</button></div>
      <div class="grid"><label>Starting config<textarea data-help="node.config" class="code" rows="7" data-path="nodes.${i}.config">${esc(n.config)}</textarea></label>
      <label>Solution (lines to add)<textarea data-help="node.solution" class="code" rows="7" data-path="solution.${n.name}">${esc(d.solution[n.name] || "")}</textarea></label></div></div>`).join("")}
    <button data-help="node.add" id="add-node">+ Add node</button></fieldset>
  <fieldset><legend>Links</legend>${d.links.map((l, i) => `<div class="row-head" style="margin:.3rem 0">
      <select data-help="link.node" aria-label="Node A" data-path="links.${i}.a.node">${nodeOpts(l.a.node)}</select><select data-help="link.port" aria-label="Port A" data-path="links.${i}.a.port" data-type="int">${portOpts(l.a.port)}</select> ↔
      <select data-help="link.node" aria-label="Node B" data-path="links.${i}.b.node">${nodeOpts(l.b.node)}</select><select data-help="link.port" aria-label="Port B" data-path="links.${i}.b.port" data-type="int">${portOpts(l.b.port)}</select>
      <button data-help="link.remove" data-del="links.${i}" class="danger hint-btn">Remove</button></div>`).join("")}
    <button data-help="link.add" id="add-link">+ Add link</button></fieldset>
  <fieldset><legend>Checks <span class="muted small">(need at least one live and one config check)</span></legend>${d.checks.map((c, i) => checkRow(c, i, nodeOpts)).join("")}
    <div class="toolbar"><select data-help="check.add" aria-label="Add check" id="add-check-tpl"><option value="">+ Add check from template…</option>
      ${templates.map((t) => `<option value="${t.name}">[${t.mode}] ${esc(t.title)}</option>`).join("")}<option value="__live">[live] Custom show/ping + regex</option><option value="__config">[config] Custom regex</option></select></div></fieldset>`;
  $$("#tab-form [data-path]").forEach((el) => el.addEventListener("change", onFormChange));
  const pp = $("#preview-plat"); pp.value = (d.platforms || ["iol"]).includes(localStorage.getItem("previewPlat")) ? localStorage.getItem("previewPlat") : (d.platforms || ["iol"])[0];
  const upd = () => { $("#task-preview").innerHTML = md(renderIf($("#task-src").value, pp.value)); };
  pp.onchange = () => { localStorage.setItem("previewPlat", pp.value); upd(); };
  $("#task-src").addEventListener("input", upd); upd();
  $$("#tab-form [data-del]").forEach((b) => b.onclick = () => { const [k, i] = b.dataset.del.split("."); draft[k].splice(+i, 1); renderForm(); scheduleValidate(); });
  $("#add-node").onclick = () => { let i = draft.nodes.length + 1; while (names.includes("R" + i)) i++; draft.nodes.push({name: "R" + i, kind: "router", x: 0, y: 150, config: ""}); renderForm(); scheduleValidate(); };
  $("#add-link").onclick = () => { draft.links.push({a: {node: names[0], port: 0}, b: {node: names[1] || names[0], port: 0}}); renderForm(); scheduleValidate(); };
  $("#add-check-tpl").onchange = (e) => {
    const v = e.target.value; if (!v) return;
    const id = `check-${draft.checks.length + 1}`, dev = names[0];
    if (v === "__live") draft.checks.push({id, device: dev, mode: "live", description: "", command: "show ", match: [""], hint: ""});
    else if (v === "__config") draft.checks.push({id, device: dev, mode: "config", description: "", match: [""], hint: ""});
    else { const t = templates.find((x) => x.name === v); const params = {}; t.params.forEach((p) => { if (p.default != null) params[p.name] = p.default; });
      draft.checks.push({id, template: v, device: dev, params, hint: ""}); }
    renderForm(); scheduleValidate();
  };
}
function checkRow(c, i, nodeOpts) {
  const t = c.template ? templates.find((x) => x.name === c.template) : null;
  const head = `<div class="row-head"><input data-help="check.id" aria-label="Check id" data-path="checks.${i}.id" value="${esc(c.id)}" placeholder="id">
    <select data-help="check.device" aria-label="Device" data-path="checks.${i}.device">${nodeOpts(c.device)}</select>
    <span class="tag">${t ? t.mode : (c.mode || "live")}</span><b data-help-text="${t ? esc(`Template ${t.name} (${t.mode} check): fill in the parameters and the command and regex are generated.`) : "Custom check: write the command and regexes yourself."}">${t ? esc(t.title) : "custom"}</b>
    <button data-help="check.remove" data-del="checks.${i}" class="danger hint-btn">Remove</button></div>`;
  let body;
  if (t) body = `<div class="grid">${t.params.map((p) => `<label title="${esc(p.description)}">${esc(p.name)}${p.required ? " *" : ""}
      <input data-help-text="${esc(p.description + (p.required ? " (required)" : " (optional)") + (p.default != null ? ", default " + p.default : ""))}" data-path="checks.${i}.params.${p.name}" value="${esc((c.params || {})[p.name] ?? "")}" placeholder="${esc(p.description)}"></label>`).join("")}</div>`;
  else body = `${c.mode === "config" ? "" : field("check.command", "Command (show/ping)", `checks.${i}.command`, c.command)}
      <label>Must match (regex per line)<textarea data-help="check.match" class="code" rows="2" data-path="checks.${i}.match" data-type="lines">${esc((c.match || []).join("\n"))}</textarea></label>
      <label>Must NOT match (regex per line)<textarea data-help="check.absent" class="code" rows="1" data-path="checks.${i}.absent" data-type="lines">${esc((c.absent || []).join("\n"))}</textarea></label>
      ${c.mode === "config" ? "" : field("check.minSuccess", "Ping min success %", `checks.${i}.min_success`, c.min_success, "number", 'data-type="intornull"')}`;
  return `<div class="row">${head}${body}<div class="grid">${field("check.description", "Description" + (t ? " (optional)" : ""), `checks.${i}.description`, c.description)}
    ${field("check.hint", "Hint", `checks.${i}.hint`, c.hint)}</div></div>`;
}
function onFormChange(e) {
  const el = e.target, path = el.dataset.path, type = el.dataset.type;
  let v = el.value;
  if (type === "int") v = parseInt(v, 10) || 0;
  else if (type === "intornull") v = v === "" ? null : parseInt(v, 10);
  else if (type === "csv") v = v.split(",").map((x) => x.trim()).filter(Boolean);
  else if (type === "lines") v = v.split("\n").filter((x) => x.trim());
  else if (type === "plat") v = v.split(",");
  if (el.dataset.rename !== undefined) { // node rename: carry links/checks/solution along
    const old = el.dataset.rename;
    draft.links.forEach((l) => { if (l.a.node === old) l.a.node = v; if (l.b.node === old) l.b.node = v; });
    draft.checks.forEach((c) => { if (c.device === old) c.device = v; });
    if (draft.solution && old in draft.solution) { draft.solution[v] = draft.solution[old]; delete draft.solution[old]; }
  }
  if (path.startsWith("solution.")) { draft.solution ??= {}; draft.solution[path.slice(9)] = v; }
  else setPath(draft, path, v);
  if (el.dataset.rename !== undefined) renderForm();
  scheduleValidate();
}
function cleanDraft() {
  const d = JSON.parse(JSON.stringify(draft));
  d.checks = (d.checks || []).map((c) => { const o = {}; for (const [k, v] of Object.entries(c)) {
    if (v === "" || v == null || (Array.isArray(v) && !v.length)) continue;
    if (k === "params") { const p = {}; for (const [pk, pv] of Object.entries(v)) if (pv !== "" && pv != null) p[pk] = pv; o.params = p; } else o[k] = v; } return o; });
  if (d.solution) { for (const k of Object.keys(d.solution)) if (!String(d.solution[k] || "").trim()) delete d.solution[k]; if (!Object.keys(d.solution).length) delete d.solution; }
  for (const k of ["author", "summary"]) if (d[k] === undefined) d[k] = "";
  if (!String(d.solution_summary || "").trim()) delete d.solution_summary;
  if (!(d.hints || []).length) delete d.hints;
  return d;
}
async function syncYaml() { const {yaml} = await api("/api/yaml/dump", {method: "POST", body: JSON.stringify({obj: cleanDraft()})}); $("#b-yaml").value = yaml; }
let vTimer = null;
function scheduleValidate() { clearTimeout(vTimer); vTimer = setTimeout(validateDraft, 500); }
$("#b-yaml").addEventListener("input", () => { clearTimeout(vTimer); vTimer = setTimeout(async () => {
  try { const {obj} = await api("/api/yaml/parse", {method: "POST", body: JSON.stringify({yaml: $("#b-yaml").value})}); draft = obj; validateDraft(true); }
  catch (e) { showValidation({ok: false, errors: [e.data?.error || e.message], warnings: [], results: []}); }
}, 600); });
function currentYaml(fromTab) { return fromTab || !$("#tab-yaml").hidden ? $("#b-yaml").value : null; }
async function validateDraft(fromYaml = false, strict = false) {
  let yaml = currentYaml(fromYaml);
  if (yaml === null) { await syncYaml(); yaml = $("#b-yaml").value; }
  const rep = await api("/api/validate", {method: "POST", body: JSON.stringify({yaml, strict, fixtures_from: draftSource})});
  showValidation(rep); return rep;
}
function showValidation(rep) {
  const v = $("#b-validation");
  v.className = "validation " + (rep.ok ? "ok" : "bad");
  v.innerHTML = (rep.ok ? '<b class="pass">Valid</b>' : '<b class="fail">Problems found</b>') +
    (rep.errors.length ? `<ul>${rep.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : "") +
    (rep.results.length ? `<div class="small">${rep.results.map((r) => `${r.platform}/${r.mode}: solution ${r.solution_pct}% · starting config ${r.blank_pct}%`).join(" &nbsp;|&nbsp; ")}</div>` : "") +
    (rep.warnings.length ? `<div class="small muted">${rep.warnings.map(esc).join("<br>")}</div>` : "");
}
$("#b-validate").onclick = async () => { const r = await validateDraft(false, true); toast(r.ok ? "Lab passes offline tests" : "Offline test found problems", r.ok ? "ok" : "err"); };
$("#b-save").onclick = async () => {
  let yaml = currentYaml(); if (yaml === null) { await syncYaml(); yaml = $("#b-yaml").value; }
  try {
    const rep = await api("/api/user-labs", {method: "POST", body: JSON.stringify({yaml, replace: $("#b-replace").checked, fixtures_from: draftSource})});
    showValidation(rep); toast(`Saved "${rep.title}" to your labs`, "ok"); $("#b-replace").checked = true; await loadLabs();
  } catch (e) { if (e.data && e.data.errors) showValidation(e.data); toast("Not saved: " + e.message, "err", 10000); }
};
$("#b-testlive").onclick = async () => {
  const id = draft.id;
  if (!labs.find((l) => l.id === id)) return toast("Save the lab first, then run the live test.", "err");
  if (!confirm("Build a temporary copy in CML with the solution applied, grade it, then delete it? This takes a few minutes.")) return;
  try {
    const {job_id} = await api(`/api/labs/${id}/test-live`, {method: "POST"});
    toast("Live test started…");
    const j = await pollJob(job_id, (j) => showValidation({ok: true, errors: [], warnings: j.log.slice(-6), results: []}));
    if (j.state === "error") toast("Live test failed: " + j.error, "err", 12000);
    else { const r = j.result; showValidation({ok: r.passed, errors: r.results.filter((x) => !x.passed).map((x) => `${x.id}: ${x.details.join("; ")}`), warnings: r.notes, results: []});
      toast(`Live test (${r.mode}): ${r.score_pct}%`, r.passed ? "ok" : "err", 10000); }
  } catch (e) { toast(e.message, "err"); }
};
$("#b-cml").onclick = async () => {
  $("#cml-dialog").showModal(); $("#cml-list").textContent = "Loading…";
  try {
    const list = await api("/api/cml/labs");
    $("#cml-list").innerHTML = list.length ? `<table>${list.map((l) => `<tr><td>${esc(l.title)}</td><td class="muted">${l.nodes ?? "?"} nodes</td><td><button data-help="cml.use" data-cml="${esc(l.id)}">Use</button></td></tr>`).join("")}</table>` : "No labs in CML.";
    $$("[data-cml]").forEach((b) => b.onclick = async () => {
      try { const r = await api("/api/cml/draft", {method: "POST", body: JSON.stringify({lab_id: b.dataset.cml})});
        draft = r.obj; draftSource = null; $("#cml-dialog").close(); renderForm(); syncYaml(); validateDraft(); toast(r.warnings.join("\n"), "", 9000);
      } catch (e) { toast(e.message, "err"); }
    });
  } catch (e) { $("#cml-list").textContent = e.message; }
};
$("#cml-close").onclick = () => $("#cml-dialog").close();

/* ---------------------------------------------------------------- AI (optional) */
$("#ai-copy").onclick = () => copyPrompt($("#ai-desc").value);
$("#ai-go").onclick = async () => {
  $("#ai-log").textContent = "Starting…";
  try {
    const {job_id} = await api("/api/ai/generate", {method: "POST", body: JSON.stringify({description: $("#ai-desc").value})});
    const j = await pollJob(job_id, (j) => { $("#ai-log").textContent = j.log.join("\n"); });
    if (j.state === "error") return toast("AI generation failed: " + j.error, "err", 12000);
    const r = j.result;
    if (!r.lab_yaml) return toast("The AI did not return a usable lab.", "err");
    const {obj} = await api("/api/yaml/parse", {method: "POST", body: JSON.stringify({yaml: r.lab_yaml})});
    draft = obj; draftSource = null; location.hash = "builder"; show("builder"); renderForm(); syncYaml(); validateDraft();
    toast(r.ok ? "Generated lab passed validation. Review it, then Save." : "Generated lab still has problems after retries. Review the errors before saving.", r.ok ? "ok" : "err", 9000);
  } catch (e) { toast(e.message, "err", 10000); }
};

/* ---------------------------------------------------------------- settings */
let presets = {};
async function loadSettings() {
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const k of ["cml_url", "username", "console_host", "console_port", "grading_mode", "platform", "node_limit", "ai_base_url", "ai_model"]) f[k].value = s[k] ?? "";
  f.verify_tls.value = s.verify_tls === false ? "false" : "true";
  f.show_help.checked = s.show_help !== false; if (window.Help) Help.setVisible(f.show_help.checked);
  f.password.value = ""; f.password.placeholder = s.password_set ? "(saved - leave blank to keep)" : "";
  f.ai_api_key.value = ""; f.ai_api_key.placeholder = s.ai_api_key_set ? "(saved - leave blank to keep)" : "";
  presets = await api("/api/ai/presets");
  $("#ai-preset").innerHTML = `<option value="">(none)</option>` + Object.entries(presets).map(([k, p]) => `<option value="${k}" ${k === s.ai_preset ? "selected" : ""}>${esc(p.label)}</option>`).join("");
}
$("#ai-preset").onchange = (e) => { const p = presets[e.target.value]; if (p) { const f = $("#settings-form"); f.ai_base_url.value = p.base_url; f.ai_model.value = p.model; } };
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {cml_url: f.cml_url.value, username: f.username.value, password: f.password.value, verify_tls: f.verify_tls.value,
    console_host: f.console_host.value, console_port: Number(f.console_port.value) || 22, grading_mode: f.grading_mode.value,
    platform: f.platform.value, node_limit: Number(f.node_limit.value) || 20, remember_password: f.remember_password.checked,
    ai_preset: f.ai_preset.value, ai_base_url: f.ai_base_url.value, ai_model: f.ai_model.value, ai_api_key: f.ai_api_key.value,
    remember_ai_key: f.remember_ai_key.checked, show_help: f.show_help.checked};
  try {
    const r = await api("/api/settings", {method: "POST", body: JSON.stringify(body)});
    if (window.Help) Help.setVisible(r.show_help !== false);
    toast((r.settings_file ? `Settings saved (${r.settings_file})` : "Settings saved (memory only)") +
      (body.remember_password ? (r.keyring_saved ? "\nCML password stored in OS keyring" : "\nOS keyring unavailable") : ""), "ok");
    loadSettings();
  } catch (err) { toast("Settings not saved: " + err.message, "err", 9000); }
});

/* ---------------------------------------------------------------- version check (stale cache / app updated while open) */
async function versionCheck() {
  const page = window.APP_VERSION;
  if (page && page !== APP_JS_VERSION) {
    banner(`This page (v${page}) loaded an old cached script (v${APP_JS_VERSION}). Press Ctrl+Shift+R (or Ctrl+F5) to reload.`);
    return;
  }
  const h = await api("/api/health");
  if (page && h.version && h.version !== page && !versionCheck.warned) {
    versionCheck.warned = true;
    banner(`ENCOR Lab Builder was updated to v${h.version} while this page was open (page is v${page}). Reload the page (F5) to use it.`);
  }
}

/* ---------------------------------------------------------------- boot */
(async () => {
  const step = async (name, fn) => { try { await fn(); } catch (e) { if (!e.shown) banner(`Startup step "${name}" failed: ${e.message}`); } };
  await step("version check", versionCheck);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) versionCheck().catch(() => {}); });
  await step("settings", async () => { const s = await api("/api/settings"); if (window.Help) Help.setVisible(s.show_help !== false); });
  await step("check templates", async () => { templates = await api("/api/templates"); });
  await step("lab list", loadLabs);
  const v = (location.hash || "#labs").slice(1);
  show(["labs", "builder", "settings", "ai"].includes(v) ? v : "labs");
})();

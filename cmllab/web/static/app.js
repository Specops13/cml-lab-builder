"use strict";
/* CML Lab Builder UI - vanilla JS, no build step. */
const APP_JS_VERSION = "3.3.3";  // must equal cmllab.__version__ (tests/test_packaging.py)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
/* links that come from data (CML, GitHub, lab files) are only ever http(s): never javascript: or data: URLs */
const safeUrl = (u) => /^https?:\/\//i.test(String(u ?? "")) ? String(u) : "#";
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
/* inline SVG icons (no icon font / CDN; CSP-safe). 24x24, stroke = currentColor */
const ICONS = {
  check: '<path d="M20 6 9 17l-5-5"/>', alert: '<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  block: '<circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/>', help: '<circle cx="12" cy="12" r="9"/><path d="M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3m.1 4h.01"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>', trash: '<path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5"/>', x: '<path d="M18 6 6 18M6 6l12 12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8h.01"/>', play: '<path d="m7 4 13 8-13 8z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>', upload: '<path d="M12 16V4m-5 5 5-5 5 5M4 20h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>', book: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/>',
  memory: '<rect x="3" y="7" width="18" height="10" rx="1.5"/><path d="M7 7v10m5-10v10m5-10v10M5 17v3m14-3v3"/>',
};
function icon(name, cls = "") {
  return `<svg class="icon${cls ? " " + cls : ""}" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name] || ""}</svg>`;
}
const DOMAINS = ["1.0 Architecture", "2.0 Virtualization", "3.0 Infrastructure - Layer 2", "3.0 Infrastructure - Layer 3",
  "3.0 Infrastructure - Wireless", "3.0 Infrastructure - IP Services", "4.0 Network Assurance", "5.0 Security", "6.0 Automation"];
let labs = [], current = null, templates = [], draft = null, draftSource = null, statusTimer = null;
/* RAM estimate tag: neutral for every lab, red + the words "RAM heavy" at/above the Settings threshold (text, not only color). */
function ramTag(r) {
  if (!r) return "";
  return `<span data-help="lab.ram" class="tag ram${r.heavy ? " ram-heavy" : ""}" title="${esc(r.tooltip)}">${r.heavy ? "RAM heavy · " : "RAM "}${esc(r.label)}</span>`;
}
const walkTag = (l) => l.type === "walkthrough" ? '<span class="tag walk">walkthrough</span>' : "";
/* where a lab came from: library labs need no tag; labs you made or imported yourself say so */
const srcTag = (l) => (l.library || l.source === "builtin") ? "" : '<span class="tag user">imported</span>';
// completed by hand (3.3.3, for a buggy check): recorded apart from a graded pass, counted by courses, not by mastery
const manTag = (what = "lab") => `<span class="tag manual" title="This ${what} was marked done by hand, not by a graded check">marked manually</span>`;
const doneTags = (l) => l.walkthrough
  ? (l.walkthrough.completed ? '<span class="tag ok">completed</span>' + (l.walkthrough.completed_manually ? manTag() : "") : ((l.walkthrough.required_done || l.walkthrough.required_passed) ? `<span class="tag">${l.walkthrough.required_done ?? l.walkthrough.required_passed}/${l.walkthrough.required} steps</span>` : ""))
  : (l.marked_manually ? '<span class="tag ok">completed</span>' + manTag() : l.solved ? '<span class="tag ok">solved</span>' : (l.best != null ? `<span class="tag">best ${l.best}%</span>` : ""));
const updTag = (l) => l.update_available ? '<span data-help="lab.updateTag" class="tag warn">update available</span>' : "";
let migration = null, libraryUrl = "", libStarter = [];
let labRecs = [], libIdx = null, libRecs = [], libCards = [], libRaf = 0;
// library page state; the view, the topic selection and the collapsed groups are remembered (localStorage)
const LIB_PREFS = "cmllab.library";
const libPrefs = (() => { try { const p = JSON.parse(localStorage.getItem(LIB_PREFS) || "{}");
  return {view: p.view === "list" ? "list" : "grouped", topics: Array.isArray(p.topics) ? p.topics.map(String) : [], collapsed: Array.isArray(p.collapsed) ? p.collapsed.map(String) : []};
} catch (e) { return {view: "grouped", topics: [], collapsed: []}; } })();
let libQuery = {q: "", kind: "", status: "", course: "", noheavy: false, topics: libPrefs.topics.slice()};
let libTopicMeta = new Map(), libGroups = [];
function libSavePrefs() { try { localStorage.setItem(LIB_PREFS, JSON.stringify({view: libPrefs.view, topics: libQuery.topics, collapsed: libPrefs.collapsed})); } catch (e) { /* private mode */ } }

/* ---------------------------------------------------------------- error banner */
function banner(msg) {
  const b = document.getElementById("error-banner");
  if (!b) return;
  if (!msg) { b.hidden = true; b.innerHTML = ""; return; }
  const line = document.createElement("div");
  line.textContent = msg;
  if (b.hidden) {
    b.innerHTML = '<button data-help-text="Hide this message" class="hint-btn" data-dismiss>Dismiss</button>' +
      "<b>Something went wrong.</b> Try a hard refresh (Ctrl+Shift+R / Ctrl+F5). Details (also in the F12 console):";
    b.querySelector("[data-dismiss]").addEventListener("click", () => banner());
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
  // CSRF protection (web/security.py): state-changing requests must carry this header, which other sites cannot send
  o.headers = Object.assign({"X-CMLLab-Request": "1"}, o.headers || {});
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

/* Same placeholder rules as cmllab/platforms.py (kept in sync by tests/test_placeholders.py). */
const IFNAMES = {iol: ["Ethernet0/", "Et0/"], iosv: ["GigabitEthernet0/", "Gi0/"]};
function renderIf(text, plat) { return String(text || "").replace(/%if(\d)(s?)%/g, (_, n, sh) => IFNAMES[plat][sh ? 1 : 0] + n); }

/* ---------------------------------------------------------------- navigation + theme */
const VIEWS = ["labs", "progress", "builder", "settings", "ai"];
function show(view) {
  for (const v of VIEWS) $(`#view-${v}`).hidden = v !== view;
  $$("nav>a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $("#more-menu").hidden = true;
  if (view === "settings") loadSettings();
  if (view === "progress") loadProgress();
  if (view === "builder" && !draft) newDraft();
}
$$("[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); location.hash = a.dataset.view; show(a.dataset.view); }));
$("#more-btn").onclick = (e) => { e.stopPropagation(); $("#more-menu").hidden = !$("#more-menu").hidden; $("#more-btn").setAttribute("aria-expanded", String(!$("#more-menu").hidden)); };
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
    if (rep.kind === "course") { await afterCourseInstall(rep); return; }
    toast(`Imported "${rep.title}"` + (rep.warnings.length ? `\nNote: ${rep.warnings.join("\n")}` : ""), "ok", 7000);
    try { await loadLabs(); await selectLab(rep.lab_id); } catch (e) { return; }  // import succeeded; banner explains the list error
    const li = $("#lab-list li.sel"); if (li) li.scrollIntoView({block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"});
  } catch (err) {
    const d = err.data || {};
    if (err.status === 409 && confirm(d.lab_id ? `A lab with id "${d.lab_id}" is already imported. Replace it?` : `${(d.errors || []).join("\n")}\n\nReplace the existing labs?`)) return importFile(file, true);
    toast(`Could not import ${file.name}:\n- ` + ((d.errors && d.errors.length) ? d.errors.join("\n- ") : err.message), "err", 15000);
  }
}

/* ---------------------------------------------------------------- catalog */
async function loadLabs() {
  let data;
  try { data = await api("/api/labs"); } catch (e) { banner(`Could not load the lab list: ${e.message}`); e.shown = true; throw e; }
  labs = data.labs;
  labRecs = labs.map((l) => Fuzzy.prepare({title: [l.title, 3], id: [l.id, 2.5], blueprint: [l.blueprint.join(", "), 2], domain: [l.domain, 2],
    tags: [[l.type, l.track, Fuzzy.nodeTags(l.node_types), (l.platforms || []).join(" "), (l.ram && l.ram.heavy) ? "ram heavy" : ""].join(" "), 1.5],
    summary: [l.summary, 1]}));
  migration = data.migration || null;
  renderMigration();
  document.querySelector("aside.catalog").classList.toggle("no-labs", !labs.length);
  if (!labs.length && !current && !$("#library")) renderEmpty();
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
  const q = $("#f-search").value, dom = $("#f-domain").value, diff = $("#f-diff").value, src = $("#f-source").value;
  const crs = courseList.find((c) => c.id === $("#f-course").value);
  const hits = new Map();
  let items = labs;
  if (Fuzzy.tokens(q).length) items = Fuzzy.search(q, labRecs).map((r) => { hits.set(labs[r.i].id, r.hits); return labs[r.i]; });  // ranked
  items = items.filter((l) => (!dom || l.domain === dom) && (!diff || String(l.difficulty) === diff) &&
    (!src || (src === "library" ? (l.library || l.source === "builtin") : !(l.library || l.source === "builtin"))));
  if (crs) { const order = crs.labs.map((x) => x.id); items = items.filter((l) => order.includes(l.id)); if (!hits.size) items.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id)); }
  const hl = (l, k) => Fuzzy.highlight(l[k], (hits.get(l.id) || {})[k], esc);
  $("#lab-list").innerHTML = items.map((l) => `<li data-help="lab.item" data-id="${esc(l.id)}" class="${l.id === current ? "sel" : ""}">
    <b>${hl(l, "title")}</b><br>
    ${walkTag(l)}<span class="tag">${"★".repeat(l.difficulty)}</span><span class="tag">${l.nodes} nodes</span>${ramTag(l.ram)}<span class="tag">${esc(l.blueprint.join(", "))}</span>
    ${srcTag(l)}${updTag(l)}${l.fault_active ? '<span class="tag warn">fault active</span>' : ""}${doneTags(l)}
    <div class="muted small">${hl(l, "summary")}</div></li>`).join("") || `<li class="muted">${labs.length ? (q.trim() ? `No labs match "${esc(q.trim())}". Try fewer or shorter words, or clear the filters (Esc clears the search).` : "No labs match the filters.") : "Your labs will show up here."}</li>`;
  $$("#lab-list li[data-id]").forEach((li) => li.addEventListener("click", () => selectLab(li.dataset.id)));
}
["#f-search", "#f-domain", "#f-diff", "#f-source", "#f-course"].forEach((s) => $(s).addEventListener("input", renderList));

/* ---------------------------------------------------------------- first run (no labs) + labs kept from 1.x */
function renderEmpty(note = "") {
  $("#lab-detail").innerHTML = `<div class="welcome" data-help="lab.empty">
    <div class="welcome-hero"><h2>Welcome to CML Lab Builder</h2>
      <p class="lead">Hands-on CCNP ENCOR labs for your CML server. Pick a way to get your first labs. It takes a few seconds.</p></div>
    <div class="choices">
      <div class="choice rec"><span class="tag ok">Recommended</span><h3>Start with the basics</h3>
        <p>Six small core labs: VLANs and STP, EtherChannel, EIGRP, OSPF, BGP and HSRP.</p>
        <ul id="e-starter-list" class="starter-list muted small"><li>Loading the list…</li></ul>
        <button data-help="lab.starter" id="e-starter" class="primary big">Install recommended starter set</button></div>
      <div class="choice"><h3>Follow a course</h3>
        <p>Courses put labs in a sensible order. <b>Install all</b> gets every lab of a course in one click.</p>
        <p class="muted small">You can also pick single labs; each shows its size and how much CML RAM it needs.</p>
        <button data-help="lab.browse" id="e-browse" class="big">${icon("book")}Browse library &amp; courses</button></div>
      <div class="choice"><h3>Got a lab file?</h3>
        <p>Import a .cmllab or .cmlcourse file (or an older .encorlab / .encorcourse) someone shared with you, or drop it anywhere on this page.</p>
        <button data-help="import.button" id="e-import" class="big">⬆ Import a .cmllab file</button></div>
    </div>
    <div id="e-note">${note}</div>
    <p id="e-next" class="muted small welcome-foot"></p></div>`;
  $("#e-starter").onclick = () => installStarter($("#e-starter"));
  $("#e-browse").onclick = () => openLibrary(true);
  $("#e-import").onclick = () => $("#import-file").click();
  fillWelcome();
}
/* best effort: the starter labs with size and RAM, and a hint when no CML server is set yet */
async function fillWelcome() {
  api("/api/settings").then((s) => {
    const n = $("#e-next"); if (!n) return;
    n.innerHTML = s.cml_url ? "Labs download from the online lab library, so the app itself stays small."
      : `Next step: add your CML server under <a data-help="lab.setup" href="#settings">Settings</a> so you can deploy the labs.`;
    const a = $("a", n); if (a) a.onclick = (e) => { e.preventDefault(); location.hash = "settings"; show("settings"); };
  }).catch(() => {});
  const ul = $("#e-starter-list");
  try {
    const idx = await api("/api/library");
    const set = idx.items.filter((it) => it.kind === "lab" && it.starter);
    if (!$("#e-starter-list")) return;
    if (!set.length) { ul.remove(); return; }
    const kb = set.reduce((t, it) => t + it.size, 0) / 1024;
    ul.innerHTML = set.map((it) => `<li><span>${esc(it.title)}</span>${it.ram_gb ? `<span class="tag ram">RAM ~${Math.round(it.ram_gb)} GB</span>` : ""}</li>`).join("") +
      `<li class="total">${set.length} labs · ${kb.toFixed(0)} KB download</li>`;
    $("#e-starter").textContent = `Install recommended starter set (${set.length} labs)`;
  } catch (e) {
    if (!$("#e-starter-list")) return;
    ul.remove();
    const box = $("#e-note");
    if (box) { box.innerHTML = offlineNote(libErr(e)); const a = $("[data-retry]", box); if (a) a.onclick = (ev) => { ev.preventDefault(); renderEmpty(); }; }
  }
}
function offlineNote(msg) {
  return `<div class="notice" data-help="lab.offline"><b>The lab library can't be reached right now.</b> Are you offline?
    Everything else keeps working. <a data-help="lab.retry" href="#" data-retry="1">Try again</a>, import a .cmllab file,
    or point Settings &gt; Library URL at another copy of the library.</div>
    <div class="muted small">Could not reach the lab library: ${esc(msg)}</div>`;
}
function libErr(e) { const d = e.data || {}; return (d.errors && d.errors.length) ? d.errors.join("; ") : e.message; }
async function installStarter(btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Installing…"; }
  try {
    const r = await api("/api/library/install-set", {method: "POST", body: JSON.stringify({starter: true})});
    const failed = Object.entries(r.failed || {});
    toast(`Installed ${r.installed.length} lab(s)` + (r.skipped.length ? `, ${r.skipped.length} already installed` : "") +
      (failed.length ? `\nFailed: ${failed.map(([k, v]) => `${k}: ${v}`).join("\n")}` : ""), failed.length ? "err" : "ok", 9000);
    current = null; applyCatalog(); await loadLabs();
    if (labs.length && !$("#library")) selectLab(labs[0].id);
    if ($("#library")) loadLibrary();
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = "Install recommended starter set"; }
    const box = $("#e-note") || $("#lib-items");
    if (box) { box.innerHTML = offlineNote(libErr(e)); const a = $("[data-retry]", box); if (a) a.onclick = (ev) => { ev.preventDefault(); installStarter(btn); }; }
    else toast("Could not install the starter set: " + libErr(e), "err", 12000);
  }
}
function renderMigration() {
  const b = $("#mig-banner"); if (!b) return;
  const m = migration;
  if (!m || m.state !== "pending" || !m.pending.length) { b.hidden = true; b.innerHTML = ""; return; }
  b.hidden = false;
  b.innerHTML = `<span data-help="mig.banner"><b>${m.pending.length} lab(s) from your previous version</b> are not installed yet
    (they now come from the lab library)${m.pending_with_data.length ? `, including ${m.pending_with_data.length} with your results history` : ""}.
    Your history and progress are kept and link up again as soon as the labs are back.${m.last_error ? ` <span class="muted">Last try: ${esc(m.last_error)}</span>` : ""}</span>
    <button data-help="mig.retry" id="mig-retry" class="primary">Restore now</button><button data-help="mig.dismiss" id="mig-dismiss" class="hint-btn">Dismiss</button>`;
  $("#mig-retry").onclick = async () => {
    $("#mig-retry").disabled = true; $("#mig-retry").textContent = "Restoring…";
    try { migration = await api("/api/migration/restore", {method: "POST"});
      toast(migration.state === "pending" ? `Still missing: ${migration.pending.join(", ")}` : "Your labs are back.", migration.state === "pending" ? "err" : "ok", 9000);
    } catch (e) { toast(e.message, "err"); }
    await loadLabs();
  };
  $("#mig-dismiss").onclick = async () => {
    if (!confirm("Stop offering to restore these labs? You can still install them from the library at any time; your history is kept.")) return;
    migration = await api("/api/migration/dismiss", {method: "POST"}); renderMigration();
  };
}
function libNote(id) {
  const l = labs.find((x) => x.id === id);
  return l && l.update_available ? `<div class="notice" data-help="lab.update">A newer version of this lab is in the library.
    <button data-help="lab.update" id="a-update" class="primary" data-id="${esc(id)}">Update lab</button> <span class="muted small">Your history and progress are kept;
    changes you made to the lab's files are replaced.</span></div>` : "";
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("#a-update"); if (!b) return;
  b.disabled = true;
  try { const r = await api("/api/library/install-set", {method: "POST", body: JSON.stringify({ids: [b.dataset.id], updates: true})});
    toast(r.installed.length ? "Lab updated" : `Not updated: ${Object.values(r.failed).join("; ") || "already current"}`, r.installed.length ? "ok" : "err");
    await loadLabs(); selectLab(b.dataset.id);
  } catch (err) { b.disabled = false; toast("Update failed: " + libErr(err), "err", 12000); }
});
async function deleteLab(id, title) {
  if (!confirm(`Delete the lab "${title}" from this app? (It is not removed from CML.) You can install it again from the library.`)) return;
  const clear = confirm("Also delete your results history and progress for this lab?\n\nOK = delete history too, Cancel = keep it (it links up again if you re-install the lab).");
  try { await api(`/api/user-labs/${encodeURIComponent(id)}?clear_history=${clear}`, {method: "DELETE"}); toast("Lab deleted" + (clear ? " with its history" : " (history kept)"), "ok"); current = null; applyCatalog();
    $("#lab-detail").innerHTML = '<div class="empty">Select a lab, or import one.</div>'; loadLabs(); } catch (e) { toast(e.message, "err"); }
}

/* ---------------------------------------------------------------- courses + online library */
let courseList = [];
const LIB_DEFAULT = "https://raw.githubusercontent.com/Specops13/cml-lab-builder/main/library/index.json";
async function loadCourses() {
  try { courseList = (await api("/api/courses")).courses; } catch (e) { courseList = []; }
  const sel = $("#f-course"), cur = sel.value;
  sel.innerHTML = `<option value="">No course filter</option>` + courseList.map((c) => `<option value="${esc(c.id)}" ${c.id === cur ? "selected" : ""}>Course: ${esc(c.title)} (${c.solved}/${c.total})</option>`).join("");
  return courseList;
}
async function afterCourseInstall(rep) {
  toast(`Installed course "${rep.title}": ${rep.labs.length} labs` + (rep.installed.length ? `, ${rep.installed.length} installed` : "") +
    (rep.warnings.length ? `\nNote: ${rep.warnings.join("\n")}` : ""), "ok", 8000);
  try { await loadLabs(); } catch (e) { /* banner shown */ }
  await loadCourses(); $("#f-course").value = rep.course_id; renderList();
  if ($("#library")) await openLibrary(!!$("#lib-cards"));
}
$("#lib-btn").onclick = () => openLibrary(true);
/* Collapsible lab list (3.3.1): hides the left column so the lab / walkthrough directions get the full width.
   The choice is remembered (localStorage "cmllab.catalog" = "open" | "collapsed"); with no choice saved, the list
   collapses by itself in narrow windows (<= 900 px, where it would sit above the directions) once a lab is open. */
const CATALOG_KEY = "cmllab.catalog", narrowMq = window.matchMedia("(max-width: 900px)");
function catalogPref() { try { return localStorage.getItem(CATALOG_KEY); } catch { return null; } }
function catalogCollapsed() {
  if (!current) return false;                       // nothing to read yet: the list is the page
  const pref = catalogPref();
  return pref === "collapsed" || pref === "open" ? pref === "collapsed" : narrowMq.matches && !!current;
}
function applyCatalog() {
  const aside = $("#catalog"), btn = $("#catalog-toggle"); if (!aside || !btn) return;
  const collapsed = catalogCollapsed();
  aside.hidden = collapsed;
  btn.hidden = !current;
  $("#view-labs").classList.toggle("catalog-collapsed", collapsed);
  btn.setAttribute("aria-expanded", String(!collapsed));
  btn.querySelector(".lbl").textContent = collapsed ? "Show lab list" : "Hide lab list";
  btn.title = collapsed ? "Show the lab list again" : "Hide the lab list so the directions get the full width";
}
function setCatalog(collapsed) {
  try { localStorage.setItem(CATALOG_KEY, collapsed ? "collapsed" : "open"); } catch { /* private mode: this page only */ }
  applyCatalog();
}
$("#catalog-toggle").onclick = () => setCatalog(!catalogCollapsed());
narrowMq.addEventListener("change", applyCatalog);
applyCatalog();
async function openLibrary(fetchIndex) {
  current = null; renderList(); applyCatalog();
  await loadCourses();
  const url = libraryUrl || LIB_DEFAULT;
  $("#lab-detail").innerHTML = `<div id="library">
    <div class="toolbar"><h2 style="margin:0">Library &amp; courses</h2></div>
    <h3 data-help="lib.courses">Your courses</h3><div id="lib-courses"></div>
    <h3 data-help="lib.online">Online library</h3>
    <div class="toolbar"><input data-help="lib.url" id="lib-url" style="flex:1;min-width:20em" aria-label="Library index URL" value="${esc(url)}">
      <button data-help="lib.load" id="lib-load">Load library</button><button data-help="lib.default" id="lib-default" class="hint-btn">Default</button></div>
    <div class="muted small">The address is saved in Settings &gt; Library URL; changing it here only applies until you reload the page.</div>
    <div id="lib-search-bar" class="toolbar lib-search-bar" hidden>
      <input data-help="lib.search" id="lib-search" type="search" autocomplete="off" spellcheck="false" aria-label="Search the library"
        placeholder="Search the library: title, id, topic, platform, node type…  ( / or Ctrl+K )">
      <select data-help="lib.fKind" id="lib-kind" aria-label="Kind"><option value="">Labs and courses</option><option value="lab">Labs</option><option value="course">Courses</option></select>
      <select data-help="lib.fStatus" id="lib-status" aria-label="Status"><option value="">Any status</option><option value="installed">Installed</option><option value="new">Not installed</option><option value="update">Update available</option></select>
      <select data-help="lib.fCourse" id="lib-course" aria-label="Course"><option value="">Any course</option></select>
      <label class="small"><input data-help="lib.fHeavy" type="checkbox" id="lib-noheavy"> Hide RAM heavy</label>
      <span class="sep"></span><span id="lib-count" class="muted small" aria-live="polite"></span>
      <span class="seg" role="group" aria-label="Layout"><button data-help="lib.viewGrouped" id="lib-view-grouped" type="button" aria-pressed="true">Grouped by topic</button><button data-help="lib.viewList" id="lib-view-list" type="button" aria-pressed="false">List</button></span></div>
    <div id="lib-topics" class="lib-topics" role="group" aria-label="Filter by topic" hidden></div>
    <div id="lib-items" class="muted">Click "Load library" to see the labs and courses published in the project repository.</div>
    <h3 data-help="lib.fromUrl">Install from a URL</h3>
    <div class="toolbar"><input data-help="lib.fileUrl" id="lib-file-url" style="flex:1;min-width:20em" placeholder="https://…/my-lab.cmllab or .cmlcourse" aria-label="File URL">
      <input data-help="lib.sha" id="lib-sha" style="width:22em" placeholder="sha256 (recommended)" aria-label="Expected sha256">
      <button data-help="lib.installUrl" id="lib-install-url">Install</button></div></div>`;
  renderCourses();
  libBindFilters();
  $("#lib-load").onclick = () => loadLibrary();
  $("#lib-default").onclick = () => { $("#lib-url").value = libraryUrl || LIB_DEFAULT; loadLibrary(); };
  $("#lib-install-url").onclick = () => libInstall({url: $("#lib-file-url").value.trim(), sha256: $("#lib-sha").value.trim()});
  if (fetchIndex) loadLibrary();
}
function renderCourses() {
  const box = $("#lib-courses"); if (!box) return;
  box.innerHTML = courseList.length ? courseList.map((c) => `<div class="course card" data-help="lib.course">
    <div class="toolbar"><b>${esc(c.title)}</b><span class="tag">${c.solved}/${c.total} done</span>${ramTag(c.ram)}<span class="sep"></span>
      ${c.next ? `<button data-help="lib.continue" class="primary" data-open="${esc(c.next)}">Continue: ${esc(c.next)}</button>` : '<span class="tag ok">complete</span>'}
      <button data-help="lib.filter" data-filter="${esc(c.id)}">Show in list</button>
      <button data-help="lib.removeCourse" class="danger" data-rmcourse="${esc(c.id)}" data-bundled="${c.bundled.length}">Remove</button></div>
    ${bar(c.pct)}
    ${c.description ? `<div class="muted small">${esc(c.description)}</div>` : ""}
    <ol>${c.labs.map((l) => `<li>${l.available ? `<a data-help="lib.courseLab" href="#" data-open="${esc(l.id)}">${esc(l.title)}</a>` : `${esc(l.id)} <span class="tag warn">missing</span>`}
      ${l.type === "walkthrough" ? walkTag(l) : ""}${ramTag(l.ram)}${l.solved ? `<span class="tag ok">${l.type === "walkthrough" || l.marked_manually ? "completed" : "solved"}</span>${l.marked_manually ? manTag() : ""}` : (l.best != null ? `<span class="tag">best ${l.best}%</span>` : "")}</li>`).join("")}</ol></div>`).join("")
    : `<div class="muted">No courses yet. Install one from the online library below, or import a .encorcourse file.</div>`;
  $$("#lib-courses [data-open]").forEach((b) => b.addEventListener("click", (e) => { e.preventDefault(); selectLab(b.dataset.open); }));
  $$("#lib-courses [data-filter]").forEach((b) => b.addEventListener("click", () => { $("#f-course").value = b.dataset.filter; renderList(); }));
  $$("#lib-courses [data-rmcourse]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Remove the course "${b.dataset.rmcourse}"? Your history is kept.`)) return;
    const labsToo = Number(b.dataset.bundled) > 0 && confirm(`Also delete the ${b.dataset.bundled} lab(s) that came inside this course file? (Labs installed from the library on their own are kept; your history is kept either way.)`);
    try {
      const r = await api(`/api/courses/${encodeURIComponent(b.dataset.rmcourse)}?labs=${labsToo}`, {method: "DELETE"});
      toast("Course removed" + (r.removed_labs.length ? ` with ${r.removed_labs.length} lab(s)` : ""), "ok");
      if ($("#f-course").value === b.dataset.rmcourse) $("#f-course").value = "";
      try { await loadLabs(); } catch (e) { /* banner */ }
      await openLibrary(false);
    } catch (e) { toast(e.message, "err"); }
  }));
}
async function loadLibrary() {
  const url = $("#lib-url").value.trim() || libraryUrl || LIB_DEFAULT;
  $("#lib-items").innerHTML = '<p class="muted loading" role="status"><span class="spinner" aria-hidden="true"></span>Loading the library…</p>';
  try {
    const idx = await api(`/api/library?url=${encodeURIComponent(url)}`);
    libStarter = idx.starter || [];
    const starterLeft = idx.items.filter((it) => it.starter && !it.installed).length;
    const ups = idx.updates || [];
    const libBtn = (it) => {
      if (it.builtin) return '<span class="tag">built in</span>';
      if (it.kind === "course") {
        const n = (it.missing || []).length;
        if (n && !it.installable) return `<span class="tag warn" title="The library has no pack for: ${esc(it.missing.join(", "))}">labs missing</span>`;
        return `<button data-help="lib.installAll" data-file="${esc(it.file)}" data-installed="${it.installed && !n ? 1 : ""}" class="${it.installed && !n ? "" : "primary"}">${n ? `Install all (${n} lab${n > 1 ? "s" : ""})` : (it.installed ? "Reinstall" : "Install")}</button>`;
      }
      if (it.update_available) return `<button data-help="lib.update" data-file="${esc(it.file)}" data-installed="1" class="primary">Update to v${esc(it.version)}</button>`;
      return `<button data-help="lib.install" data-file="${esc(it.file)}" data-installed="${it.installed ? 1 : ""}" class="${it.installed ? "" : "primary"}">${it.installed ? "Reinstall" : "Install"}</button>`;
    };
    libPrepare(idx);
    $("#lib-items").innerHTML = idx.items.length ? `<div class="toolbar">
      ${starterLeft ? `<button data-help="lib.starter" id="lib-starter" class="primary">Install recommended starter set (${starterLeft})</button>` : ""}
      ${ups.length ? `<button data-help="lib.updateAll" id="lib-update-all" class="warn">Update all (${ups.length})</button>` : ""}
      <span class="sep"></span><button data-help="lib.expandAll" id="lib-expand" type="button" class="hint-btn">Expand all</button><button data-help="lib.collapseAll" id="lib-collapse" type="button" class="hint-btn">Collapse all</button></div>
      <div id="lib-cards">${libGroups.map((g) => `<section class="lib-group" data-g="${esc(g.id)}" aria-labelledby="lib-gh-${esc(g.id)}">
        <h4 class="lib-group-h"><button data-help="lib.group" type="button" id="lib-gh-${esc(g.id)}" aria-controls="lib-g-${esc(g.id)}" aria-expanded="true"><span class="chev" aria-hidden="true"></span>${esc(g.label)} <span class="lib-gcount muted"></span></button></h4>
        <div class="lib-grid" id="lib-g-${esc(g.id)}" role="list"></div></section>`).join("")}
        <div class="lib-grid" id="lib-flat" role="list" aria-label="Library items"></div></div>
      <div id="lib-empty" class="lib-empty" hidden></div>
      <div class="muted small" data-help="lib.integrity">Every download is checked against the sha256 and size in the index, then validated like an imported file.</div>`
      : `<div class="muted">The library is empty.</div>`;
    const tpl = document.createElement("template");
    tpl.innerHTML = idx.items.map((it, i) => libCardHtml(it, i, libBtn(it))).join("");
    libCards = [...tpl.content.children];
    $("#lib-search-bar").hidden = !idx.items.length;
    libRenderTopics();
    if ($("#lib-expand")) { $("#lib-expand").onclick = () => libCollapseAll(false); $("#lib-collapse").onclick = () => libCollapseAll(true); }
    libApply();
    libCards.flatMap((c) => [...c.querySelectorAll("[data-file]")]).forEach((b) => b.addEventListener("click", () => libInstall({file: b.dataset.file, index_url: url}, !!b.dataset.installed)));
    libFitTags();   // "fits now?" tags from the cached resource check (3.3.0); silent when CML is not set up
    if ($("#lib-starter")) $("#lib-starter").onclick = () => installStarter($("#lib-starter"));
    if ($("#lib-update-all")) $("#lib-update-all").onclick = async () => {
      if (!confirm(`Update ${ups.length} lab(s) to the library version? Your history and progress are kept; changes you made to those labs' files are replaced.`)) return;
      try { const r = await api("/api/library/install-set", {method: "POST", body: JSON.stringify({updates: true, index_url: url})});
        toast(`Updated ${r.installed.length} lab(s)` + (Object.keys(r.failed).length ? `\nFailed: ${Object.entries(r.failed).map(([k, v]) => `${k}: ${v}`).join("\n")}` : ""), "ok", 8000);
      } catch (e) { toast("Update failed: " + libErr(e), "err", 12000); }
      try { await loadLabs(); } catch (e) { /* banner */ }
      loadLibrary();
    };
  } catch (e) {
    $("#lib-items").innerHTML = offlineNote(libErr(e));
    const a = $("#lib-items [data-retry]"); if (a) a.onclick = (ev) => { ev.preventDefault(); loadLibrary(); };
  }
}
/* library search: fuzzy matching over the loaded index (fuzzy.js), no server calls while typing */
const libText = (it, key) => Fuzzy.library.text(it, key);
function libCell(it, key, hits) { return Fuzzy.highlight(libText(it, key), hits && hits[key], esc); }
const LIB_NOGROUP = new Set(["Type", "Track"]);
const libTopicLabel = (t) => (libTopicMeta.get(t) || {label: t}).label;
const libSubjects = (it) => (it.topics || []).filter((t) => !LIB_NOGROUP.has((libTopicMeta.get(t) || {}).area));
// a lab is listed once: under the first of its subject topics that is selected as a filter, else under its first
// subject topic; courses have their own group at the end
const libGroupOf = (it) => it.kind === "course" ? "_courses"
  : (libSubjects(it).find((t) => libQuery.topics.includes(t)) || libSubjects(it)[0] || "other");
function libPrepare(idx) {
  const t0 = performance.now();
  libIdx = idx;
  // topic vocabulary from the app (index.topics); an app/index without it still works, with the ids as labels
  libTopicMeta = new Map((idx.topics || []).map((t) => [t.id, t]));
  for (const it of idx.items) for (const t of it.topics || []) if (!libTopicMeta.has(t)) libTopicMeta.set(t, {id: t, label: t, area: "Other"});
  Fuzzy.library.labels = Object.fromEntries([...libTopicMeta].map(([k, v]) => [k, v.label]));
  const order = [...libTopicMeta.keys()];
  const gids = [...new Set(idx.items.flatMap((it) => it.kind === "course" ? ["_courses"] : (libSubjects(it).length ? libSubjects(it) : ["other"])))].sort((a, b) => (a === "_courses") - (b === "_courses") || order.indexOf(a) - order.indexOf(b));
  libGroups = gids.map((g) => ({id: g, label: g === "_courses" ? "Courses" : libTopicLabel(g)}));
  libQuery.topics = libQuery.topics.filter((t) => libTopicMeta.has(t));
  Fuzzy.library.addCourses(idx.items);
  libRecs = idx.items.map(Fuzzy.library.record);
  const sel = $("#lib-course");
  if (sel) sel.innerHTML = `<option value="">Any course</option>` + idx.items.filter((c) => c.kind === "course")
    .map((c) => `<option value="${esc(c.id)}" ${c.id === libQuery.course ? "selected" : ""}>Course: ${esc(c.title)}</option>`).join("");
  libPrepare.ms = performance.now() - t0;
}
function libRamTag(it) {
  return it.ram_gb ? ramTag({heavy: it.ram_heavy, label: `~${Math.round(it.ram_gb)} GB`,
    tooltip: `About ${Math.round(it.ram_gb)} GB of CML server RAM${it.kind === "course" ? " for its heaviest lab" : ""}, estimated from the CML 2.9 node-definition defaults.${it.ram_heavy ? " Marked RAM heavy (threshold in Settings)." : ""}`}) : "";
}
function libCardHtml(it, i, action) {
  const type = it.kind === "course" ? ["course", "Course"] : it.type === "walkthrough" ? ["walk", "Walkthrough"] : ["chal", "Challenge"];
  const chips = (it.topics || []).filter((t) => (libTopicMeta.get(t) || {}).area !== "Type")
    .map((t) => `<button data-help="lib.cardTopic" type="button" class="chip sm" data-topic="${esc(t)}" aria-pressed="false" aria-label="Filter by topic ${esc(libTopicLabel(t))}">${esc(libTopicLabel(t))}</button>`).join("");
  const status = [it.starter ? '<span class="tag ok" data-help="lib.starterTag">starter</span>' : "",
    it.update_available ? `<span class="tag warn">update v${esc(it.version)}</span>` : "",
    it.kind === "lab" && it.installed ? `<span class="tag inst">installed v${esc(it.installed_version || "1")}</span>` : "",
    it.kind === "course" && it.installed ? '<span class="tag inst">installed</span>' : ""].join("");
  return `<article class="lib-card" role="listitem" data-i="${i}" aria-label="${esc(it.title)}">
    <div class="lib-card-head"><h5 class="lib-card-title c-title">${libCell(it, "title")}</h5><span class="type-badge ${type[0]}">${type[1]}</span></div>
    <div class="lib-meta">${it.difficulty ? `<span class="stars" title="Difficulty ${it.difficulty} of 5" aria-label="Difficulty ${it.difficulty} of 5">${"★".repeat(it.difficulty)}<span class="dim">${"★".repeat(Math.max(0, 5 - it.difficulty))}</span></span>` : ""}
      ${it.kind === "course" ? `<span>${(it.labs || []).length} labs</span>` : it.nodes ? `<span>${it.nodes} nodes</span>` : ""}${libRamTag(it)}${it.ram_gb ? `<span class="fit-slot" data-gb="${Number(it.ram_gb) || 0}" data-nodes="${Number(it.nodes) || 0}"></span>` : ""}${status}</div>
    <p class="lib-desc c-description">${libCell(it, "description")}</p>
    <div class="muted small c-id"></div>
    ${it.kind === "course" ? `<div class="muted small">Labs: <span class="c-labs">${libCell(it, "labs")}</span></div>` : ""}
    <div class="lib-hit muted small" hidden><span class="c-domain"></span> <span class="c-nodes"></span></div>
    <div class="lib-chips">${chips}</div>
    <div class="lib-card-foot"><span class="muted small lib-where"><span class="c-blueprint">${libCell(it, "blueprint")}</span><span class="c-courses">${it.in_courses && it.in_courses.length ? " · " + libCell(it, "courses") : ""}</span></span>
      <span class="muted small lib-size">${(it.size / 1024).toFixed(1)} KB</span>${action}</div></article>`;
}
// topic chips with counts (the items that pass the search and the other filters), grouped by area
function libRenderTopics() {
  const box = $("#lib-topics"); if (!box || !libIdx) return;
  const used = new Set(libIdx.items.flatMap((it) => it.topics || []));
  const areas = [];
  for (const [id, t] of libTopicMeta) {
    if (!used.has(id)) continue;
    let a = areas.find((x) => x.area === t.area); if (!a) areas.push(a = {area: t.area, ids: []});
    a.ids.push(id);
  }
  box.innerHTML = areas.map((a) => `<span class="lib-area" role="group" aria-label="${esc(a.area)}"><span class="lib-area-name">${esc(a.area)}</span>${a.ids.map((id) =>
    `<button data-help="lib.topic" type="button" class="chip" data-topic="${esc(id)}" aria-pressed="false">${esc(libTopicLabel(id))} <span class="n"></span></button>`).join("")}</span>`).join("")
    + `<button data-help="lib.clearTopics" type="button" id="lib-topics-clear" class="hint-btn" hidden>Clear topics</button>`;
  box.hidden = !areas.length;
  $("#lib-topics-clear").onclick = () => { libQuery.topics = []; libSavePrefs(); libApply(); };
}
function libToggleTopic(t) {
  libQuery.topics = libQuery.topics.includes(t) ? libQuery.topics.filter((x) => x !== t) : [...libQuery.topics, t];
  libSavePrefs(); libApply();
}
// selected topics: any of them within one area (OSPF or BGP), all areas at once (OSPF or BGP, and Walkthrough)
function libTopicsOk(it, sel) {
  if (!sel.length) return true;
  const by = {};
  for (const t of sel) (by[(libTopicMeta.get(t) || {}).area] = by[(libTopicMeta.get(t) || {}).area] || []).push(t);
  const has = new Set(it.topics || []);
  return Object.values(by).every((ts) => ts.some((t) => has.has(t)));
}
function libCollapseAll(c) {
  libPrefs.collapsed = c ? libGroups.map((g) => g.id) : [];
  libSavePrefs(); libApply();
}
function libStatusOk(it, st) {
  if (!st) return true;
  if (st === "update") return !!it.update_available;
  const inst = it.kind === "course" ? it.installed && !(it.missing || []).length : !!it.installed;
  return st === "installed" ? inst : !inst;
}
function libBindFilters() {
  const q = $("#lib-search");
  libBindValues();
  const upd = () => { libQuery = {...libQuery, q: q.value, kind: $("#lib-kind").value, status: $("#lib-status").value, course: $("#lib-course").value, noheavy: $("#lib-noheavy").checked};
    if (!libRaf) libRaf = requestAnimationFrame(() => { libRaf = 0; libApply(); }); };
  ["#lib-search", "#lib-kind", "#lib-status", "#lib-course", "#lib-noheavy"].forEach((s) => $(s).addEventListener("input", upd));
  const view = (v) => { libPrefs.view = v; libSavePrefs(); libApply(); };
  $("#lib-view-grouped").onclick = () => view("grouped"); $("#lib-view-list").onclick = () => view("list");
  // topic chips (row and cards) and group headings, by delegation: the cards are moved around, not re-rendered
  $("#library").addEventListener("click", (e) => {
    const chip = e.target.closest("[data-topic]");
    if (chip) { libToggleTopic(chip.dataset.topic); return; }
    const h = e.target.closest(".lib-group-h button");
    if (h) { const g = h.closest(".lib-group").dataset.g;
      libPrefs.collapsed = libPrefs.collapsed.includes(g) ? libPrefs.collapsed.filter((x) => x !== g) : [...libPrefs.collapsed, g];
      libSavePrefs(); libApply(); }
  });
  // arrow keys move between the topic chips
  $("#lib-topics").addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    const all = $$("#lib-topics .chip"), i = all.indexOf(document.activeElement); if (i < 0) return;
    const j = e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + all.length) % all.length;
    all[j].focus(); e.preventDefault();
  });
}
// filter + rank + highlight the already-rendered cards and move them into their groups (no re-render while typing)
function libApply() {
  const box = $("#lib-cards"); if (!libIdx || !box) return;
  const t0 = performance.now();
  const items = libIdx.items, {q, kind, status, course, noheavy, topics} = libQuery;
  const crs = course && items.find((c) => c.kind === "course" && c.id === course);
  const keep = (it) => (!kind || it.kind === kind) && libStatusOk(it, status) && !(noheavy && it.ram_heavy) &&
    (!crs || it === crs || (it.kind === "lab" && (crs.labs || []).includes(it.id)));
  const searching = Fuzzy.tokens(q).length > 0;
  let base = searching ? Fuzzy.search(q, libRecs) : items.map((it, i) => ({i, hits: null}));
  base = base.filter((r) => keep(items[r.i]));
  const order = base.filter((r) => libTopicsOk(items[r.i], topics));
  const tMatch = performance.now() - t0;
  // chip counts: what each topic would show with the search and the other filters (ignoring the topic selection)
  const counts = {};
  for (const r of base) for (const t of items[r.i].topics || []) counts[t] = (counts[t] || 0) + 1;
  for (const c of $$("#lib-topics .chip")) {
    const t = c.dataset.topic, on = topics.includes(t), n = counts[t] || 0;
    c.setAttribute("aria-pressed", on); c.querySelector(".n").textContent = n;
    c.classList.toggle("zero", !n && !on); c.setAttribute("aria-label", `${libTopicLabel(t)}: ${n} item${n === 1 ? "" : "s"}${on ? ", selected" : ""}`);
  }
  $("#lib-topics-clear").hidden = !topics.length;
  const grouped = libPrefs.view !== "list";
  $("#lib-view-grouped").setAttribute("aria-pressed", grouped); $("#lib-view-list").setAttribute("aria-pressed", !grouped);
  const sets = {}, flat = document.createDocumentFragment(), shown = new Set();
  for (const r of order) {
    const card = libCards[r.i], it = items[r.i];
    if (r.hits || card._hl) {
      for (const k of ["title", "description", "blueprint", "labs"]) {
        const el = card.querySelector(".c-" + k); if (el) el.innerHTML = libCell(it, k, r.hits);
      }
      const cc = card.querySelector(".c-courses"); cc.innerHTML = it.in_courses && it.in_courses.length ? " · " + libCell(it, "courses", r.hits) : "";
      // matches in fields the card does not show: domain, node types
      const hd = r.hits && r.hits.domain, hn = r.hits && r.hits.nodes;
      card.querySelector(".c-domain").innerHTML = hd ? libCell(it, "domain", r.hits) : "";
      card.querySelector(".c-nodes").innerHTML = hn ? libCell(it, "nodes", r.hits) : "";
      card.querySelector(".lib-hit").hidden = !(hd || hn);
      card.querySelector(".c-id").innerHTML = r.hits && r.hits.id ? "id: " + libCell(it, "id", r.hits) : "";
      card._hl = !!r.hits;
    }
    for (const c of card.querySelectorAll(".chip")) c.setAttribute("aria-pressed", topics.includes(c.dataset.topic));
    card.hidden = false; shown.add(r.i);
    if (grouped) { const g = libGroupOf(it); (sets[g] = sets[g] || []).push(card); } else flat.appendChild(card);
  }
  // groups in vocabulary order; while searching, the group with the best match first
  const rank = searching ? Object.keys(sets) : null;
  for (const g of libGroups) {
    const sec = box.querySelector(`.lib-group[data-g="${CSS.escape(g.id)}"]`), cards = sets[g.id] || [];
    const grid = sec.querySelector(".lib-grid"), collapsed = libPrefs.collapsed.includes(g.id);
    sec.hidden = !grouped || !cards.length;
    sec.querySelector(".lib-group-h button").setAttribute("aria-expanded", !collapsed);
    sec.classList.toggle("collapsed", collapsed); grid.hidden = collapsed;
    sec.querySelector(".lib-gcount").textContent = cards.length;
    const frag = document.createDocumentFragment(); cards.forEach((c) => frag.appendChild(c)); grid.appendChild(frag);
    if (rank) box.insertBefore(sec, $("#lib-flat"));
  }
  if (rank) for (const g of rank.slice().reverse()) box.insertBefore(box.querySelector(`.lib-group[data-g="${CSS.escape(g)}"]`), box.firstChild);
  else for (const g of libGroups) box.insertBefore(box.querySelector(`.lib-group[data-g="${CSS.escape(g.id)}"]`), $("#lib-flat"));
  const fl = $("#lib-flat"); fl.hidden = grouped; fl.appendChild(flat);
  libCards.forEach((c, i) => { if (!shown.has(i)) { c.hidden = true; if (c.parentNode) c.remove(); } });
  const filtered = q.trim() || kind || status || course || noheavy || topics.length;
  $("#lib-count").textContent = filtered ? `${order.length} of ${items.length}` : `${items.length} items`;
  $("#lib-expand").hidden = $("#lib-collapse").hidden = !grouped;
  const empty = $("#lib-empty");
  empty.hidden = order.length > 0; box.hidden = !order.length;
  if (!order.length) {
    const what = [q.trim() ? `"<b>${esc(q.trim())}</b>"` : "", topics.length ? "topics " + topics.map((t) => `<b>${esc(libTopicLabel(t))}</b>`).join(" + ") : ""].filter(Boolean).join(" and ");
    empty.innerHTML = `No labs or courses match${what ? " " + what : ""}${kind || status || course || noheavy ? " with these filters" : ""}.
      Try fewer words or topics (typos and abbreviations like "mcast" or "ospf stb" are fine). <button data-help-text="Empty the search box and reset the filters and topics." id="lib-clear" class="hint-btn">Clear search and filters</button>`;
    $("#lib-clear").onclick = () => { libQuery = {q: "", kind: "", status: "", course: "", noheavy: false, topics: []}; libSavePrefs(); libBindValues(); libApply(); $("#lib-search").focus(); };
  }
  libApply.ms = {match: tMatch, total: performance.now() - t0};
}
function libBindValues() { $("#lib-search").value = libQuery.q; $("#lib-kind").value = libQuery.kind; $("#lib-status").value = libQuery.status; $("#lib-course").value = libQuery.course; $("#lib-noheavy").checked = libQuery.noheavy; }
// "/" or Ctrl+K focuses the search (library page if open, else the lab list); Esc clears it
document.addEventListener("keydown", (e) => {
  const t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  if ((e.key === "/" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) || ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "k")) {
    const box = ($("#lib-search-bar") && !$("#lib-search-bar").hidden) ? $("#lib-search") : $("#f-search");
    if (box && box.id === "f-search" && $("#catalog").hidden && $("#view-labs").offsetParent !== null) setCatalog(false);
    if (!box || box.offsetParent === null) return;   // that view is not shown
    e.preventDefault(); box.focus(); box.select();
    return;
  }
  if (e.key === "Escape" && t && (t.id === "lib-search" || t.id === "f-search")) {
    if (t.value) { t.value = ""; t.dispatchEvent(new Event("input")); e.preventDefault(); } else t.blur();
  }
});
async function libInstall(body, replace = false) {
  if (!body.file && !body.url) { toast("Enter the https URL of a .cmllab or .cmlcourse file", "err"); return; }
  if (body.url && !body.sha256 && !confirm("No sha256 given, so the download cannot be verified. It will still be validated before it is installed. Continue?")) return;
  try {
    const r = await api("/api/library/install", {method: "POST", body: JSON.stringify({...body, replace})});
    if (r.kind === "course") { await afterCourseInstall(r); return; }
    toast(`Installed "${r.title}"` + (r.warnings.length ? `\nNote: ${r.warnings.join("\n")}` : ""), "ok", 7000);
    try { await loadLabs(); } catch (e) { return; }
    await loadCourses(); renderCourses(); if (body.file) loadLibrary();
  } catch (err) {
    const d = err.data || {};
    if (err.status === 409 && confirm(`${(d.errors || []).join("\n")}\n\nReplace?`)) return libInstall(body, true);
    toast("Install failed:\n- " + ((d.errors && d.errors.length) ? d.errors.join("\n- ") : err.message), "err", 15000);
  }
}

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
// 2.1.0: "Test console" per node - opens the node's console step by step (SSH, open, prompt, login, command) and shows
// what each stage saw plus the raw last console lines, so a failing Check/Apply can be explained.
function consoleTestBox(l) {
  const nodes = l.node_list || [];
  if (!nodes.length) return "";
  return `<details id="ctest-box"><summary data-help="lab.consoleTest">Test console</summary>
    <p class="muted small">Opens one node's console the way Check and Apply do and reports every stage. The lab must be built and the node booted.</p>
    <div class="toolbar">${nodes.map((n) => `<button data-help="lab.consoleTestNode" class="small" data-ctest="${esc(n.name)}">${esc(n.name)} <span class="muted">${esc(n.os)}</span></button>`).join("")}</div>
    <div id="ctest-out"></div></details>`;
}
function bindConsoleTest(l) {
  document.querySelectorAll("[data-ctest]").forEach((b) => { b.onclick = () => consoleTest(l.id, b.dataset.ctest); });
}
async function consoleTest(id, node) {
  const out = $("#ctest-out"); if (!out) return;
  document.querySelectorAll("[data-ctest]").forEach((b) => { b.disabled = true; });
  out.innerHTML = `<p class="muted">Testing the console of ${esc(node)}… (an NX-OS node can take a minute)</p>`;
  try {
    const r = await api(`/api/labs/${id}/console-test?node=${encodeURIComponent(node)}`, {method: "POST"});
    out.innerHTML = `<p><b>${esc(node)}</b> ${r.ok ? '<span class="tag ok">console OK</span>' : '<span class="tag bad">console problem</span>'}</p>
      <table>${(r.stages || []).map((st) => `<tr><td>${st.ok ? "✔" : "✘"}</td><td>${esc(st.name)}</td><td class="small">${esc(st.detail || "")}</td></tr>`).join("")}</table>
      <p class="muted small">Last console lines:</p><pre class="log">${esc(r.tail || "(nothing received)")}</pre>`;
  } catch (e) { out.innerHTML = `<p><span class="tag bad">error</span> ${esc(e.message)}</p>`; }
  document.querySelectorAll("[data-ctest]").forEach((b) => { b.disabled = false; });
}

async function selectLab(id) {
  current = id; renderList(); applyCatalog();
  const l = await api(`/api/labs/${id}`);
  currentLab = l;
  if (l.type === "walkthrough") return renderWalkthrough(l);
  $("#lab-detail").innerHTML = `
    <div class="toolbar"><h2 style="margin:0">${esc(l.title)}</h2><span class="sep"></span>
      <span class="tag">${esc(l.domain)}</span><span class="tag">${"★".repeat(l.difficulty)}</span>${ramTag(l.ram)}
      ${srcTag(labs.find((x) => x.id === l.id) || l)}${l.marked_manually ? '<span class="tag ok">completed</span>' + manTag() : ""}</div>${libNote(l.id)}
    <div class="toolbar">
      <button data-help="lab.build" id="a-build" class="primary">Build</button>${l.exam ? '<button data-help="lab.examSubmit" id="a-check" class="primary">Submit exam</button>' : '<button data-help="lab.check" id="a-check">Check</button>'}<button data-help="lab.hintNext" id="a-hint">Hint</button>
      <label class="inline">Grading<select data-help="lab.mode" id="mode"><option value="">Mode: default</option><option value="auto">Auto</option><option value="live">Live only</option><option value="config">Config only</option></select></label>
      <button data-help="lab.reset" id="a-reset">Reset</button><button data-help="lab.destroy" id="a-destroy" class="danger">Destroy</button>
      ${l.faults && !l.exam ? `<button data-help="lab.break" id="a-break" class="warn">Break my lab</button>` : ""}
      ${!l.exam && !l.fault ? `<button data-help="lab.exam" id="a-exam">Exam mode</button>` : ""}
      <span class="sep"></span>
      ${l.exam ? "" : `<button data-help="lab.edit" id="a-edit">Edit / copy</button><button data-help="lab.export" id="a-export">Export pack</button>`}
      ${l.source === "user" ? '<button data-help="lab.delete" id="a-delete" class="danger">Delete lab</button>' : ""}
      ${l.exam ? "" : markLabBtn(l)}
    </div>
    <div id="build-confirm"></div>
    <div class="statusbar"><span data-help="lab.status" class="muted"><span id="status">Status: …</span></span><div class="progress"><div id="boot-bar"></div></div>
      <span data-help="lab.timer">⏱ <span id="timer" class="timer">00:00:00</span></span><button data-help="lab.timerToggle" id="t-toggle" class="hint-btn">Start</button><button data-help="lab.timerReset" id="t-reset" class="hint-btn">Reset timer</button></div>
    ${l.fault ? `<section class="fault-box" data-help="lab.faultBox"><h3>Trouble ticket <span class="tag">fault practice</span></h3>
      <p>${esc(l.fault.ticket)}</p><p class="muted small">Started ${esc(l.fault.started || "")}. The lab was built from a working config with one fault added.
      Find and fix it, then click Check.${l.fault.extra_checks ? ` ${l.fault.extra_checks} extra check(s) are graded for this fault.` : ""}</p>
      <div class="toolbar"><button data-help="lab.faultReveal" id="a-fault-reveal" class="hint-btn">Reveal the answer</button>
      <button data-help="lab.faultEnd" id="a-fault-end" class="hint-btn">End fault practice</button></div><div id="fault-answer"></div></section>` : ""}
    <section id="exam-setup" class="exam-box" hidden><h3>Exam mode</h3>
      <p class="muted small">A timed, one-shot attempt. Hints and the solution are withheld; Check becomes <b>Submit exam</b>, which grades once and ends
      the exam. Late submissions (after the time limit plus 1 minute) score 0%. Build the lab first if it isn't running: the clock starts when you click Start.</p>
      <div class="toolbar"><label class="inline">Minutes <input data-help="lab.examMinutes" id="x-min" type="number" min="5" max="240" value="${l.default_exam_minutes}" style="width:5em"></label>
      <label class="inline">Hints <select data-help="lab.examHints" id="x-hints"><option value="penalty">Allowed, cost points</option><option value="off">Disabled</option></select></label>
      <label class="inline">Points per hint <input data-help="lab.examPenalty" id="x-pen" type="number" min="0" max="50" value="10" style="width:4em"></label>
      <button data-help="lab.examStart" id="x-start" class="primary">Start exam</button><button data-help="lab.examCancel" id="x-cancel" class="hint-btn">Cancel</button></div></section>
    ${l.exam ? `<section class="exam-box" data-help="lab.examBox"><h3>Exam running <span class="tag warn">no solution, ${l.exam.hints === "off" ? "no hints" : `hints -${l.exam.penalty} pts`}</span></h3>
      <div class="exam-clock" id="exam-clock">--:--</div>
      <p class="muted small">Started ${esc(l.exam.started)}, limit ${fmtTime(l.exam.duration_s)}. Pass target ${l.exam.pass_pct}%. Submit when done; the lab is submitted automatically when time runs out.</p>
      <div class="toolbar"><button data-help="lab.examAbort" id="x-abort" class="hint-btn">Abort exam</button></div></section>` : ""}
    <div id="hints-box" class="hints-box" data-help="lab.hintsBox" hidden></div>
    <h3 data-help="lab.task">Task</h3><div class="task md">${md(l.task)}</div>
    <details><summary data-help="lab.objectives">Objectives graded (${l.checks.length} checks: ${l.checks.filter((c) => c.mode === "live").length} live, ${l.checks.filter((c) => c.mode === "config").length} config) - spoilers</summary>
      <table>${l.checks.map((c) => `<tr><td><span class="tag">${c.mode}</span></td><td>${esc(c.device)}</td><td>${esc(c.description)}</td>
      <td>${c.hint ? `<button data-help="lab.hint" class="hint-btn" data-hint="${esc(c.hint)}">Show hint</button>` : ""}</td></tr>`).join("")}</table></details>
    <details id="cons-box" hidden><summary data-help="lab.consoles">Consoles</summary><div id="consoles"></div></details>${consoleTestBox(l)}
    ${l.exam ? "" : `<details id="snap-box"><summary data-help="lab.snapshots">Config snapshots</summary>
      <div class="toolbar"><input data-help="lab.snapName" id="snap-name" placeholder="name (blank = date/time)" style="width:16em" aria-label="Snapshot name">
      <input data-help="lab.snapNote" id="snap-note" placeholder="note (optional)" style="flex:1;min-width:12em" aria-label="Snapshot note">
      <button data-help="lab.snapSave" id="snap-save">Save snapshot</button></div><div id="snapshots" class="muted small">Loading…</div></details>`}
    <h3 data-help="lab.results">Results</h3><div id="results" class="muted">Not checked yet.</div>
    <h3 data-help="lab.activity">Activity</h3><pre id="log" class="log">-</pre>
    <details id="hist-box"><summary data-help="lab.history">History</summary><div id="history"></div></details>
    ${l.exam ? "" : `<div class="toolbar"><a data-help="lab.report" class="btn" href="/report/labs/${encodeURIComponent(l.id)}" target="_blank" rel="noopener">Print report ↗</a>
      <a data-help="lab.reportOutputs" class="btn" href="/report/labs/${encodeURIComponent(l.id)}?outputs=true" target="_blank" rel="noopener">Report with command output ↗</a></div>`}`;
  $("#a-build").onclick = () => confirmBuild(l);
  $("#a-check").onclick = () => (l.exam ? confirm("Submit the exam now? It is graded once and the exam ends.") && run("check") : run("check"));
  currentExam = l.exam || null; currentHintsTotal = l.hints_total || 0;
  currentHints = l.exam ? (l.exam.hints_shown || []) : (l.hints || []);
  $("#a-hint").onclick = l.exam ? () => examHint(id) : () => { const n = hintsUsed(id); if (n < currentHints.length) { hintsSet(id, n + 1); } };
  if ($("#a-exam")) $("#a-exam").onclick = () => { $("#exam-setup").hidden = !$("#exam-setup").hidden; };
  if ($("#x-cancel")) $("#x-cancel").onclick = () => { $("#exam-setup").hidden = true; };
  if ($("#x-start")) $("#x-start").onclick = () => examStart(id);
  if ($("#x-abort")) $("#x-abort").onclick = async () => {
    if (!confirm("Abort the exam? Nothing is recorded.")) return;
    await api(`/api/labs/${id}/exam/abort`, {method: "POST"}); toast("Exam aborted", "ok"); selectLab(id);
  };
  renderHints(); renderExamClock();
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
  if ($("#a-edit")) $("#a-edit").onclick = () => openInBuilder(id);
  if ($("#a-export")) $("#a-export").onclick = () => { location.href = `/api/labs/${encodeURIComponent(id)}/export`; };
  if ($("#a-delete")) $("#a-delete").onclick = () => deleteLab(id, l.title);
  bindMarkLab(l);
  $("#t-toggle").onclick = () => (timerState(id).start ? timerPause(id) : timerStart(id));
  $("#t-reset").onclick = () => confirm("Reset the timer?") && timerSet(id, {acc: 0, start: null});
  bindHints($("#lab-detail")); bindConsoleTest(l);
  if ($("#snap-save")) $("#snap-save").onclick = () => {
    const q = new URLSearchParams({name: $("#snap-name").value.trim(), note: $("#snap-note").value.trim()});
    run("snapshot", `/api/labs/${id}/snapshots?${q}`).then(() => { $("#snap-name").value = ""; $("#snap-note").value = ""; });
  };
  renderTimer(); refreshStatus(); loadHistory(); loadSnapshots();
}
async function loadSnapshots() {
  const box = $("#snapshots"); if (!box || !current) return;
  const id = current;
  let r; try { r = await api(`/api/labs/${id}/snapshots`); } catch (e) { box.textContent = e.message; return; }
  box.classList.toggle("muted", !r.snapshots.length);
  box.innerHTML = r.snapshots.length ? `<table><tr><th>Name</th><th>Saved</th><th>Images</th><th>Devices</th><th>Note</th><th></th></tr>${r.snapshots.map((x) => `<tr>
    <td><b>${esc(x.name)}</b></td><td class="small">${esc(x.created)}</td><td>${esc(x.platform || "-")}</td><td class="small">${esc(x.nodes.join(", "))}</td><td class="small">${esc(x.note)}</td>
    <td><button data-help="lab.snapRestore" class="hint-btn" data-restore="${esc(x.name)}">Restore</button>
      <button data-help="lab.snapView" class="hint-btn" data-view-snap="${esc(x.name)}">View</button>
      <a data-help="lab.snapDownload" class="btn small" href="/api/labs/${encodeURIComponent(id)}/snapshots/${encodeURIComponent(x.name)}?fmt=cfg">.cfg</a>
      <button data-help="lab.snapDelete" class="hint-btn danger" data-del-snap="${esc(x.name)}">Delete</button></td></tr>`).join("")}</table>
    <div id="snap-view"></div><div class="muted small">${r.snapshots.length}/${r.max} snapshots. Restore stops, wipes and reboots the lab with the saved configs.</div>`
    : "No snapshots yet. Save one when the lab is built and its nodes are BOOTED (for example before trying something risky).";
  $$("#snapshots [data-restore]").forEach((b) => b.onclick = () => confirm(`Restore snapshot "${b.dataset.restore}"? The lab is stopped, wiped and rebooted with the saved configs; unsaved changes on the devices are lost.`)
    && run("restore", `/api/labs/${id}/snapshots/${encodeURIComponent(b.dataset.restore)}/restore`));
  $$("#snapshots [data-del-snap]").forEach((b) => b.onclick = async () => {
    if (!confirm(`Delete snapshot "${b.dataset.delSnap}"?`)) return;
    try { await api(`/api/labs/${id}/snapshots/${encodeURIComponent(b.dataset.delSnap)}`, {method: "DELETE"}); loadSnapshots(); } catch (e) { toast(e.message, "err"); }
  });
  $$("#snapshots [data-view-snap]").forEach((b) => b.onclick = async () => {
    try { const sn = await api(`/api/labs/${id}/snapshots/${encodeURIComponent(b.dataset.viewSnap)}`);
      $("#snap-view").innerHTML = `<h4>${esc(sn.name)}</h4>` + Object.entries(sn.configs).map(([d, c]) => `<details><summary data-help="lab.snapDevice">${esc(d)}</summary><pre class="code">${esc(c)}</pre></details>`).join("");
    } catch (e) { toast(e.message, "err"); }
  });
}
const revealedKey = (id) => `revealed:${id}`;
/* ---------------------------------------------------------------- progressive hints (per lab, localStorage) */
let currentHints = [];
const hintsKey = (id) => `hints:${id}`;
function hintsUsed(id) { const n = parseInt(localStorage.getItem(hintsKey(id)) || "0", 10); return Number.isFinite(n) && n > 0 ? n : 0; }
function hintsSet(id, n) { if (n) localStorage.setItem(hintsKey(id), String(n)); else localStorage.removeItem(hintsKey(id)); renderHints(); }
function renderHints() {
  const btn = $("#a-hint"), box = $("#hints-box");
  if (!btn || !box || !current) return;
  const x = currentExam && currentExam.hints;
  const total = x ? currentHintsTotal : currentHints.length, used = x ? currentHints.length : Math.min(hintsUsed(current), total);
  btn.disabled = used >= total || x === "off";
  btn.textContent = x === "off" ? "Hints disabled (exam)" : !total ? "No hints" : used >= total ? `All ${total} hints shown`
    : `Hint ${used + 1} of ${total}` + (x ? ` (-${currentExam.penalty} pts)` : "");
  box.hidden = !used;
  box.innerHTML = currentHints.slice(0, used).map((h, i) =>
    `<div class="hint-item"><span class="tag">Hint ${i + 1} of ${total}</span> ${md(h).replace(/^<p>|<\/p>$/g, "")}</div>`).join("");
}
/* ---------------------------------------------------------------- exam mode (server-side state; countdown here) */
let currentExam = null, currentHintsTotal = 0, examAutoSubmitted = {};
async function examStart(id) {
  try {
    await api(`/api/labs/${id}/exam/start?minutes=${Number($("#x-min").value) || 0}&hints=${$("#x-hints").value}&penalty=${Number($("#x-pen").value) || 0}`, {method: "POST"});
    hintsSet(id, 0); localStorage.removeItem(revealedKey(id)); timerSet(id, {acc: 0, start: Date.now()});
    delete examAutoSubmitted[id]; toast("Exam started. Good luck!", "ok"); await selectLab(id);
  } catch (e) { toast("Could not start the exam: " + e.message, "err", 8000); }
}
async function examHint(id) {
  if (!confirm(`This hint costs ${currentExam.penalty} points on your exam score. Show it?`)) return;
  try { const r = await api(`/api/labs/${id}/exam/hint`, {method: "POST"}); currentHints = r.hints; currentExam = r.exam; renderHints(); }
  catch (e) { toast(e.message, "err"); }
}
function examRemaining() { return currentExam ? Math.round(currentExam.started_ts + currentExam.duration_s - Date.now() / 1000) : 0; }
function renderExamClock() {
  const el = $("#exam-clock"); if (!el || !currentExam) return;
  const rem = examRemaining();
  el.textContent = rem > 0 ? fmtTime(rem) : "TIME IS UP";
  el.classList.toggle("low", rem < 300);
  if (rem <= 0 && !examAutoSubmitted[current] && $("#a-check") && !$("#a-check").disabled) {
    examAutoSubmitted[current] = true; toast("Time is up: submitting your exam", "err", 8000); run("check");
  }
}
setInterval(renderExamClock, 1000);
function examPanel(x) {
  return `<section class="exam-report" data-help="lab.examReport"><h3>Exam result: ${x.final_pct}% <span class="${x.passed ? "pass" : "fail"}">${x.passed ? "PASS" : "FAIL"}</span>
    <span class="muted small">(target ${x.pass_pct}%)</span></h3>
    <table class="kv"><tr><td>Raw score</td><td>${x.raw_pct}%</td></tr>
    <tr><td>Hints</td><td>${x.hints === "off" ? "disabled" : `${x.hints_used} used × ${x.penalty_per_hint} = -${x.penalty} points`}</td></tr>
    <tr><td>Time</td><td>${fmtTime(x.used_s)} of ${fmtTime(x.duration_s)}${x.late ? ' <span class="fail">submitted late: scored 0%</span>' : ""}</td></tr></table></section>`;
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
    renderConsoles(s.exists ? s : null);
  } catch (e) { $("#status").textContent = "Status: " + e.message; }
}
let consKey = "";
function renderConsoles(s) {
  const box = $("#cons-box"); if (!box) return;
  const key = s && s.consoles ? JSON.stringify([s.cml_lab_url, s.consoles]) : "";
  if (key === consKey && box.dataset.lab === current) return;
  consKey = key; box.dataset.lab = current || "";
  box.hidden = !key; if (!key) { $("#consoles").innerHTML = ""; return; }
  $("#consoles").innerHTML = `<div class="toolbar">
      ${s.cml_lab_url ? `<a data-help="lab.openCml" class="btn" href="${esc(safeUrl(s.cml_lab_url))}" target="_blank" rel="noopener">Open lab in CML ↗</a>` : ""}
      <button data-help="lab.copyAllConsoles" id="cons-copy-all" class="hint-btn">Copy all commands</button>
      <span class="muted small">Console server ${esc(s.console_host)}:${s.console_port}, lab "${esc(s.cml_title)}"</span></div>
    <table><tr><th>Node</th><th>State</th><th>Console server command</th><th></th></tr>${s.consoles.map((c) => `<tr>
      <td><b>${esc(c.node)}</b> <span class="muted small">${esc(c.kind)}</span></td><td><span class="tag ${c.state === "BOOTED" ? "ok" : ""}">${esc(c.state || "-")}</span></td>
      <td><code class="cmd">${esc(c.ssh)}</code></td><td><button data-help="lab.copyConsole" class="hint-btn" data-cmd="${esc(c.ssh)}">Copy</button></td></tr>`).join("")}</table>
    <div class="muted small">Paste a command into a terminal (Windows Terminal/PowerShell, or any Linux shell) and log in with your CML password.
      Inside the console server you can also type <code>open ${esc(s.consoles[0] ? s.consoles[0].path : "/lab/node/0")}</code>. In the CML web UI: right-click a node, then Console.</div>`;
  $$("#consoles [data-cmd]").forEach((b) => b.addEventListener("click", async () => toast(await copyText(b.dataset.cmd) ? "Command copied" : "Could not copy", "ok")));
  $("#cons-copy-all").onclick = async () => toast(await copyText(s.consoles.map((c) => `# ${c.node}\n${c.ssh}`).join("\n")) ? "All console commands copied" : "Could not copy", "ok");
}
function setBusy(b) { $$("#lab-detail .toolbar button").forEach((x) => { if (!x.closest("a")) x.disabled = b; }); if (!b) renderHints(); }
async function run(kind, path) {
  const lab = current; setBusy(true);
  $("#log").textContent = `${kind} started…`;
  clearInterval(statusTimer); statusTimer = setInterval(refreshStatus, 4000);
  try {
    const q = new URLSearchParams();
    if (kind === "check") { if ($("#mode").value) q.set("mode", $("#mode").value); q.set("hints_used", String(hintsUsed(lab)));
      q.set("elapsed_s", String(timerSecs(lab))); if (localStorage.getItem(revealedKey(lab))) q.set("revealed", "true"); }
    const {job_id} = await api(path || (`/api/labs/${lab}/${kind}` + (q.toString() ? `?${q}` : "")), {method: "POST"});
    const j = await pollJob(job_id, (j) => { if (lab === current) { $("#log").textContent = j.log.join("\n") || "…"; $("#log").scrollTop = 1e9; } });
    if (j.state === "error") toast(`${kind} failed: ${j.error.split("\n")[0]}${j.error.includes("\n") ? " (the last console lines are in the Activity log)" : ""}`, "err", 12000);
    else {
      toast(`${kind} finished`, "ok");
      if (kind === "build") timerStart(lab);
      if (kind === "reset" || kind === "break") localStorage.removeItem(revealedKey(lab));
      if (kind === "reset") hintsSet(lab, 0);
      if (kind === "snapshot" || kind === "restore") { if (lab === current) loadSnapshots(); if (kind === "restore") toast("Snapshot restored: the lab rebooted with the saved configs", "ok", 7000); }
      if (kind === "break") { hintsSet(lab, 0); timerSet(lab, {acc: 0, start: Date.now()}); toast("Trouble ticket ready. Find and fix the fault.", "ok", 7000); if (lab === current) await selectLab(lab); }
      if ((kind === "step-check" || kind === "step-apply") && lab === current) await afterStepJob(kind, j.result);
      if (kind === "check" && j.result && lab === current && j.result.walkthrough) { await afterStepJob("step-check", j.result); }
      else if (kind === "check" && j.result && lab === current) {
        if (j.result.fault_fixed || j.result.exam) { hintsSet(lab, 0); await selectLab(lab); }
        if (j.result.exam) { timerPause(lab); toast(`Exam submitted: ${j.result.exam.final_pct}% (${j.result.exam.passed ? "PASS" : "below target"})`, j.result.exam.passed ? "ok" : "err", 8000); }
        showResults(j.result); if (j.result.passed) { timerPause(lab); toast(j.result.fault_fixed ? "Fault fixed!" : "Lab solved!", "ok"); } loadHistory(); loadLabs(); }
    }
  } catch (e) { toast(e.message, "err", 10000); if ($("#log")) $("#log").textContent = "Error: " + e.message; }
  clearInterval(statusTimer); setBusy(false); refreshStatus();
}
function showResults(r) {
  const modeName = r.mode === "config" ? "Config (running config via CML API)" : "Live (device console)";
  $("#results").classList.remove("muted");
  $("#results").innerHTML = (r.exam ? examPanel(r.exam) : "") + `<p><b>Score ${r.earned}/${r.total} (${r.score_pct}%)</b> ${r.passed ? '<span class="pass">SOLVED</span>' : '<span class="fail">not solved yet</span>'}</p>
    <p>Mode used: <b>${esc(modeName)}</b>${r.requested_mode ? ` (requested: ${esc(r.requested_mode)})` : ""}</p>
    ${(r.notes || []).map((n) => `<p class="note">${esc(n)}</p>`).join("")}
    <table><tr><th></th><th>Device</th><th>Check</th><th>Details</th></tr>${r.results.map((c) => `
    <tr><td class="${c.passed ? "pass" : "fail"}">${c.passed ? "PASS" : "FAIL"}</td><td>${esc(c.device)}</td>
    <td>${esc(c.description)}<br><code class="small">${esc(c.command)}</code></td>
    <td class="small">${c.details.map((d) => (d.includes("\n") ? `<pre class="log">${esc(d)}</pre>` : esc(d))).join("<br>")}${c.hint ? `<br><button data-help="lab.hint" class="hint-btn" data-hint="${esc(c.hint)}">Show hint</button>` : ""}
    <details${c.output.startsWith("(last console output)") ? " open" : ""}><summary data-help="lab.output">output</summary><pre class="log">${esc(c.output)}</pre></details></td></tr>`).join("")}</table>
    ${r.fault_fixed ? faultPanel(r.fault_fixed, "Fault fixed") : ""}
    <div id="solution-box">${r.fault ? "" : r.passed && r.solution_summary ? solutionPanel({summary: r.solution_summary, auto_generated: r.solution_summary_auto, configs: {}})
      : '<button data-help="lab.revealSolution" id="a-reveal" class="hint-btn">Reveal solution</button>'}</div>`;
  bindHints($("#results"));
  const rb = $("#a-reveal");
  if (rb) rb.onclick = async () => {
    if (!confirm("Reveal the full solution? This shows the root cause and the exact fix for every device.")) return;
    try { $("#solution-box").innerHTML = solutionPanel(await api(`/api/labs/${current}/solution`), true); localStorage.setItem(revealedKey(current), "1"); }
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

/* ---------------------------------------------------------------- build confirmation (shows the RAM estimate) */
let currentLab = null;
/* ---------------------------------------------------------------- resource pre-check before Build (3.3.0) */
let resCache = null;   // {at, data}: GET /api/resources, kept 30 s (the server caches 30 s too)
async function cmlResources(fresh) {
  if (!fresh && resCache && Date.now() - resCache.at < 30000) return resCache.data;
  const d = await api(`/api/resources${fresh ? "?fresh=true" : ""}`);
  resCache = {at: Date.now(), data: d};
  return d;
}
function fitLevel(snap, gb, nodes) {
  if (!snap || snap.available_gb == null) return {level: "unknown"};
  const margin = snap.available_gb - (gb || 0), head = snap.headroom_gb ?? 4;
  let level = margin < 0 ? "nofit" : margin < head ? "tight" : "fits";
  const ramLevel = level, lic = snap.license;
  // node licenses only when CML reported both numbers (3.3.1: an unreadable license is "can't tell", never "won't fit")
  const licFail = !!(lic && lic.known && nodes && lic.in_use + nodes > lic.max);
  const limFail = !!(snap.node_limit && nodes && (snap.running_nodes || 0) + nodes > snap.node_limit);
  if (licFail || limFail) level = "nofit";
  return {level, margin, ramLevel, nodesFail: licFail || limFail};
}
const FIT = {fits: ["check", "Fits"], tight: ["alert", "Tight"], nofit: ["block", "Won't fit"], unknown: ["help", "Can't tell"]};
const FIT_TAG = {fits: "fits now", tight: "tight now", nofit: "won't fit now", unknown: "fit unknown"};
function fitTag(level, title) {
  return `<span data-help="lib.fit" class="tag fit fit-${level}" title="${esc(title)}">${icon(FIT[level][0])}${FIT_TAG[level]}</span>`;
}
async function libFitTags() {
  const slots = (typeof libCards !== "undefined" && libCards ? libCards : []).flatMap((c) => [...c.querySelectorAll(".fit-slot")]);
  if (!slots.length) return;
  let d;
  try { d = await cmlResources(false); } catch { return; }
  if (!d || !d.configured || !d.enabled || d.available_gb == null) return;   // nothing to say: no tag
  for (const s of slots) {
    const gb = Number(s.dataset.gb) || 0, nodes = Number(s.dataset.nodes) || 0, f = fitLevel(d, gb, nodes);
    const lic = d.license && d.license.known ? ` Node licenses: ${d.license.in_use} of ${d.license.max} in use, this lab uses ${nodes}.` : "";
    const why = f.level !== "nofit" ? "" : f.nodesFail && f.ramLevel === "nofit" ? " Not enough memory or node licenses."
      : f.nodesFail ? " Memory is fine; not enough node licenses." : " Not enough free memory.";
    s.innerHTML = fitTag(f.level, `Needs about ${Math.round(gb)} GB; ${d.available_gb} GB of CML memory is free right now` +
      ` (${d.headroom_gb} GB headroom).${lic}${why} Checked within the last 30 s; the Build button checks again.`);
  }
}
const gb1 = (x) => x == null ? "?" : (x >= 10 ? Math.round(x) : Math.round(x * 10) / 10);
function confirmBuild(l) {
  const box = $("#build-confirm"); if (!box) return run("build");
  const r = l.ram || {};
  box.innerHTML = `<section class="${r.heavy ? "build-box heavy" : "build-box"}" data-help="lab.buildBox" aria-labelledby="bc-title">
    <p id="bc-title"><b>Build "${esc(l.title)}" in CML?</b> ${ramTag(r)}</p>
    <p class="small">${l.nodes} nodes. ${esc(r.tooltip || "")}${r.vcpus ? ` About ${r.vcpus} vCPUs.` : ""}</p>
    <div id="res-panel" class="res-panel" aria-live="polite" aria-busy="true"><p class="muted small loading"><span class="spinner" aria-hidden="true"></span>Checking free memory and running labs on CML…</p></div>
    <div class="toolbar"><button data-help="lab.buildGo" id="bc-go" class="primary">Build</button><button data-help="lab.buildCancel" id="bc-cancel" class="hint-btn">Cancel</button>
      <button data-help="res.recheck" id="bc-recheck" class="hint-btn" hidden>${icon("refresh")}Check again</button>
      <button data-help="res.copyDiag" id="bc-diag" class="hint-btn">${icon("info")}Copy diagnostics</button></div></section>`;
  $("#bc-go").onclick = () => { box.innerHTML = ""; resCache = null; run("build"); };
  $("#bc-cancel").onclick = () => { box.innerHTML = ""; };
  $("#bc-recheck").onclick = () => renderPrecheck(l);
  $("#bc-diag").onclick = copyResourceDiagnostics;
  renderPrecheck(l);
}
async function copyResourceDiagnostics() {
  try {
    const d = await api("/api/resources/debug");
    if (!d.configured) { toast("Set up the CML connection in Settings first", "err"); return; }
    const text = JSON.stringify(d.dump, null, 1);
    toast(await copyText(text) ? "Diagnostics copied (secrets, serials, ids, host names and IP addresses removed). Paste them into your bug report."
      : "Could not copy to clipboard; run `cmllab resource-diagnostics` instead", "ok", 8000);
  } catch (e) { toast("Could not read diagnostics: " + e.message, "err"); }
}
function setBuildGo(level) {
  const go = $("#bc-go"); if (!go) return;
  go.textContent = level === "fits" || level === "tight" || level === "off" ? "Build" : "Build anyway";
  go.className = level === "nofit" ? "danger" : level === "tight" || level === "unknown" ? "warn" : "primary";
  if ($("#bc-recheck")) $("#bc-recheck").hidden = level === "off";
}
async function renderPrecheck(l) {
  const panel = $("#res-panel"); if (!panel) return;
  panel.setAttribute("aria-busy", "true");
  panel.innerHTML = '<p class="muted small loading"><span class="spinner" aria-hidden="true"></span>Checking free memory and running labs on CML…</p>';
  let d;
  try { d = await api(`/api/labs/${encodeURIComponent(l.id)}/precheck`); }
  catch (e) {
    if (!$("#res-panel")) return;
    panel.innerHTML = `<div class="res-head res-unknown">${icon("help")}<div><b>Couldn't check CML resources.</b><div class="small">${esc(e.message)}. You can build anyway or cancel.</div></div></div>`;
    panel.removeAttribute("aria-busy"); setBuildGo("unknown"); return;
  }
  if (!$("#res-panel")) return;   // the box was closed meanwhile
  panel.removeAttribute("aria-busy");
  if (!d.configured) { panel.innerHTML = '<p class="muted small">Set up CML on the Settings page to check free memory before a build.</p>'; setBuildGo("off"); return; }
  if (!d.enabled) { panel.innerHTML = '<p class="muted small">The resource check is turned off (Settings &gt; Resource check).</p>'; setBuildGo("off"); return; }
  const v = d.verdict, s = d.snapshot, [ic, word] = FIT[v.level];
  const total = s.total_gb, used = total != null && s.available_gb != null ? Math.max(0, total - s.available_gb) : null;
  const ramLv = (v.ram && v.ram.level) || v.level, nd = v.node_check || {level: "unknown"};
  const pct = (x) => total ? Math.max(0, Math.min(100, (x / total) * 100)).toFixed(1) : 0;
  const meter = total ? `<div class="meter" role="img" aria-label="CML memory: ${gb1(used)} GB in use, this lab needs ${gb1(v.need_gb)} GB, ${gb1(total)} GB total">
      <span class="meter-used" style="width:${pct(used)}%"></span><span class="meter-need fit-${ramLv}" style="width:${pct(Math.min(v.need_gb, Math.max(0, total - used)))}%"></span></div>
      <div class="meter-legend small"><span><i class="sw used"></i>in use ${gb1(used)} GB</span><span><i class="sw need fit-${ramLv}"></i>this lab ~${gb1(v.need_gb)} GB</span><span>free ${gb1(s.available_gb)} of ${gb1(total)} GB · headroom ${gb1(v.headroom_gb)} GB</span></div>` : "";
  const summary = v.level === "fits" ? `Enough memory: about ${gb1(v.margin_gb)} GB stays free after the build.`
    : v.level === "tight" ? "It should start, but the server will be nearly full."
    : v.level === "nofit" ? ((v.failed || []).length === 2 ? "Not enough free memory and not enough node licenses."
      : (v.failed || [])[0] === "nodes" ? "Memory is fine, but there are not enough node licenses: the extra nodes will not start."
      : "Not enough free memory: this lab will probably not start (or nodes will fail to boot) until you free some.")
    : "The server's free memory could not be read.";
  const LV = {fits: "fits", tight: "tight", nofit: "won't fit", unknown: "can't tell"};
  const limits = `<ul class="small res-limits" aria-label="Limits checked">
      <li class="lim fit-${ramLv}">${icon(FIT[ramLv][0])}<b>Memory:</b> ${LV[ramLv]}${v.need_gb != null ? ` (needs ~${gb1(v.need_gb)} GB, ${gb1(s.available_gb)} GB free)` : ""}</li>
      <li class="lim fit-${nd.level}">${icon(FIT[nd.level][0])}<b>Node licenses:</b> ${LV[nd.level]}${nd.max != null
        ? ` (this lab uses ${v.nodes}; ${nd.in_use} of ${nd.max} in use${nd.pool ? `; your resource pool${nd.pool.label ? " " + esc(nd.pool.label) : ""}: ${nd.pool.in_use} of ${nd.pool.max}` : ""})` : ` (this lab uses ${v.nodes}; ${esc((s.license && s.license.note) || "CML did not report its license: only admins can read it")})`}</li></ul>`;
  const lic = s.license && s.license.product ? `<span>License: ${esc(s.license.product)}${s.license.source === "diagnostics" ? "" : s.license.source === "licensing+labs" ? " (nodes counted from running labs)" : ""}</span>` : "";
  const rows = (s.labs || []).map((x) => {
    const mine = v.running_copy && v.running_copy.id === x.id;
    return `<tr><td>${esc(x.title)}${x.owner ? ` <span class="muted small">(${esc(x.owner)})</span>` : ""}${mine ? ' <span class="tag">this lab: replaced by the build</span>' : ""}</td>
      <td class="num">${x.running_nodes}</td><td class="num">${gb1(x.ram_gb)} GB</td>
      <td class="actions">${mine ? "" : `<button data-help="res.stop" class="hint-btn" data-stop="${esc(x.id)}" data-title="${esc(x.title)}">${icon("stop")}Stop</button>`}
      ${x.ours && !mine ? `<button data-help="res.wipe" class="hint-btn danger-text" data-wipe="${esc(x.id)}" data-title="${esc(x.title)}">${icon("trash")}Stop &amp; wipe</button>` : ""}</td></tr>`;
  }).join("");
  panel.innerHTML = `<div class="res-head res-${v.level}">${icon(ic)}<div><b>${word}</b> <span class="small">${esc(summary)}</span>
      ${limits}${v.reasons.length ? `<ul class="small reasons">${v.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div></div>
    ${meter}<div class="small muted res-facts">${lic}${s.errors && s.errors.length ? `<span>Partial data: ${esc(s.errors.join("; "))}</span>` : ""}</div>
    ${rows ? `<table class="res-labs"><caption class="small muted">Running labs on CML (biggest first)</caption><thead><tr><th scope="col">Lab</th><th scope="col" class="num">Nodes</th><th scope="col" class="num">RAM</th><th scope="col"><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows}</tbody></table>`
      : '<p class="small muted">No labs are running on CML.</p>'}`;
  setBuildGo(v.level);
  $$("#res-panel [data-stop], #res-panel [data-wipe]").forEach((b) => b.onclick = () => stopCmlLab(l, b.dataset.stop || b.dataset.wipe, b.dataset.title, !!b.dataset.wipe));
}
async function stopCmlLab(l, id, title, wipe) {
  const msg = wipe ? `Stop and wipe "${title}"?\n\nIts nodes shut down and their disks and configs are discarded (the lab stays in CML and starts fresh next time). Anyone using it is interrupted.`
    : `Stop "${title}"?\n\nIts nodes shut down; unsaved device configs are lost and anyone using it is interrupted. You can start it again in CML.`;
  if (!confirm(msg)) return;
  const panel = $("#res-panel");
  try {
    if (panel) panel.innerHTML = `<p class="muted small loading"><span class="spinner" aria-hidden="true"></span>${wipe ? "Stopping and wiping" : "Stopping"} ${esc(title)}…</p>`;
    const {job_id} = await api(`/api/cml/labs/${encodeURIComponent(id)}/stop`, {method: "POST", body: JSON.stringify({confirm: true, wipe})});
    const j = await pollJob(job_id);
    if (j.state === "error") toast(`Could not stop ${title}: ${j.error.split("\n")[0]}`, "err", 10000);
    else toast(`${title} ${wipe ? "stopped and wiped" : "stopped"}`, "ok");
  } catch (e) { toast(e.message, "err", 10000); }
  resCache = null;
  renderPrecheck(l);
}

/* ---------------------------------------------------------------- walkthrough labs: guided, ordered steps */
let walk = null;   // {lab, status, index}
function renderWalkthrough(l) {
  walk = {lab: l, status: l.walkthrough, index: Math.min(l.walkthrough.current, l.steps.length)};
  $("#lab-detail").innerHTML = `
    <div class="toolbar"><h2 style="margin:0">${esc(l.title)}</h2><span class="sep"></span>
      ${walkTag(l)}<span class="tag">${esc(l.domain)}</span><span class="tag">${"★".repeat(l.difficulty)}</span>${ramTag(l.ram)}
      ${srcTag(labs.find((x) => x.id === l.id) || l)}</div>${libNote(l.id)}
    <div class="toolbar">
      <button data-help="lab.build" id="a-build" class="primary">Build</button>
      <button data-help="w.checkAll" id="w-check-all">Check every step</button>
      <button data-help="lab.reset" id="a-reset">Reset</button><button data-help="lab.destroy" id="a-destroy" class="danger">Destroy</button>
      <button data-help="w.restart" id="w-restart" class="hint-btn">Restart walkthrough</button>
      <span class="sep"></span>
      <button data-help="lab.edit" id="a-edit">Edit / copy</button><button data-help="lab.export" id="a-export">Export pack</button>
      ${l.source === "user" ? '<button data-help="lab.delete" id="a-delete" class="danger">Delete lab</button>' : ""}
    </div>
    <div id="build-confirm"></div>
    <div class="statusbar"><span data-help="lab.status" class="muted"><span id="status">Status: …</span></span><div class="progress"><div id="boot-bar"></div></div></div>
    <details class="walk-intro"${walk.index === 0 ? " open" : ""}><summary data-help="w.intro">About this walkthrough</summary><div class="task md">${md(l.task)}</div></details>
    <div id="walk-progress" class="walk-progress"></div>
    <section id="walk-step" class="walk-step"></section>
    <h3 data-help="lab.activity">Activity</h3><pre id="log" class="log">-</pre>
    <details id="cons-box" hidden><summary data-help="lab.consoles">Consoles</summary><div id="consoles"></div></details>${consoleTestBox(l)}`;
  $("#a-build").onclick = () => confirmBuild(l);
  $("#w-check-all").onclick = () => run("step-check", `/api/labs/${l.id}/walkthrough/check-all`);
  $("#a-reset").onclick = () => confirm("Reset wipes all device configs back to the starting point (hostname and logins only). Your walkthrough progress is kept. Continue?") && run("reset");
  $("#a-destroy").onclick = () => confirm("Delete this lab from CML?") && run("destroy");
  $("#w-restart").onclick = async () => {
    if (!confirm("Clear the step results and go back to step 1? (Device configs are not touched.)")) return;
    walk.status = await api(`/api/labs/${l.id}/walkthrough/reset`, {method: "POST"}); walk.index = 0; renderWalkStep(); loadLabs();
  };
  $("#a-edit").onclick = () => openInBuilder(l.id);
  $("#a-export").onclick = () => { location.href = `/api/labs/${encodeURIComponent(l.id)}/export`; };
  bindConsoleTest(l);
  if ($("#a-delete")) $("#a-delete").onclick = () => deleteLab(l.id, l.title);
  renderWalkStep(); refreshStatus();
}
function walkStepState(i) {
  const st = walk.status.steps[i] || {};
  return st.passed === true ? "ok" : st.manual_at ? "man" : st.passed === false ? "bad" : "";
}
function renderWalkProgress() {
  const l = walk.lab, s = walk.status, n = l.steps.length;
  const marked = s.steps.filter((x) => x.manual_at && !x.passed).length;
  $("#walk-progress").innerHTML = `<div class="toolbar"><b data-help="w.progress">${walk.index >= n ? `Summary (after step ${n})` : `Step ${walk.index + 1} of ${n}`}</b>
      <span class="muted small">${s.required_passed}/${s.required} required steps checked${marked ? `, ${marked} marked done by hand` : ""}${s.completed ? " · <span class=\"pass\">walkthrough completed</span>" : ""}</span>${s.completed_manually ? manTag("walkthrough") : ""}
      <span class="sep"></span>${markLabBtn(l, s)}</div>
    <div class="pbar wide" role="progressbar" aria-label="Walkthrough progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(100 * walk.index / n)}"><div style="width:${Math.round(100 * Math.min(walk.index, n) / n)}%"></div></div>
    <ol class="walk-steps">${l.steps.map((st, i) => `<li class="${i === walk.index ? "cur " : ""}${walkStepState(i)}"><button data-help="w.jump" class="hint-btn" data-step="${i}" title="${esc(st.title)}${walkStepState(i) === "man" ? " (marked done manually)" : ""}"${walkStepState(i) === "man" ? ` aria-label="${i + 1}, marked done manually"` : ""}>${i + 1}${walkStepState(i) === "ok" ? " ✓" : walkStepState(i) === "man" ? " ✓" : walkStepState(i) === "bad" ? " ✗" : ""}${st.optional ? " (opt.)" : ""}</button></li>`).join("")}
      <li class="${walk.index >= n ? "cur" : ""}"><button data-help="w.summary" class="hint-btn" data-step="${n}">Summary</button></li></ol>`;
  $$("#walk-progress [data-step]").forEach((b) => b.onclick = () => walkGo(Number(b.dataset.step)));
  bindMarkLab(l, s);
}
/* "Mark lab complete" / "Undo / mark incomplete": for a lab whose check is buggy. Walkthrough s = its status. */
function markLabBtn(l, s) {
  if (s ? s.manual_completed : l.marked_manually)
    return '<button data-help="lab.unmarkComplete" id="a-unmark" class="hint-btn">Undo / mark incomplete</button>';
  if (s ? s.completed : l.solved) return "";
  return '<button data-help="lab.markComplete" id="a-mark" class="hint-btn">Mark lab complete</button>';
}
function bindMarkLab(l, s) {
  const go = async (done) => {
    const what = s ? "walkthrough" : "lab";
    if (!confirm(done
      ? `Mark this ${what} complete by hand?\n\nUse this when a check is wrong. It is recorded as "marked manually" (not a graded pass): courses count it as done, scores and mastery do not change.`
      : `Undo the manual mark and set this ${what} back to incomplete?${s ? " Step results are kept." : " Your check history is kept."}`)) return;
    try {
      const r = await api(`/api/labs/${encodeURIComponent(l.id)}/mark-complete?done=${done}`, {method: "POST"});
      toast(done ? `Marked complete (manually)` : "Marked incomplete", "ok");
      if (s) { walk.status = r.walkthrough; renderWalkStep(); } else selectLab(l.id);
      loadLabs(); loadCourses();
    } catch (e) { toast(`Could not update: ${e.message}`, "err", 8000); }
  };
  const root = s ? "#walk-progress " : "#lab-detail ";
  if ($(root + "#a-mark")) $(root + "#a-mark").onclick = () => go(true);
  if ($(root + "#a-unmark")) $(root + "#a-unmark").onclick = () => go(false);
}
async function walkGo(i) {
  const n = walk.lab.steps.length;
  walk.index = Math.max(0, Math.min(i, n)); renderWalkStep();
  // Next / Previous / a jump: bring the top of the new step into view (below the sticky header) and focus its heading
  if (window.WalkScroll) WalkScroll.toStep($("#walk-step h3"), window, $("#walk-step"));
  try { walk.status = await api(`/api/labs/${walk.lab.id}/walkthrough/step?index=${walk.index}`, {method: "POST"}); renderWalkProgress(); } catch (e) { /* position is a convenience */ }
}
function cfgBlock(dev, text, whole) {
  const btn = whole ? `<button data-help="w.copyAll" class="hint-btn" data-copy="${esc(text)}">Copy all of ${esc(dev)}</button>`
    : `<button data-help="w.copy" class="hint-btn" data-copy="${esc(text)}">Copy ${esc(dev)} config</button>`;
  return `<div class="cfg"><div class="toolbar"><b>${esc(dev)}</b>${btn}</div><pre class="code">${esc(text)}</pre></div>`;
}
function renderWalkStep() {
  renderWalkProgress();
  const l = walk.lab, n = l.steps.length, i = walk.index, box = $("#walk-step");
  const nav = `<div class="toolbar walk-nav"><button data-help="w.prev" id="w-prev" ${i === 0 ? "disabled" : ""}>← Previous</button><span class="sep"></span>
    <button data-help="w.next" id="w-next" class="primary" ${i >= n ? "disabled" : ""}>${i === n - 1 ? "Summary →" : "Next →"}</button></div>`;
  if (i >= n) {
    const fs = l.final_summary || {devices: {}, text: ""};
    box.innerHTML = `<h3 data-help="w.summaryView">Summary: the whole build</h3>
      ${walk.status.completed ? (walk.status.completed_manually ? `<p class="pass">Walkthrough completed ${manTag("walkthrough")}</p>` : '<p class="pass">Walkthrough completed: every required step has passed its checks.</p>') : `<p class="note">${walk.status.required - (walk.status.required_done ?? walk.status.required_passed)} required step(s) not checked yet. Use <b>Check every step</b> to check them all at once.</p>`}
      <div class="md">${md(fs.text)}</div>
      <h4>Complete config per device</h4>
      ${Object.entries(fs.devices).map(([dev, parts]) => cfgBlock(dev, parts.map((p) => `! --- ${p.title}${p.optional ? " (optional)" : ""}\n${p.config}`).join(""), true)).join("")}
      ${nav}`;
  } else {
    const st = l.steps[i], r = walk.status.steps[i] || {};
    box.innerHTML = `<h3>${i + 1}. ${esc(st.title)} ${st.optional ? '<span class="tag">optional</span>' : ""}
        ${r.passed === true ? '<span class="tag ok">checked ✓</span>' : r.manual_at ? '<span class="tag ok">done</span>' + manTag("step") : r.passed === false ? '<span class="tag bad">not passing yet</span>' : ""}${r.applied_at ? '<span class="tag">applied for you</span>' : ""}</h3>
      <div class="md">${md(st.explain)}</div>
      ${Object.keys(st.config).length ? `<h4 data-help="w.config">Configuration</h4>${Object.entries(st.config).map(([d, c]) => cfgBlock(d, c, false)).join("")}` : ""}
      ${st.verify.length ? `<h4 data-help="w.verify">Verify</h4><table><tr><th>Device</th><th>Command</th><th>Good output looks like</th></tr>${st.verify.map((v) => `<tr>
        <td>${esc(v.device)}</td><td><code class="cmd">${esc(v.command)}</code> <button data-help="w.copyCmd" class="hint-btn" data-copy="${esc(v.command)}">Copy</button></td><td class="md small">${md(v.expect)}</td></tr>`).join("")}</table>` : ""}
      <div class="toolbar">${st.checks.length ? `<button data-help="w.check" id="w-check" class="primary">Check this step</button><span class="muted small">${st.checks.length} check(s): ${st.checks.filter((c) => c.mode === "live").length} live, ${st.checks.filter((c) => c.mode === "config").length} config</span>` : '<span class="muted small">Nothing to check in this step: read it and move on.</span>'}
        ${st.apply ? '<button data-help="w.apply" id="w-apply" class="warn">Apply this step for me</button>' : ""}
        ${st.checks.length && r.passed !== true ? (r.manual_at ? '<button data-help="w.unmarkStep" id="w-unmark" class="hint-btn">Undo mark done</button>'
          : '<button data-help="w.markStep" id="w-mark" class="hint-btn">Mark step done</button>') : ""}</div>
      <div id="w-results"></div>
      ${nav}`;
    if ($("#w-check")) $("#w-check").onclick = () => run("step-check", `/api/labs/${l.id}/steps/${encodeURIComponent(st.id)}/check`);
    const mark = async (done) => {
      try {
        walk.status = await api(`/api/labs/${encodeURIComponent(l.id)}/steps/${encodeURIComponent(st.id)}/mark-done?done=${done}`, {method: "POST"});
        renderWalkStep(); $(done ? "#w-unmark" : "#w-mark")?.focus();
        toast(done ? "Step marked done by hand. Next → to continue." : "Manual mark removed", "ok");
        loadLabs(); loadCourses();
      } catch (e) { toast(`Could not update: ${e.message}`, "err", 8000); }
    };
    if ($("#w-mark")) $("#w-mark").onclick = () => mark(true);
    if ($("#w-unmark")) $("#w-unmark").onclick = () => mark(false);
    if ($("#w-apply")) $("#w-apply").onclick = () => confirm(`Type the configuration of this step into ${Object.keys(st.config).join(", ")} over the CML console?\n\nThe lab must be built and booted. Typing it yourself teaches more; this is for catching up.`) &&
      run("step-apply", `/api/labs/${l.id}/steps/${encodeURIComponent(st.id)}/apply`);
  }
  $$("#walk-step [data-copy]").forEach((b) => b.onclick = async () => toast(await copyText(b.dataset.copy) ? "Copied" : "Could not copy", "ok"));
  $("#w-prev").onclick = () => walkGo(i - 1);
  $("#w-next").onclick = () => walkGo(i + 1);
}
async function afterStepJob(kind, res) {
  if (!walk || walk.lab.id !== current) return;
  if (kind === "step-apply") {
    toast(`Applied on ${(res && res.applied || []).join(", ")}. Give the protocols a moment, then click Check this step.`, "ok", 8000);
    walk.status = await api(`/api/labs/${walk.lab.id}/walkthrough`); renderWalkStep(); return;
  }
  if (res && res.walkthrough) walk.status = res.walkthrough;
  const was = walk.index; renderWalkStep();
  if (res && $("#w-results") && (res.step || was < walk.lab.steps.length)) {
    $("#w-results").innerHTML = `<p><b>${res.passed ? '<span class="pass">Step passed</span>' : '<span class="fail">Not there yet</span>'}</b> ${res.earned}/${res.total} · mode ${esc(res.mode)}</p>
      ${(res.notes || []).map((x) => `<p class="note">${esc(x)}</p>`).join("")}
      <table>${res.results.map((c) => `<tr><td class="${c.passed ? "pass" : "fail"}">${c.passed ? "PASS" : "FAIL"}</td><td>${esc(c.device)}</td>
        <td>${esc(c.description)}<br><code class="small">${esc(c.command)}</code></td><td class="small">${c.passed ? "" : esc(c.hint)}
        <details><summary data-help="lab.output">output</summary><pre class="log">${esc(c.output)}</pre></details></td></tr>`).join("")}</table>`;
  }
  if (res && res.walkthrough && res.walkthrough.completed && !res.step) toast("Every required step passes: walkthrough completed!", "ok", 8000);
  loadLabs();
}

/* ---------------------------------------------------------------- progress dashboard */
const fmtDur = (s) => `${Math.floor(s / 3600)}h ${String(Math.floor(s / 60) % 60).padStart(2, "0")}m`;
const bar = (pct) => `<div class="pbar" role="img" aria-label="${Math.round(Math.max(0, Math.min(100, pct || 0)))}%"><div style="width:${Math.max(0, Math.min(100, pct || 0))}%"></div></div>`;
function openLab(id) { location.hash = "labs"; show("labs"); selectLab(id); }
async function loadProgress() {
  let p;
  try { p = await api("/api/progress"); } catch (e) { $("#progress").textContent = "Could not load progress: " + e.message; return; }
  const o = p.overall, st = p.streak, maxAct = Math.max(1, ...p.activity.map((a) => a.checks));
  const labBtns = (ids) => ids.map((id) => `<button data-help="p.openLab" class="hint-btn" data-open="${esc(id)}">${esc(id)}</button>`).join(" ");
  $("#progress").classList.remove("muted");
  $("#progress").innerHTML = `
    <div class="kpis">
      <div class="kpi" data-help="p.mastery"><b>${o.mastery_pct}%</b><span>overall mastery</span></div>
      <div class="kpi" data-help="p.solved"><b>${o.labs_solved}/${o.labs_total}</b><span>labs solved (${o.labs_attempted} attempted)</span></div>
      <div class="kpi" data-help="p.streak"><b>${st.current} day${st.current === 1 ? "" : "s"}</b><span>streak (longest ${st.longest})</span></div>
      <div class="kpi" data-help="p.time"><b>${fmtDur(o.time_spent_s)}</b><span>time spent</span></div>
      <div class="kpi" data-help="p.faults"><b>${o.faults_fixed}</b><span>faults fixed</span></div></div>
    ${p.walkthroughs && p.walkthroughs.total ? `<h3 data-help="p.walkthroughs">Walkthroughs <span class="muted small">(${p.walkthroughs.completed}/${p.walkthroughs.total} completed, not part of mastery)</span></h3>
      <table><tr><th>Walkthrough</th><th>Steps checked</th><th></th><th>Status</th><th></th></tr>${p.walkthroughs.labs.map((w) => `<tr><td>${esc(w.title)}</td>
        <td>${w.required_passed}/${w.required}${w.steps_marked ? ` <span class="muted small">+${w.steps_marked} by hand</span>` : ""}</td><td>${bar(w.pct)}</td><td>${w.completed ? '<span class="tag ok">completed</span>' + (w.marked_manually ? manTag("walkthrough") : "") : w.started ? '<span class="tag">in progress</span>' : '<span class="muted small">not started</span>'}</td>
        <td>${labBtns([w.id])}</td></tr>`).join("")}</table>` : ""}
    ${p.labs.some((l) => l.marked_manually) ? `<h3 data-help="p.marked">Labs marked complete by hand <span class="muted small">(count for courses, not for solved labs or mastery)</span></h3>
      <table><tr><th>Lab</th><th>Status</th><th>Best score</th><th></th></tr>${p.labs.filter((l) => l.marked_manually).map((l) => `<tr><td>${esc(l.title)}</td>
        <td><span class="tag ok">completed</span>${manTag()}</td><td>${l.attempts ? `${l.mastery_pct}%` : '<span class="muted small">not checked</span>'}</td><td>${labBtns([l.id])}</td></tr>`).join("")}</table>` : ""}
    ${(p.tracks || []).length > 1 || ((p.tracks || [])[0] && !p.tracks[0].encor) ? `<h3 data-help="p.tracks">Tracks</h3>
      <table><tr><th>Track</th><th>Mastery</th><th></th><th>Solved</th><th>Labs</th></tr>${p.tracks.map((t) => `<tr><td><b>${esc(t.id)}</b></td>
        <td>${t.mastery_pct}%</td><td>${bar(t.mastery_pct)}</td><td>${t.solved}/${t.labs}</td><td>${labBtns(t.lab_ids)}</td></tr>`).join("")}</table>` : ""}
    ${o.encor_labs ? `<h3 data-help="p.domains">ENCOR exam domains <span class="muted small">(${esc(p.blueprint)}; ENCOR mastery ${o.encor_mastery_pct}%)</span></h3>
    <table><tr><th>Domain</th><th>Weight</th><th>Mastery</th><th></th><th>Solved</th><th>Labs</th></tr>${p.domains.map((d) => `<tr>
      <td>${esc(d.id)} ${esc(d.name)}</td><td>${d.weight}%</td>${d.labs ? `<td>${d.mastery_pct}%</td><td>${bar(d.mastery_pct)}</td><td>${d.solved}/${d.labs}</td><td>${labBtns(d.lab_ids)}</td>`
      : '<td colspan="4" class="muted small">No labs for this domain yet (mostly theory topics). Study it separately.</td>'}</tr>`).join("")}</table>` : ""}
    <h3 data-help="p.weakest">Weakest topics</h3>
    <table>${p.weakest.map((i) => `<tr><td><b>${esc(i.id)}</b> ${esc(i.title)}</td><td>${i.mastery_pct}%</td><td>${bar(i.mastery_pct)}</td><td>${labBtns(i.lab_ids)}</td></tr>`).join("")}</table>
    <details><summary data-help="p.items">All topics covered by labs (${p.items.length})</summary>
      <table><tr><th>Item</th><th>Mastery</th><th></th><th>Solved</th><th>Labs</th></tr>${p.items.map((i) => `<tr><td><b>${esc(i.id)}</b> ${esc(i.title)}</td><td>${i.mastery_pct}%</td><td>${bar(i.mastery_pct)}</td><td>${i.solved}/${i.labs}</td><td>${labBtns(i.lab_ids)}</td></tr>`).join("")}</table></details>
    <h3 data-help="p.activity">Activity (last 30 days)</h3>
    <div class="activity">${p.activity.map((a) => `<span title="${esc(a.day)}: ${a.checks} check(s)" style="height:${4 + Math.round(36 * a.checks / maxAct)}px" class="${a.checks ? "on" : ""}"></span>`).join("")}</div>
    ${p.failed_checks.length ? `<h3 data-help="p.failed">Checks you fail most</h3><table>${p.failed_checks.map((f) => `<tr><td>${esc(f.description)}</td><td class="muted small">${esc(f.lab_id)} / ${esc(f.check_id)}</td><td>${f.count}×</td><td>${labBtns([f.lab_id])}</td></tr>`).join("")}</table>` : ""}
    <h3 data-help="p.recent">Recent checks</h3>${p.recent.length ? `<table><tr><th>When</th><th>Lab</th><th>Type</th><th>Score</th><th>Counted</th></tr>${p.recent.map((r) =>
      `<tr><td>${esc(r.ts)}</td><td>${esc(r.title)}</td><td>${esc(r.kind)}</td><td class="${r.passed ? "pass" : ""}">${r.score_pct}%</td><td>${r.adjusted_pct}%</td></tr>`).join("")}</table>` : '<p class="muted">No checks yet. Build a lab and click Check.</p>'}
    <p class="muted small">Mastery = best score per lab, minus ${p.rules.hint_penalty} points per hint used (capped at ${p.rules.revealed_cap}% after revealing the answer), averaged per topic; labs never checked count as 0. ENCOR mastery is weighted by the exam domain weights of the domains that have labs; with several tracks, overall mastery is the average over all labs.</p>`;
  $$("#progress [data-open]").forEach((b) => b.onclick = () => openLab(b.dataset.open));
}
$("#p-refresh").onclick = loadProgress;

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
function setPath(obj, path, v) { const ks = path.split("."); const last = ks.pop(); const t = ks.reduce((o, k) => (o[k] ??= {}), obj); if (v === undefined) delete t[last]; else t[last] = v; }
function renderForm() {
  const d = draft; const names = d.nodes.map((n) => n.name);
  const nodeOpts = (sel) => names.map((n) => `<option ${n === sel ? "selected" : ""}>${esc(n)}</option>`).join("");
  const portOpts = (sel) => [0, 1, 2, 3].map((p) => `<option value="${p}" ${p === sel ? "selected" : ""}>port ${p} (%if${p}%)</option>`).join("");
  if (d.type !== "walkthrough") d.solution ??= {};
  $("#tab-form").innerHTML = `${d.type === "walkthrough" ? `<p class="note">This is a walkthrough lab (${(d.steps || []).length} steps). Edit the steps (explanation, config per device, verify commands, checks) in the YAML tab; the form covers the general fields, nodes and links.</p>` : ""}
  <fieldset><legend>General</legend><div class="grid">
    ${field("f.id", "Lab id", "id", d.id)}${field("f.title", "Title", "title", d.title)}
    <label>Track<input data-help="f.track" data-path="track" data-type="track" placeholder="ENCOR" value="${esc(d.track || "")}"></label>
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
  else if (type === "track") v = (v.trim() && v.trim().toUpperCase() !== "ENCOR") ? v.trim() : undefined;  // ENCOR = default: leave the key out (older versions import it)
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
  $("#cml-dialog").showModal(); $("#cml-list").innerHTML = '<span class="spinner" aria-hidden="true"></span>Loading…';
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
  loadUpdateStatus().catch(() => {});
  const s = await api("/api/settings");
  const f = $("#settings-form");
  for (const k of ["cml_url", "username", "console_host", "console_port", "grading_mode", "platform", "node_limit", "ram_heavy_gb", "library_url", "device_username", "nxos_username", "ai_base_url", "ai_model"]) f[k].value = s[k] ?? "";
  for (const k of ["device_password", "nxos_password"]) { f[k].value = ""; f[k].placeholder = s[k + "_set"] ? "(set - leave blank to keep)" : (k === "nxos_password" ? "(same as the device login)" : ""); }
  loadHostKey().catch(() => {});
  libraryUrl = s.library_url || "";
  f.verify_tls.value = s.verify_tls === false ? "false" : (typeof s.verify_tls === "string" ? "ca" : "true");
  f.tls_ca.value = typeof s.verify_tls === "string" ? s.verify_tls : "";
  tlsUi();
  f.show_help.checked = s.show_help !== false; if (window.Help) Help.setVisible(f.show_help.checked);
  f.check_updates.checked = s.check_updates === true;
  f.resource_check.checked = s.resource_check !== false; f.resource_headroom_gb.value = s.resource_headroom_gb ?? 4;
  f.password.value = ""; f.password.placeholder = s.password_set ? "(saved - leave blank to keep)" : "";
  f.ai_api_key.value = ""; f.ai_api_key.placeholder = s.ai_api_key_set ? "(saved - leave blank to keep)" : "";
  presets = await api("/api/ai/presets");
  $("#ai-preset").innerHTML = `<option value="">(none)</option>` + Object.entries(presets).map(([k, p]) => `<option value="${k}" ${k === s.ai_preset ? "selected" : ""}>${esc(p.label)}</option>`).join("");
}
async function loadHostKey() {
  const h = await api("/api/console/hostkey"), box = $("#hostkey");
  if (!h.host) { box.textContent = "Console server SSH host key: set the CML URL first."; return; }
  box.innerHTML = h.key
    ? `Console server SSH host key for <b>${esc(h.key.host)}</b>: <code>${esc(h.key.type)} ${esc(h.key.sha256)}</code> <span class="muted">(MD5 ${esc(h.key.md5)}; trusted on first use)</span>
       <button data-help="s.forgetHostKey" type="button" id="hostkey-forget" class="hint-btn">Forget host key</button>`
    : `Console server SSH host key for <b>${esc(h.host)}</b>: not stored yet. It is saved on the first console connection (trust on first use).`;
  const b = $("#hostkey-forget");
  if (b) b.onclick = async () => {
    if (!confirm("Forget the stored SSH host key? The next console connection trusts whatever key the server sends. Only do this after reinstalling or upgrading CML.")) return;
    await api("/api/console/hostkey/forget", {method: "POST"}); toast("Host key forgotten", "ok"); loadHostKey();
  };
}
function tlsUi() {
  const v = $("#s-verify-tls").value;
  $("#tls-ca-row").hidden = v !== "ca"; $("#tls-warn").hidden = v !== "false";
}
$("#s-verify-tls").addEventListener("change", tlsUi);
$("#ai-preset").onchange = (e) => { const p = presets[e.target.value]; if (p) { const f = $("#settings-form"); f.ai_base_url.value = p.base_url; f.ai_model.value = p.model; } };
$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {cml_url: f.cml_url.value, username: f.username.value, password: f.password.value,
    verify_tls: f.verify_tls.value === "ca" ? (f.tls_ca.value.trim() || "true") : f.verify_tls.value,
    console_host: f.console_host.value, console_port: Number(f.console_port.value) || 22, grading_mode: f.grading_mode.value,
    platform: f.platform.value, node_limit: Number(f.node_limit.value) || 20, ram_heavy_gb: Number(f.ram_heavy_gb.value) || 16, library_url: f.library_url.value.trim(), remember_password: f.remember_password.checked,
    device_username: f.device_username.value.trim(), device_password: f.device_password.value, nxos_username: f.nxos_username.value.trim(), nxos_password: f.nxos_password.value,
    ai_preset: f.ai_preset.value, ai_base_url: f.ai_base_url.value, ai_model: f.ai_model.value, ai_api_key: f.ai_api_key.value,
    remember_ai_key: f.remember_ai_key.checked, show_help: f.show_help.checked, check_updates: f.check_updates.checked,
    resource_check: f.resource_check.checked, resource_headroom_gb: f.resource_headroom_gb.value === "" ? 4 : Number(f.resource_headroom_gb.value)};
  try {
    const r = await api("/api/settings", {method: "POST", body: JSON.stringify(body)});
    if (window.Help) Help.setVisible(r.show_help !== false);
    toast((r.settings_file ? `Settings saved (${r.settings_file})` : "Settings saved (memory only)") +
      (body.remember_password ? (r.keyring_saved ? "\nCML password stored in OS keyring" : "\nOS keyring unavailable") : ""), "ok");
    loadSettings();
  } catch (err) { toast("Settings not saved: " + err.message, "err", 9000); }
});

/* ---------------------------------------------------------------- updates
   The packaged app checks GitHub in the background (server side, see autoupdate.py), downloads and verifies a new
   version's patch, and this page asks: Update now / Later / Skip this version. Nothing installs without a click. */
const fmtSize = (n) => n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
const fmtWhen = (ts) => ts ? new Date(ts * 1000).toLocaleString([], {dateStyle: "short", timeStyle: "short"}) : "never";
const Upd = {timer: null, key: "", restarting: false, toasted: false};
async function checkUpdates(manual) {
  const out = $("#update-result");
  if (out) out.textContent = "Checking…";
  let r;
  try { r = await api("/api/update/check", {method: "POST"}); }
  catch (e) {
    const msg = `Could not check for updates: ${(e.data && e.data.error) || e.message}`;
    if (out) out.textContent = msg;
    if (manual) toast(msg, "err", 8000);
    return;
  }
  let text;
  if (r.status === "source") {
    const i = r.info;
    text = i.update_available ? `Version ${i.latest} is available (you have ${i.current}). Running from source: update with git pull.`
      : `You have the latest version (${i.current}).`;
    if (out) out.innerHTML = `${esc(text)} <a data-help="s.releaseLink" href="${esc(safeUrl(i.url))}" target="_blank" rel="noopener">Release page ↗</a>`;
  } else {
    text = {up_to_date: `You have the latest version (${r.latest || APP_JS_VERSION}).`,
      staged: `Version ${r.version} is downloaded and verified: see the prompt at the bottom left.`,
      full_download: `Version ${r.version} needs a full download (${r.reason}).`}[r.status] || "Done.";
    if (out) out.textContent = text;
  }
  if (manual) toast(text, "ok", 6000);
  pollUpdates();
}
function scheduleUpdatePoll(ms) {
  clearTimeout(Upd.timer);
  Upd.timer = setTimeout(pollUpdates, ms);
}
async function pollUpdates() {
  let st;
  try { st = await api("/api/update/auto"); } catch (e) { scheduleUpdatePoll(60000); return; }
  renderUpdatePrompt(st);
  renderFullBanner(st);
  const el = $("#update-auto-status");
  if (el) {
    let t = st.enabled ? `Automatic checks on · last check ${fmtWhen(st.last_check)} · next ${fmtWhen(st.next_check)}`
      : `Automatic checks off${st.reason ? ": " + st.reason : ""}`;
    if (st.enabled && st.failures) t += ` · last attempt failed, retrying later (${st.last_error || "error"})`;
    if (st.failed_update) t += ` · update ${st.failed_update.version} could not start and was rolled back; it will not be offered again`;
    el.textContent = t;
  }
  if (st.just_updated && !Upd.toasted) {
    Upd.toasted = true;
    toast(`Updated to ${st.just_updated.version}`, "ok", 10000);
    api("/api/update/ack", {method: "POST"}).catch(() => {});
  }
  const a = st.apply;
  if (a && a.state === "restarting" && st.offer) waitForRestart(st.offer.version);
  scheduleUpdatePoll(a && ["waiting", "installing", "restarting"].includes(a.state) ? 2000 : 60000);
}
function renderUpdatePrompt(st) {
  const box = $("#update-prompt"), o = st.offer, a = st.apply || {};
  const key = JSON.stringify([o, a.state, a.waiting_for, a.error]);
  if (key === Upd.key) return;
  Upd.key = key;
  if (!o) { box.hidden = true; box.innerHTML = ""; return; }
  const v = esc(o.version), busy = (a.waiting_for && a.waiting_for.length ? a.waiting_for : o.busy) || [];
  let msg = `A small update (${fmtSize(o.size || 0)}) is downloaded and verified. You have ${esc(APP_JS_VERSION)}.`;
  let buttons = `<button data-help="u.updateNow" type="button" class="primary" data-upd="now">Update now</button>
    <button data-help="u.later" type="button" data-upd="later">Later</button>
    <button data-help="u.skip" type="button" data-upd="skip">Skip this version</button>`;
  if (a.state === "waiting") {
    msg = `Waiting for ${esc(busy.join(", ") || "the running work")} to finish; then the update installs and the app restarts. Nothing is interrupted.`;
    buttons = `<button data-help="u.cancel" type="button" data-upd="cancel">Cancel</button>`;
  } else if (a.state === "installing") { msg = "Installing the update…"; buttons = ""; }
  else if (a.state === "restarting") { msg = "Restarting CML Lab Builder… this page reconnects by itself."; buttons = ""; }
  else if (a.state === "installed") { msg = `Installed. ${esc(a.error || "Close the app and start it again to finish.")}`; buttons = ""; }
  else {
    if (a.state === "error") msg = `The update could not be installed: ${esc(a.error || "unknown error")}. You can try again.`;
    if (busy.length) msg += ` Update now will wait until ${esc(busy.join(", "))} finishes.`;
  }
  box.innerHTML = `<h3>CML Lab Builder ${v} is ready</h3><p>${msg}</p>
    <p class="small"><a data-help="u.notes" href="${esc(safeUrl(o.url))}" target="_blank" rel="noopener">Release notes ↗</a> ·
    <a data-help="u.notes" href="${esc(safeUrl(o.changelog))}" target="_blank" rel="noopener">Changelog ↗</a></p>
    <div class="toolbar">${buttons}</div>`;
  box.hidden = false;
  box.querySelectorAll("[data-upd]").forEach((b) => { b.onclick = () => updateAnswer(b.dataset.upd, o.version); });
}
async function updateAnswer(what, version) {
  const q = encodeURIComponent(version);
  const path = {now: `/api/update/apply?version=${q}`, later: "/api/update/later", skip: `/api/update/skip?version=${q}`,
    cancel: "/api/update/cancel"}[what];
  try { await api(path, {method: "POST"}); }
  catch (e) { toast(`Update: ${(e.data && e.data.error) || e.message}`, "err", 9000); }
  if (what === "skip") toast(`Version ${version} will not be offered again. Settings > Check for updates now still finds it.`, "ok", 8000);
  Upd.key = "";
  pollUpdates();
}
function renderFullBanner(st) {
  const b = $("#update-full"), f = st.full_download;
  if (!f) { b.hidden = true; b.innerHTML = ""; return; }
  if (b.dataset.version === f.version && !b.hidden) return;
  b.dataset.version = f.version;
  b.innerHTML = `<button data-help="u.fullDismiss" type="button" class="hint-btn">Dismiss</button>
    CML Lab Builder ${esc(f.version)} is available but needs a <b>full download</b> (${esc(f.reason || "new runtime")}); it cannot be installed as a patch.
    <a data-help="u.fullLink" href="${esc(safeUrl(f.url))}" target="_blank" rel="noopener">${f.asset ? "Download " + esc(f.asset) : "Download it from the release page"} ↗</a>${f.how ? ", then " + esc(f.how) : ""}.
    Your data and settings are kept.`;
  b.hidden = false;
  b.querySelector("button").onclick = async () => {
    b.hidden = true;
    await api(`/api/update/dismiss-full?version=${encodeURIComponent(f.version)}`, {method: "POST"}).catch(() => {});
  };
}
async function waitForRestart(version) {
  if (Upd.restarting) return;
  Upd.restarting = true;
  const t0 = Date.now();
  await new Promise((res) => setTimeout(res, 1500));
  while (Date.now() - t0 < 120000) {
    try {
      const h = await fetch("/api/health", {cache: "no-store"}).then((x) => x.json());
      if (h.ok && (h.version === version || Date.now() - t0 > 20000)) { location.reload(); return; }
    } catch (e) { /* still restarting */ }
    await new Promise((res) => setTimeout(res, 1000));
  }
  Upd.restarting = false;
  banner("The app did not come back within 2 minutes. Start it again from the CML Lab Builder shortcut or folder.");
}
async function loadUpdateStatus() {
  const el = $("#update-status");
  if (!el) return;
  let st;
  try { st = await api("/api/update/status"); } catch (e) { el.textContent = "App code: unknown"; return; }
  const a = st.active || {version: st.version, source: "source tree"};
  const src = {bundled: "built-in copy", installed: "installed update"}[a.source] || a.source;
  let t = `App code ${a.version} (${src}) · runtime ${st.runtime ?? "-"}`;
  if (!st.patchable) t += ` · patch updates not available: ${st.reason}`;
  else if (st.previous || st.bundled_version) t += ` · fallback: ${st.previous || "built-in " + st.bundled_version}`;
  if (st.failed && st.failed.version) t += ` · update ${st.failed.version} was rolled back (${st.failed.reason})`;
  if (st.restart_needed && st.next_start) t += ` · restart to switch to ${st.next_start.version}`;
  el.textContent = t;
  $("#s-update-rollback").hidden = !st.can_rollback;
  $("#s-update-restart").hidden = !(st.restart_needed && st.can_restart);
}
$("#s-update-rollback").onclick = async () => {
  if (!confirm("Go back to the previous app code? It takes effect after a restart.")) return;
  try {
    const r = await api("/api/update/rollback", {method: "POST"});
    toast(r.next ? `Rolled back: the next start uses ${r.next.version}.` : "Rolled back.", "ok", 8000);
  } catch (e) { toast(`Roll back failed: ${(e.data && e.data.error) || e.message}`, "err", 9000); }
  loadUpdateStatus();
};
$("#s-update-restart").onclick = async () => {
  const before = (await api("/api/update/status").catch(() => ({}))).next_start;
  try { await api("/api/update/restart", {method: "POST"}); }
  catch (e) { toast(`Restart failed: ${(e.data && e.data.error) || e.message}`, "err", 9000); return; }
  banner("Restarting CML Lab Builder… this page reloads when it is back.");
  const t0 = Date.now();
  await new Promise((res) => setTimeout(res, 1500));
  while (Date.now() - t0 < 90000) {
    try {
      const h = await fetch("/api/health", {cache: "no-store"}).then((x) => x.json());
      if (h.ok && (!before || h.version === before.version || Date.now() - t0 > 8000)) { location.reload(); return; }
    } catch (e) { /* still restarting */ }
    await new Promise((res) => setTimeout(res, 1000));
  }
  banner("The app did not come back within 90 s. Start it again from the CML Lab Builder shortcut or folder.");
};
$("#s-update-check").onclick = () => checkUpdates(true);
$("#update-link").onclick = (e) => { e.preventDefault(); show("settings"); location.hash = "settings"; checkUpdates(true); };

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
    banner(`CML Lab Builder was updated to v${h.version} while this page was open (page is v${page}). Reload the page (F5) to use it.`);
  }
}

/* ---------------------------------------------------------------- boot */
/* the data folder moved (the old ENCOR folder -> cml-lab-builder): say so once */
async function dataFolderNote() {
  const d = await api("/api/data-folder");
  if (d.state !== "moved" || d.notified) return;
  toast(`Your data moved to ${d.to}\n(from ${d.from}; the old folder was left in place, with a MOVED.txt note)`, "ok", 15000);
  await api("/api/data-folder/ack", {method: "POST"});
}
(async () => {
  const step = async (name, fn) => { try { await fn(); } catch (e) { if (!e.shown) banner(`Startup step "${name}" failed: ${e.message}`); } };
  await step("version check", versionCheck);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { versionCheck().catch(() => {}); pollUpdates(); } });
  await step("settings", async () => { const s = await api("/api/settings"); libraryUrl = s.library_url || ""; if (window.Help) Help.setVisible(s.show_help !== false); });
  await step("check templates", async () => { templates = await api("/api/templates"); });
  await step("lab list", loadLabs);
  await step("courses", loadCourses);
  step("data folder", dataFolderNote);
  pollUpdates();   // the update prompt (the server does the checking); never blocks startup
  const v = (location.hash || "#labs").slice(1);
  show(VIEWS.includes(v) ? v : "labs");
})();

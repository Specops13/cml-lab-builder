/* Fuzzy search for the library and the lab list (vanilla JS, no dependencies; also loads in node for the tests).
 *
 * Fuzzy.prepare({title: [text, weight], ...}) -> a prepared record (normalized once, when the index loads)
 * Fuzzy.search(query, records) -> [{i, score, hits: {field: [original char indices]}}], best first
 * Fuzzy.highlight(text, indices, esc) -> HTML with the matched characters in <mark>
 *
 * Each query word (AND) is scored against every field, and the best field wins (field weight x match score):
 *   substring   100 (+ bonus at a word start, more for a whole word or the start of the field)
 *   subsequence  30-90 ("mcast" in multicast, "ospf stb" -> stub): bonus per word start and per run of
 *                consecutive characters; rejected when the characters are spread too far apart
 *   typo         30-60 (Damerau-Levenshtein against single words or word prefixes: 1 edit for 4-7
 *                letters, 2 for longer words, e.g. "mutlicast", "redistrbution")
 * Matching is case- and accent-insensitive; punctuation counts as a word gap ("vrf lit" -> "VRF-Lite").
 */
(function (root) {
  "use strict";

  function normalize(s) {
    s = String(s == null ? "" : s);
    let out = "";
    const map = [];
    for (let i = 0; i < s.length; i++) {
      let c = s[i].toLowerCase();
      if (c > "\x7f") c = c.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      if (c.length !== 1 || !/[a-z0-9]/.test(c)) c = " ";
      out += c; map.push(i);
    }
    return {n: out, map};
  }

  const isAlnum = (c) => c !== " " && c !== undefined;
  const isDigit = (c) => c >= "0" && c <= "9";

  // which of a-z / 0-9 occur (two 32-bit masks): rules out fields that lack a letter of the word
  function charMask(str) {
    let a = 0, b = 0;
    for (let i = 0; i < str.length; i++) {
      const c = str.charCodeAt(i);
      if (c >= 97 && c <= 122) a |= 1 << (c - 97); else if (c >= 48 && c <= 57) b |= 1 << (c - 48);
    }
    return [a, b];
  }
  function missing(tm, fm) {     // number of distinct characters of the word that the field lacks
    let x = tm[0] & ~fm[0], y = tm[1] & ~fm[1], k = 0;
    while (x) { x &= x - 1; k++; }
    while (y) { y &= y - 1; k++; }
    return k;
  }

  function prepField(text, w) {
    const {n, map} = normalize(text);
    const starts = new Uint8Array(n.length);
    const words = [];
    for (let i = 0; i < n.length; i++) {
      const c = n[i];
      if (!isAlnum(c)) continue;
      const p = n[i - 1];
      if (!isAlnum(p) || isDigit(p) !== isDigit(c)) {
        starts[i] = 1;
        let j = i + 1;
        while (j < n.length && isAlnum(n[j]) && isDigit(n[j]) === isDigit(c)) j++;
        words.push([i, j]);
      }
    }
    return {text: String(text == null ? "" : text), n, map, starts, words, w, mask: charMask(n)};
  }

  function prepare(fields) {
    const out = [];
    for (const key in fields) {
      const [text, w] = fields[key];
      if (text) out.push(Object.assign(prepField(text, w), {key}));
    }
    return {fields: out};
  }

  function tokens(q) {
    return normalize(q).n.split(" ").filter(Boolean);
  }

  function range(a, b) { const r = []; for (let i = a; i < b; i++) r.push(i); return r; }

  function substring(tok, f) {
    let best = null;
    for (let p = f.n.indexOf(tok); p !== -1; p = f.n.indexOf(tok, p + 1)) {
      const ws = f.starts[p] === 1, we = !isAlnum(f.n[p + tok.length]) || isDigit(f.n[p + tok.length]) !== isDigit(f.n[p + tok.length - 1]);
      const s = 100 + (ws ? 25 : 0) + (ws && we ? 15 : 0) + (p === 0 ? 5 : 0) - Math.min(p, 40) * 0.05;
      if (!best || s > best.s) best = {s, idx: range(p, p + tok.length)};
      if (ws && we && p === 0) break;
    }
    return best;
  }

  // greedy subsequence from a start position; at each step prefer the next word start if it comes before a
  // continuation that is not consecutive (keeps "ospf stb" -> s-t-u-b and "mcast" -> m...c-a-s-t tight)
  function subseqFrom(tok, f, p0) {
    if (tok.length <= 3 && !f.starts[p0]) return null;     // short words: abbreviations start at a word ("stb")
    const n = f.n, idx = [p0];
    let p = p0, bounds = f.starts[p0], runs = 0;
    for (let k = 1; k < tok.length; k++) {
      const c = tok[k];
      if (n[p + 1] === c) { p++; runs++; idx.push(p); if (f.starts[p]) bounds++; continue; }
      let q = n.indexOf(c, p + 1);
      if (q === -1) return null;
      for (let r = q; r !== -1 && r - p < 40; r = n.indexOf(c, r + 1)) { if (f.starts[r]) { q = r; break; } }
      p = q; idx.push(p); if (f.starts[p]) bounds++;
    }
    const span = idx[idx.length - 1] - idx[0] + 1;
    const allStarts = bounds === tok.length;
    if (!allStarts && span > Math.max(3 * tok.length, tok.length + 6)) return null;
    let s = 40 + 10 * bounds + 6 * runs - (span - tok.length) * 1.5 + (f.starts[p0] ? 10 : 0);
    return s < 30 ? null : {s: Math.min(90, s), idx};   // too scattered to be a real abbreviation
  }

  function subsequence(tok, f) {
    if (tok.length < 2) return null;
    let best = null, tries = 0;
    for (let p = f.n.indexOf(tok[0]); p !== -1 && tries < 12; p = f.n.indexOf(tok[0], p + 1)) {
      if (!f.starts[p] && tries > 6) continue;
      tries++;
      const m = subseqFrom(tok, f, p);
      if (m && (!best || m.s > best.s)) best = m;
    }
    return best;
  }

  // Damerau-Levenshtein (optimal string alignment) with an early exit above max; reuses three row buffers
  let R0 = new Int32Array(64), R1 = new Int32Array(64), R2 = new Int32Array(64);
  function editDistance(a, b, max) {
    const la = a.length, lb = b.length;
    if (Math.abs(la - lb) > max) return max + 1;
    if (lb + 1 > R0.length) { R0 = new Int32Array(lb + 1); R1 = new Int32Array(lb + 1); R2 = new Int32Array(lb + 1); }
    let p2 = R0, p1 = R1, cur = R2;
    for (let j = 0; j <= lb; j++) p1[j] = j;
    for (let i = 1; i <= la; i++) {
      cur[0] = i;
      let rowMin = i;
      const ca = a.charCodeAt(i - 1), cp = i > 1 ? a.charCodeAt(i - 2) : -1;
      for (let j = 1; j <= lb; j++) {
        const cb = b.charCodeAt(j - 1);
        let v = Math.min(p1[j] + 1, cur[j - 1] + 1, p1[j - 1] + (ca === cb ? 0 : 1));
        if (i > 1 && j > 1 && ca === b.charCodeAt(j - 2) && cp === cb && p2[j - 2] + 1 < v) v = p2[j - 2] + 1;
        cur[j] = v; if (v < rowMin) rowMin = v;
      }
      if (rowMin > max) return max + 1;
      const t = p2; p2 = p1; p1 = cur; cur = t;
    }
    return p1[lb];
  }

  function typo(tok, f) {
    const max = tok.length >= 8 ? 2 : tok.length >= 4 ? 1 : 0;
    if (!max) return null;
    let best = null;
    for (const [a, b] of f.words) {
      const word = f.n.slice(a, b);
      if (word.length + max < tok.length) continue;
      let d = editDistance(tok, word, max), end = b;
      if (d > max && word.length > tok.length) {          // typo in a prefix of a longer word ("multicat" -> multicast)
        for (const L of [tok.length - 1, tok.length, tok.length + 1]) {
          if (L < 3 || L > word.length) continue;
          const dd = editDistance(tok, word.slice(0, L), max);
          if (dd < d) { d = dd; end = a + L; }
        }
        if (d <= max) d += 0.5;
      }
      if (d <= max) {
        const s = 60 - 15 * d;
        if (!best || s > best.s) best = {s, idx: range(a, end)};
      }
    }
    return best;
  }

  function matchToken(tok, f, tm) {
    const miss = missing(tm, f.mask);
    if (miss > (tok.length >= 8 ? 2 : tok.length >= 4 ? 1 : 0)) return null;   // not even a typo away
    if (miss) return typo(tok, f);
    const s = substring(tok, f);
    if (s) return s;
    const a = subsequence(tok, f), b = typo(tok, f);
    return a && b ? (a.s >= b.s ? a : b) : a || b;
  }

  // per record: the best field for one token ({s: weighted score, key, idx: original indices}) or null.
  // Cached per record list, so a keystroke only scores the word being typed (the others are unchanged).
  const cache = new WeakMap();
  function tokenResults(tok, records, phrase) {
    let m = cache.get(records);
    if (!m) { m = new Map(); cache.set(records, m); }
    const ck = (phrase ? "\u0001" : "") + tok;
    let arr = m.get(ck);
    if (arr) { m.delete(ck); m.set(ck, arr); return arr; }     // keep recently used last
    arr = new Array(records.length);
    const tm = charMask(tok);
    for (let i = 0; i < records.length; i++) {
      let best = null, bf = null, sum = 0;
      for (const f of records[i].fields) {
        const mt = phrase ? (missing(tm, f.mask) ? null : substring(tok, f)) : matchToken(tok, f, tm);
        if (!mt) continue;
        const v = mt.s * f.w;
        sum += v;
        if (!best || v > best.s * bf.w) { best = mt; bf = f; }
      }
      arr[i] = best ? {s: best.s * bf.w + 0.15 * (sum - best.s * bf.w),   // small bonus when other fields match too
                       key: bf.key, idx: best.idx.map((k) => bf.map[k])} : null;
    }
    m.set(ck, arr);
    if (m.size > 64) m.delete(m.keys().next().value);
    return arr;
  }

  // query words (split on spaces); a word with punctuation inside ("3.1.b", "vrf-lite", "17-mpls") is tried as a
  // phrase first and otherwise as its parts (all must match)
  function words(q) {
    return String(q == null ? "" : q).split(/\s+/).map((w) => normalize(w).n.split(" ").filter(Boolean)).filter((p) => p.length);
  }

  function search(query, records, opts) {
    const ws = words(query);
    const out = [];
    if (!ws.length) return out;
    const limit = (opts && opts.limit) || Infinity;
    const groups = ws.map((parts) => ({phrase: parts.length > 1 ? tokenResults(parts.join(" "), records, true) : null,
                                       parts: parts.map((t) => tokenResults(t, records, false))}));
    for (let i = 0; i < records.length; i++) {
      let total = 0, ok = true;
      const hits = {};
      const add = (r, f) => { total += r.s * f; const h = hits[r.key] || (hits[r.key] = []); for (const k of r.idx) h.push(k); };
      for (const g of groups) {
        const ph = g.phrase && g.phrase[i];
        if (ph) { add(ph, g.parts.length); continue; }          // the exact phrase counts like all its parts
        const rs = g.parts.map((a) => a[i]);
        if (rs.some((r) => !r)) { ok = false; break; }
        rs.forEach((r) => add(r, g.phrase ? 0.5 : 1));           // parts found apart: weaker
      }
      if (ok) out.push({i, score: total, hits});
    }
    out.sort((a, b) => b.score - a.score || a.i - b.i);
    return out.length > limit ? out.slice(0, limit) : out;
  }

  const ESC = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

  function highlight(text, indices, esc) {
    esc = esc || ESC;
    text = String(text == null ? "" : text);
    if (!indices || !indices.length) return esc(text);
    const on = new Set(indices);
    let html = "", open = false;
    for (let i = 0; i < text.length; i++) {
      const m = on.has(i);
      if (m && !open) { html += "<mark>"; open = true; }
      if (!m && open) { html += "</mark>"; open = false; }
      html += esc(text[i]);
    }
    return html + (open ? "</mark>" : "");
  }

  // search words for CML node definitions, so "nexus" or "ios-xe" finds the labs that use them
  const NODE_ALIASES = {
    "iol-xe": "iol ios-xe router", "ioll2-xe": "iol l2 ios-xe switch", "iol-xe-serial-4eth": "iol ios-xe serial",
    "iosv": "iosv router", "iosvl2": "iosvl2 switch", "nxosv9000": "nexus nx-os nxos 9000v", "csr1000v": "csr ios-xe",
    "cat8000v": "catalyst 8000v ios-xe", "cat9000v-uadp": "catalyst 9000v switch", "cat9000v-q200": "catalyst 9000v switch",
    "iosxrv9000": "ios-xr xrv", "asav": "asa firewall", "alpine": "linux host", "ubuntu": "linux host", "server": "host",
  };
  function nodeTags(defs) { return (defs || []).map((d) => d + " " + (NODE_ALIASES[d] || "")).join(" "); }

  // the library page's searchable fields (weights) for an index item (/api/library), shared with the tests
  const LIB_FIELDS = {title: 3, id: 2.5, topics: 2.2, blueprint: 2, domain: 2, nodes: 2, aliases: 1.5, kind: 2, courses: 2, labs: 1.5, description: 1};
  const library = {
    FIELDS: LIB_FIELDS,
    labels: {},           // topic id -> label (the vocabulary from /api/library), set by the page

    text(it, key) {
      switch (key) {
        case "blueprint": return (it.blueprint || []).join(", ");
        case "nodes": return (it.node_types || []).join(", ");
        case "aliases": return nodeTags(it.node_types) + " " + (it.platforms || []).join(" ") + " " + (it.track || "");
        case "kind": return [it.kind, it.type, it.ram_heavy ? "ram heavy" : "", it.starter ? "starter" : ""].join(" ");
        case "courses": return (it.in_courses || []).length ? "In: " + it.in_courses.join(", ") : "";
        case "labs": return (it.labs || []).join(", ");
        case "topics": return (it.topics || []).map((t) => library.labels[t] || t).join(", ");
        default: return it[key] == null ? "" : String(it[key]);
      }
    },
    addCourses(items) {     // in_courses: the titles of the courses that list a lab
      const of = {};
      for (const c of items) if (c.kind === "course") for (const l of c.labs || []) (of[l] = of[l] || []).push(c.title);
      for (const it of items) it.in_courses = it.kind === "lab" ? (of[it.id] || []) : [];
      return items;
    },
    record(it) {
      const f = {};
      for (const k in LIB_FIELDS) f[k] = [library.text(it, k), LIB_FIELDS[k]];
      return prepare(f);
    },
  };

  const api = {NODE_ALIASES, nodeTags, library, normalize, prepare, tokens, words, search, highlight, editDistance};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Fuzzy = api;
})(typeof window !== "undefined" ? window : this);

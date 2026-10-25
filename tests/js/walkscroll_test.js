// Tests for cmllab/web/static/walkscroll.js with a tiny fake DOM (run by tests/test_walk_scroll.py with node).
//   node tests/js/walkscroll_test.js   -> prints JSON {failures, cases}
"use strict";
const path = require("path");
const W = require(path.join(__dirname, "../../cmllab/web/static/walkscroll.js"));
const failures = [], cases = {};
const expect = (cond, msg) => { if (!cond) failures.push(msg); };

function el(opts = {}) {
  const e = {style: opts.style || {}, top: opts.top || 0, height: opts.height || 20, parentElement: opts.parent || null,
    scrollHeight: opts.scrollHeight || 0, clientHeight: opts.clientHeight || 0, attrs: {}, classes: new Set(), calls: [],
    getBoundingClientRect() { return {top: this.top, bottom: this.top + this.height, height: this.height}; },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    classList: null,
    focus(o) { this.focused = o || true; },
    scrollBy(o, y) { this.calls.push(typeof o === "object" ? o : {top: y}); },
    contains(x) { for (let p = x; p; p = p.parentElement) if (p === this) return true; return false; }};
  e.classList = {add: (c) => e.classes.add(c)};
  return e;
}
function win({headers = [], reduce = false} = {}) {
  const body = el(), html = el();
  const w = {document: {body, documentElement: html, querySelectorAll: () => headers}, calls: [],
    getComputedStyle: (x) => x.style, matchMedia: (q) => ({matches: reduce && q.includes("reduce")}),
    scrollBy(o, y) { this.calls.push(typeof o === "object" ? o : {top: y}); }};
  return {w, body};
}

// 1. page scroll, sticky header 56 px: the step's top lands just below the header, smooth
{
  const header = el({style: {position: "sticky"}, top: 0, height: 56});
  const {w, body} = win({headers: [header]});
  const box = el({parent: body, top: 900, style: {}}), h3 = el({parent: box, top: 905, style: {}});
  const r = W.toStep(h3, w, box);
  cases.page = r && {delta: r.delta, behavior: r.behavior, calls: w.calls};
  expect(r.scroller === null && w.calls.length === 1, "page: window.scrollBy once");
  expect(w.calls[0].top === 900 - 56 - W.GAP && w.calls[0].behavior === "smooth", "page: delta below the sticky header, smooth: " + JSON.stringify(w.calls[0]));
  expect(h3.attrs.tabindex === "-1" && h3.focused && h3.focused.preventScroll === true, "page: heading focused (tabindex -1, preventScroll)");
  expect(h3.classes.has("walk-focus"), "page: heading gets walk-focus (no focus ring)");
}
// 2. prefers-reduced-motion: instant; scrolling up (Previous) works too
{
  const header = el({style: {position: "sticky"}, top: 0, height: 56});
  const {w, body} = win({headers: [header], reduce: true});
  const box = el({parent: body, top: -400, style: {}}), h3 = el({parent: box, top: -395, style: {}});
  const r = W.toStep(h3, w, box);
  expect(r.behavior === "instant" && w.calls[0].behavior === "instant", "reduced motion: instant");
  expect(w.calls[0].top === -400 - 56 - W.GAP, "previous: scrolls up to the step top: " + w.calls[0].top);
}
// 2b. reduced motion: a nudge right after the jump (scroll anchoring) is corrected on the next frame
{
  const {w, body} = win({reduce: true});
  const frames = []; w.requestAnimationFrame = (f) => frames.push(f);
  const box = el({parent: body, top: 500, style: {}});
  w.scrollBy = function (o) { this.calls.push(o); box.top -= o.top; if (this.calls.length === 1) box.top -= 18; };
  W.toStep(box, w, box);
  expect(frames.length === 1, "reduced motion: one correction frame");
  frames[0]();
  expect(w.calls.length === 2 && w.calls[1].top === -18 && w.calls[1].behavior === "instant" && box.top === W.GAP,
         "reduced motion: corrected to the step top: " + JSON.stringify(w.calls) + " " + box.top);
}
// 3. inner scroll container: scroll it, not the page; a sticky header outside it does not count
{
  const header = el({style: {position: "sticky"}, top: 0, height: 56});
  const {w, body} = win({headers: [header]});
  const pane = el({parent: body, top: 120, style: {overflowY: "auto"}, scrollHeight: 3000, clientHeight: 500});
  const box = el({parent: pane, top: 700, style: {}}), h3 = el({parent: box, top: 705, style: {}});
  const r = W.toStep(h3, w, box);
  expect(r.scroller === pane && pane.calls.length === 1 && w.calls.length === 0, "container: scrolls the pane only");
  expect(pane.calls[0].top === 700 - 120 - W.GAP, "container: relative to the pane top: " + pane.calls[0].top);
}
// 4. a container with overflow auto that does not scroll is skipped; header static (narrow screens) = no offset
{
  const header = el({style: {position: "static"}, top: 0, height: 56});
  const {w, body} = win({headers: [header]});
  const pane = el({parent: body, top: 0, style: {overflowY: "auto"}, scrollHeight: 400, clientHeight: 400});
  const box = el({parent: pane, top: 300, style: {}}), h3 = el({parent: box, top: 300, style: {}});
  const r = W.toStep(h3, w, box);
  expect(r.scroller === null && w.calls[0].top === 300 - W.GAP, "static header: no offset, page scroll");
}
// 5. already in place: no scroll call, focus still moves; no heading: nothing happens
{
  const header = el({style: {position: "fixed"}, top: 0, height: 50});
  const {w, body} = win({headers: [header]});
  const h3 = el({parent: body, top: 50 + W.GAP, style: {}});
  const r = W.toStep(h3, w);
  expect(r.delta === 0 && w.calls.length === 0 && h3.focused, "no-op scroll, focus moved");
  expect(W.toStep(null, w) === null, "null heading");
}
// 6. scrollBy without options support (old engines): falls back to scrollBy(x, y)
{
  const {w, body} = win();
  w.scrollBy = function (o, y) { if (typeof o === "object") throw new TypeError("no options"); this.calls.push({top: y}); };
  const h3 = el({parent: body, top: 208, style: {}});
  W.toStep(h3, w);
  expect(w.calls.length === 1 && w.calls[0].top === 200, "fallback scrollBy(0, y)");
}
process.stdout.write(JSON.stringify({failures, cases}));

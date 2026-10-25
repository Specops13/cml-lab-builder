/* Walkthrough step scrolling (3.3.3; vanilla JS, no dependencies; also loads in node for the tests).
 *
 * WalkScroll.toStep(heading, win, anchor) - after Next / Previous / a jump to a step: scroll the nearest scroll
 *   container (an ancestor with overflow-y auto/scroll that actually scrolls, else the page) so the top of the step
 *   (anchor, e.g. the step's box; default the heading) sits at the
 *   top of the visible area, below any sticky / fixed header that covers it; instant when the user prefers reduced
 *   motion, smooth otherwise. Then move keyboard focus to the heading (tabindex="-1", focus({preventScroll})) so
 *   screen readers announce the new step and Tab continues from there; the heading gets no focus ring
 *   (class walk-focus, see style.css) because it is not a control.
 * Returns {scroller, delta, behavior} for the tests.
 */
(function (root) {
  "use strict";
  const GAP = 8;   // px of breathing room between the header and the heading

  function scrollerOf(el, win) {
    for (let p = el.parentElement; p; p = p.parentElement) {
      if (p === win.document.body || p === win.document.documentElement) break;
      const oy = win.getComputedStyle(p).overflowY;
      if ((oy === "auto" || oy === "scroll" || oy === "overlay") && p.scrollHeight > p.clientHeight) return p;
    }
    return null;   // the page itself
  }

  // Bottom edge of sticky/fixed elements pinned to the top of the viewport (the app header), 0 if none.
  function stickyOffset(win, scroller) {
    const top = scroller ? scroller.getBoundingClientRect().top : 0;
    let off = 0;
    for (const h of win.document.querySelectorAll("header, [data-sticky-top]")) {
      const cs = win.getComputedStyle(h);
      if (cs.position !== "sticky" && cs.position !== "fixed") continue;
      if (scroller && !scroller.contains(h) && cs.position === "sticky") continue;
      const r = h.getBoundingClientRect();
      if (r.height > 0 && r.top <= top + 1) off = Math.max(off, r.bottom - top);
    }
    return Math.max(0, off);
  }

  function reducedMotion(win) {
    try { return !!(win.matchMedia && win.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (e) { return false; }
  }

  function offBy(anchor, win, scroller) {
    const top = scroller ? scroller.getBoundingClientRect().top : 0;
    return Math.round(anchor.getBoundingClientRect().top - top - stickyOffset(win, scroller) - GAP);
  }

  function scroll(target, delta, behavior) {
    if (delta === 0) return;
    try { target.scrollBy({top: delta, left: 0, behavior}); } catch (e) { target.scrollBy(0, delta); }
  }

  function toStep(heading, win, anchor) {
    win = win || root;
    if (!heading) return null;
    anchor = anchor || heading;
    const scroller = scrollerOf(anchor, win);
    const delta = offBy(anchor, win, scroller);
    const behavior = reducedMotion(win) ? "instant" : "smooth";
    const target = scroller || win;
    scroll(target, delta, behavior);
    // An instant jump can be nudged right after by the browser's scroll anchoring (e.g. when the focused Next
    // button is replaced by a key press); re-measure on the next frame and correct it, still instantly.
    if (behavior === "instant" && win.requestAnimationFrame) {
      win.requestAnimationFrame(() => { const d = offBy(anchor, win, scroller); if (Math.abs(d) > 1) scroll(target, d, "instant"); });
    }
    heading.setAttribute("tabindex", "-1");
    heading.classList.add("walk-focus");
    try { heading.focus({preventScroll: true}); } catch (e) { heading.focus(); }
    return {scroller, delta, behavior};
  }

  const api = {toStep, scrollerOf, stickyOffset, reducedMotion, GAP};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WalkScroll = api;
})(typeof window !== "undefined" ? window : this);

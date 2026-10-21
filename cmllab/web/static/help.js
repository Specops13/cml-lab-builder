"use strict";
/* Help system. Text lives in help.json; elements opt in with data-help="key" (or data-help-text="literal").
   - buttons, links, list items and unlabeled controls get a native title tooltip
   - controls inside a <label> and plain text elements get a small "?" icon with a custom tooltip:
     300 ms hover delay, instant on keyboard focus, closes on mouseleave / blur / Esc,
     pointer-events:none so it never blocks clicks, positioned beside the icon so it never covers the control. */
(() => {
  let HELP = {}, seq = 0, timer = null, active = null, shownAt = 0;
  const tip = () => document.getElementById("tooltip");
  const TITLE_TAGS = new Set(["BUTTON", "A", "LI", "SUMMARY"]);
  const CONTROL_TAGS = new Set(["INPUT", "SELECT", "TEXTAREA"]);

  function textFor(el) {
    if (el.dataset.helpText) return el.dataset.helpText;
    const t = HELP[el.dataset.help];
    if (!t) console.warn("missing help text for", el.dataset.help);
    return t || "";
  }

  function makeIcon(text) {
    const id = `help-${++seq}`;
    const icon = document.createElement("span");
    icon.className = "help-icon"; icon.tabIndex = 0; icon.textContent = "?";
    icon.setAttribute("role", "button"); icon.setAttribute("aria-label", "Help");
    icon.setAttribute("aria-describedby", id);
    const sr = document.createElement("span");
    sr.className = "sr-only"; sr.id = id; sr.textContent = text;
    icon.dataset.tip = text;
    return [icon, sr, id];
  }

  function apply(el) {
    if (el.dataset.helpDone) return;
    el.dataset.helpDone = "1";
    const text = textFor(el);
    if (!text) return;
    const label = CONTROL_TAGS.has(el.tagName) ? el.closest("label") : null;
    if (el.type === "file" || el.hidden && !label) { el.title = text; return; }
    if (TITLE_TAGS.has(el.tagName) || (CONTROL_TAGS.has(el.tagName) && !label)) {
      if (!el.title) el.title = text;
      return;
    }
    const host = label || el;
    if (host.querySelector(":scope > .help-icon")) return;
    const [icon, sr, id] = makeIcon(text);
    if (label) {
      el.setAttribute("aria-describedby", id);
      // block labels ("Text<input>"): icon right after the text; inline ("<input> Text"): at the end
      if (label.firstChild === el) label.append(icon, sr); else label.insertBefore(icon, el), label.insertBefore(sr, el);
    } else {
      host.append(icon, sr);
    }
  }

  function scan(root) {
    if (!(root instanceof Element)) return;
    if (root.matches("[data-help],[data-help-text]")) apply(root);
    root.querySelectorAll("[data-help],[data-help-text]").forEach(apply);
  }

  function place(icon) {
    const t = tip();
    t.textContent = icon.dataset.tip; t.hidden = false;
    // keep clear of the whole label (text + its control) so the field is never covered:
    // above the label if there is room, otherwise below it; horizontally next to the icon, clamped to the viewport
    const label = icon.closest("label");
    const avoid = (label || icon).getBoundingClientRect(), r = icon.getBoundingClientRect();
    const w = t.offsetWidth, h = t.offsetHeight, m = 6;
    const x = Math.min(Math.max(m, r.left - 12), innerWidth - w - m);
    let y = avoid.top - h - m;
    if (y < m) y = avoid.bottom + m;
    t.style.left = `${Math.round(x)}px`; t.style.top = `${Math.round(y)}px`;
    active = icon; shownAt = Date.now();
  }
  function hide() { clearTimeout(timer); timer = null; const t = tip(); if (t) t.hidden = true; active = null; }

  document.addEventListener("mouseover", (e) => {
    const icon = e.target.closest && e.target.closest(".help-icon");
    if (!icon || icon === active) return;
    clearTimeout(timer); timer = setTimeout(() => place(icon), 300);
  });
  document.addEventListener("mouseout", (e) => {
    const icon = e.target.closest && e.target.closest(".help-icon");
    if (icon && !icon.contains(e.relatedTarget)) { if (document.activeElement !== icon) hide(); else clearTimeout(timer); }
  });
  document.addEventListener("focusin", (e) => { if (e.target.classList && e.target.classList.contains("help-icon")) place(e.target); });
  document.addEventListener("focusout", (e) => { if (e.target === active) hide(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !tip().hidden) { hide(); } });
  // clicking "?" inside a <label> must not toggle/focus the field; tap toggles the tooltip on touch screens
  document.addEventListener("click", (e) => {
    const icon = e.target.closest && e.target.closest(".help-icon");
    if (!icon) return;
    e.preventDefault(); e.stopPropagation();
    if (active === icon && Date.now() - shownAt > 500) hide(); else place(icon);  // tap opens; a second tap closes
  }, true);
  addEventListener("scroll", hide, true);

  window.Help = {
    ready: fetch("/static/help.json?v=" + encodeURIComponent(window.APP_VERSION || "")).then((r) => {
      if (!r.ok) throw new Error(`help.json: HTTP ${r.status}`);
      return r.json();
    }).catch((e) => { console.warn("help text unavailable, continuing without it:", e); return {}; }).then((d) => {
      HELP = d; scan(document.body);
      new MutationObserver((ms) => ms.forEach((m) => {
        m.addedNodes.forEach(scan);
        // a help-carrying element whose content was replaced (status line, validation panel) lost its icon: re-add it
        const t = m.target;
        if (t.dataset && t.dataset.helpDone && !TITLE_TAGS.has(t.tagName) && !CONTROL_TAGS.has(t.tagName) &&
            !t.querySelector(":scope > .help-icon")) { delete t.dataset.helpDone; apply(t); }
      })).observe(document.body, {childList: true, subtree: true});
    }),
    setVisible(on) { document.body.classList.toggle("help-off", !on); if (!on) hide(); },
    text: (k) => HELP[k],
  };
})();

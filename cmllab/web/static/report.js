"use strict";
/* Printable reports: the Print button (no inline handlers: the Content-Security-Policy allows no inline script). */
document.querySelectorAll("[data-print]").forEach((b) => b.addEventListener("click", () => window.print()));

"use strict";
/* Runs first (in <head>, before the CSS paints): theme without a flash, and the app version for help.js.
   A file instead of an inline <script> because the Content-Security-Policy allows no inline script. */
window.APP_VERSION = document.documentElement.dataset.version || "";
try { document.documentElement.dataset.theme = localStorage.getItem("theme") || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch (e) { /* storage blocked */ }

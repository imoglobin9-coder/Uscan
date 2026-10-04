"use strict";
/* Light/dark switch. Loaded in <head> (a separate file because the CSP forbids inline scripts) so the saved
   choice is applied before first paint. Without a saved choice the system setting is followed. */
(function () {
  const root = document.documentElement, KEY = "uscan-theme";
  const saved = () => { try { return localStorage.getItem(KEY); } catch { return null; } };
  const set = t => { if (t === "light" || t === "dark") root.dataset.theme = t; else delete root.dataset.theme; };
  set(saved());
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-theme-toggle]"); if (!b) return;
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    set(next); try { localStorage.setItem(KEY, next); } catch { /* storage blocked: choice lasts for this visit */ }
    b.setAttribute("aria-pressed", String(next === "dark"));
  });
})();

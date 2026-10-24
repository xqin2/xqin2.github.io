/* Apply the preference before CSS is painted. The page works without JS. */
(function () {
  "use strict";
  var key = "xqin2-color-scheme";
  var root = document.documentElement;
  var media = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var preference = null;
  var button = null;
  function valid(value) { return value === "light" || value === "dark"; }
  try {
    var stored = window.localStorage.getItem(key);
    if (valid(stored)) preference = stored;
  } catch (_) { /* Storage can be blocked. In-memory switching still works. */ }
  function apply() {
    var theme = preference || (media && media.matches ? "dark" : "light");
    root.setAttribute("data-theme", theme);
    if (button) {
      button.setAttribute("aria-pressed", String(theme === "dark"));
      button.title = theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
    }
  }
  apply();
  function connect() {
    button = document.getElementById("theme-toggle");
    if (!button) return;
    button.hidden = false;
    apply();
    button.addEventListener("click", function () {
      preference = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try { window.localStorage.setItem(key, preference); } catch (_) { /* Optional persistence. */ }
      apply();
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", connect, { once: true });
  else connect();
  if (media) {
    if (media.addEventListener) media.addEventListener("change", function () { if (!preference) apply(); });
    else if (media.addListener) media.addListener(function () { if (!preference) apply(); });
  }
  window.addEventListener("storage", function (event) {
    if (event.key !== key && event.key !== null) return;
    preference = valid(event.newValue) ? event.newValue : null;
    apply();
  });
}());

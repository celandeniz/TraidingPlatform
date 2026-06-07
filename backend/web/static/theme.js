// Light/dark theme toggle (DynamicsOps theme layer). Persists to localStorage and
// injects a small toggle button into the page header. Default = dark (matches the
// per-page :root). No framework, no build — plain DOM.
(function () {
  var KEY = "tp-theme";
  var root = document.documentElement;

  function apply(mode) {
    if (mode === "light") root.classList.add("light");
    else root.classList.remove("light");
  }
  function current() {
    return root.classList.contains("light") ? "light" : "dark";
  }
  try { apply(localStorage.getItem(KEY) || "dark"); } catch (e) { /* ignore */ }

  function mount() {
    if (document.querySelector(".theme-toggle")) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "theme-toggle";
    btn.title = "Tema: açık / koyu";
    btn.setAttribute("aria-label", "Toggle light/dark theme");
    function paint() { btn.textContent = current() === "light" ? "🌙" : "☀️"; }
    paint();
    btn.addEventListener("click", function () {
      var next = current() === "light" ? "dark" : "light";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch (e) { /* ignore */ }
      paint();
    });
    var header = document.querySelector("header");
    if (header) header.appendChild(btn);
    else { btn.style.position = "fixed"; btn.style.top = "10px"; btn.style.right = "10px";
           btn.style.zIndex = "50"; document.body.appendChild(btn); }
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

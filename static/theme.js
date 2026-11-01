(function () {
  var mode = "auto";
  try {
    if (localStorage.getItem("trf-cookies") === "all") mode = localStorage.getItem("trf-theme") || "auto";
  } catch (e) {}
  if (mode !== "light" && mode !== "dark") mode = "auto";
  var dark = mode === "dark" || (mode === "auto" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.setAttribute("data-theme-mode", mode);
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();

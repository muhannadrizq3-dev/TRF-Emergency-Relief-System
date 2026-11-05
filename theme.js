(function () {
  var saved = null;
  try {
    if (localStorage.getItem("trf-cookies") === "all") saved = localStorage.getItem("trf-theme");
  } catch (e) {}
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
})();

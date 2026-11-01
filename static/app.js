(function () {
  "use strict";
  var root = document.documentElement;

  function store(key, value) {
    try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch (e) {}
  }
  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  var themeModes = ["auto", "light", "dark"];
  var systemDark = window.matchMedia("(prefers-color-scheme: dark)");

  function currentMode() {
    var mode = root.getAttribute("data-theme-mode");
    return themeModes.indexOf(mode) >= 0 ? mode : "auto";
  }

  function applyMode(mode) {
    var dark = mode === "dark" || (mode === "auto" && systemDark.matches);
    root.setAttribute("data-theme-mode", mode);
    root.setAttribute("data-theme", dark ? "dark" : "light");
    document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
      var label = btn.querySelector("[data-theme-label]");
      if (label) label.textContent = btn.getAttribute("data-" + mode);
      btn.setAttribute("title", btn.getAttribute("data-" + mode));
    });
    if (window.__trfMapRefresh) window.__trfMapRefresh();
  }

  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var next = themeModes[(themeModes.indexOf(currentMode()) + 1) % themeModes.length];
      applyMode(next);
      if (read("trf-cookies") === "all") store("trf-theme", next);
    });
  });
  var onSystemChange = function () { if (currentMode() === "auto") applyMode("auto"); };
  if (systemDark.addEventListener) systemDark.addEventListener("change", onSystemChange);
  applyMode(currentMode());

  var banner = document.getElementById("cookie-banner");
  if (banner) {
    if (!read("trf-cookies")) banner.hidden = false;
    banner.querySelectorAll("[data-cookie-choice]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var choice = btn.getAttribute("data-cookie-choice");
        store("trf-cookies", choice);
        if (choice === "all") store("trf-theme", currentMode());
        else store("trf-theme", null);
        banner.hidden = true;
      });
    });
  }
  document.querySelectorAll("[data-cookie-settings]").forEach(function (btn) {
    btn.addEventListener("click", function () { if (banner) { banner.hidden = false; banner.querySelector("button").focus(); } });
  });

  document.querySelectorAll("[data-reveal]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var input = document.getElementById(btn.getAttribute("data-reveal"));
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });

  var menuBtn = document.querySelector("[data-menu]");
  var nav = document.getElementById("mainnav");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () { nav.classList.remove("open"); menuBtn.setAttribute("aria-expanded", "false"); });
    });
  }

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (ev) {
      if (!window.confirm(form.getAttribute("data-confirm"))) ev.preventDefault();
    });
  });

  document.querySelectorAll("[data-fill]").forEach(function (el) {
    var pct = Math.max(0, Math.min(100, Number(el.getAttribute("data-fill")) || 0));
    var target = el.classList.contains("bar") ? el.querySelector("span") : el;
    if (!target) return;
    target.style.width = pct + "%";
    if (!el.classList.contains("bar")) target.style.maxWidth = "calc(100% - 3rem)";
  });

  var mapEl = document.getElementById("shelter-map");
  if (!mapEl || typeof L === "undefined") return;

  function cssVar(name, fallback) {
    return getComputedStyle(root).getPropertyValue(name).trim() || fallback;
  }
  function esc(s) {
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  var map = L.map(mapEl, { scrollWheelZoom: false }).setView([25.31, 55.40], 12);
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}", {
    maxZoom: 18, attribution: "Tiles &copy; Esri"
  }).addTo(map);
  map.on("focus", function () { map.scrollWheelZoom.enable(); });

  var markers = [];
  function draw(data) {
    markers.forEach(function (m) { map.removeLayer(m); });
    markers = [];
    var bounds = [];
    var noneText = mapEl.getAttribute("data-none");
    data.shelters.forEach(function (s) {
      var colour = s.waiting ? cssVar("--brand", "#c8102e") : cssVar("--good", "#1e7a45");
      var m = L.circleMarker([s.lat, s.lng], {
        radius: s.sos ? 13 : 10, color: "#ffffff", weight: 3, fillColor: colour, fillOpacity: 1
      }).addTo(map);
      var needs = s.needs.length
        ? "<ul>" + s.needs.map(function (n) { return "<li>" + esc(n) + "</li>"; }).join("") + "</ul>"
        : "<div>" + esc(noneText) + "</div>";
      m.bindPopup("<strong>" + esc(s.name) + "</strong>" + (s.sos ? " · SOS" : "") +
                  "<div>" + esc(s.area || "") + "</div>" + needs);
      markers.push(m);
      bounds.push([s.lat, s.lng]);
    });
    if (bounds.length) map.fitBounds(bounds, { padding: [45, 45], maxZoom: 14 });
  }

  var lastData = null;
  fetch(mapEl.getAttribute("data-src"), { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (data) { lastData = data; draw(data); })
    .catch(function () {});
  window.__trfMapRefresh = function () { if (lastData) draw(lastData); };

  if (mapEl.getAttribute("data-pick") === "yes") {
    var lat = document.getElementById("latitude");
    var lng = document.getElementById("longitude");
    var pin = null;
    map.on("click", function (e) {
      if (!lat || !lng) return;
      lat.value = e.latlng.lat.toFixed(6);
      lng.value = e.latlng.lng.toFixed(6);
      if (pin) pin.setLatLng(e.latlng);
      else pin = L.circleMarker(e.latlng, { radius: 9, color: cssVar("--brand-deep", "#8a0b1d"), weight: 3, fillOpacity: .2 }).addTo(map);
    });
  }
})();

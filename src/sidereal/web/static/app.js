"use strict";

const state = {
  charts: [],
  selectedChartId: null,
  selectedSavedChart: null,
  lastChartPayload: null,
  lastChartReport: null,
  toastTimer: null,
};

const ANGLE_IDS = new Set(["asc", "mc", "desc", "ic"]);
const DISPLAY_NAMES = {
  asc: "Ascendant",
  mc: "Midheaven",
  desc: "Descendant",
  ic: "Imum Coeli",
  north_node: "North Node",
  south_node: "South Node",
  midpoint_v1: "Midpoint 13",
  equal_house_12: "Equal 12 houses",
  t_square: "T-Square",
  grand_trine: "Grand Trine",
};

const TRANSIT_NOTE_FALLBACK =
  "Transit relationships are geometric correlations between a moving sky and a fixed natal chart. Interpretations are symbolic study notes, not predictions or scientific claims.";
const SYNASTRY_NOTE_FALLBACK =
  "Two-natal synastry compares two fixed chart moments. Interpretations are symbolic relationship study notes, not compatibility scores, destiny claims, or predictions.";
const CHART_NOTE_FALLBACK =
  "Positions, houses, and angular relationships are astronomical geometry. Interpretations are symbolic cultural study notes, not scientific claims about personality, fate, health, or outcomes.";

// Offline city → IANA helpers (no network). Names are search aliases only.
const KNOWN_PLACES = [
  { label: "Tokyo, Japan", aliases: ["tokyo", "tokyo japan", "japan tokyo"], tz: "Asia/Tokyo", lat: 35.6762, lon: 139.6503 },
  { label: "Osaka, Japan", aliases: ["osaka", "osaka japan"], tz: "Asia/Tokyo", lat: 34.6937, lon: 135.5023 },
  { label: "Seoul, South Korea", aliases: ["seoul", "seoul korea", "south korea"], tz: "Asia/Seoul", lat: 37.5665, lon: 126.978 },
  { label: "Beijing, China", aliases: ["beijing", "peking", "beijing china"], tz: "Asia/Shanghai", lat: 39.9042, lon: 116.4074 },
  { label: "Shanghai, China", aliases: ["shanghai", "shanghai china"], tz: "Asia/Shanghai", lat: 31.2304, lon: 121.4737 },
  { label: "Hong Kong", aliases: ["hong kong", "hongkong"], tz: "Asia/Hong_Kong", lat: 22.3193, lon: 114.1694 },
  { label: "Taipei, Taiwan", aliases: ["taipei", "taiwan"], tz: "Asia/Taipei", lat: 25.033, lon: 121.5654 },
  { label: "Singapore", aliases: ["singapore"], tz: "Asia/Singapore", lat: 1.3521, lon: 103.8198 },
  { label: "Bangkok, Thailand", aliases: ["bangkok", "thailand"], tz: "Asia/Bangkok", lat: 13.7563, lon: 100.5018 },
  { label: "Jakarta, Indonesia", aliases: ["jakarta", "indonesia"], tz: "Asia/Jakarta", lat: -6.2088, lon: 106.8456 },
  { label: "Manila, Philippines", aliases: ["manila", "philippines"], tz: "Asia/Manila", lat: 14.5995, lon: 120.9842 },
  { label: "New Delhi, India", aliases: ["delhi", "new delhi", "india delhi"], tz: "Asia/Kolkata", lat: 28.6139, lon: 77.209 },
  { label: "Mumbai, India", aliases: ["mumbai", "bombay"], tz: "Asia/Kolkata", lat: 19.076, lon: 72.8777 },
  { label: "Dubai, UAE", aliases: ["dubai", "uae"], tz: "Asia/Dubai", lat: 25.2048, lon: 55.2708 },
  { label: "Tel Aviv, Israel", aliases: ["tel aviv", "israel"], tz: "Asia/Jerusalem", lat: 32.0853, lon: 34.7818 },
  { label: "Istanbul, Turkey", aliases: ["istanbul", "turkey", "constantinople"], tz: "Europe/Istanbul", lat: 41.0082, lon: 28.9784 },
  { label: "Moscow, Russia", aliases: ["moscow", "moskva"], tz: "Europe/Moscow", lat: 55.7558, lon: 37.6173 },
  { label: "Cairo, Egypt", aliases: ["cairo", "egypt"], tz: "Africa/Cairo", lat: 30.0444, lon: 31.2357 },
  { label: "Johannesburg, South Africa", aliases: ["johannesburg", "joburg", "south africa"], tz: "Africa/Johannesburg", lat: -26.2041, lon: 28.0473 },
  { label: "Lagos, Nigeria", aliases: ["lagos", "nigeria"], tz: "Africa/Lagos", lat: 6.5244, lon: 3.3792 },
  { label: "Nairobi, Kenya", aliases: ["nairobi", "kenya"], tz: "Africa/Nairobi", lat: -1.2921, lon: 36.8219 },
  { label: "London, United Kingdom", aliases: ["london", "london uk", "england", "britain", "uk"], tz: "Europe/London", lat: 51.5074, lon: -0.1278 },
  { label: "Paris, France", aliases: ["paris", "france"], tz: "Europe/Paris", lat: 48.8566, lon: 2.3522 },
  { label: "Berlin, Germany", aliases: ["berlin", "germany"], tz: "Europe/Berlin", lat: 52.52, lon: 13.405 },
  { label: "Amsterdam, Netherlands", aliases: ["amsterdam", "netherlands", "holland"], tz: "Europe/Amsterdam", lat: 52.3676, lon: 4.9041 },
  { label: "Rome, Italy", aliases: ["rome", "italy", "roma"], tz: "Europe/Rome", lat: 41.9028, lon: 12.4964 },
  { label: "Madrid, Spain", aliases: ["madrid", "spain"], tz: "Europe/Madrid", lat: 40.4168, lon: -3.7038 },
  { label: "Lisbon, Portugal", aliases: ["lisbon", "portugal"], tz: "Europe/Lisbon", lat: 38.7223, lon: -9.1393 },
  { label: "Athens, Greece", aliases: ["athens", "greece"], tz: "Europe/Athens", lat: 37.9838, lon: 23.7275 },
  { label: "Stockholm, Sweden", aliases: ["stockholm", "sweden"], tz: "Europe/Stockholm", lat: 59.3293, lon: 18.0686 },
  { label: "Warsaw, Poland", aliases: ["warsaw", "poland"], tz: "Europe/Warsaw", lat: 52.2297, lon: 21.0122 },
  { label: "Zurich, Switzerland", aliases: ["zurich", "zürich", "switzerland"], tz: "Europe/Zurich", lat: 47.3769, lon: 8.5417 },
  { label: "Vienna, Austria", aliases: ["vienna", "wien", "austria"], tz: "Europe/Vienna", lat: 48.2082, lon: 16.3738 },
  { label: "New York, USA", aliases: ["new york", "nyc", "new york city", "brooklyn"], tz: "America/New_York", lat: 40.7128, lon: -74.006 },
  { label: "Boston, USA", aliases: ["boston"], tz: "America/New_York", lat: 42.3601, lon: -71.0589 },
  { label: "Washington, DC, USA", aliases: ["washington", "washington dc", "dc"], tz: "America/New_York", lat: 38.9072, lon: -77.0369 },
  { label: "Miami, USA", aliases: ["miami"], tz: "America/New_York", lat: 25.7617, lon: -80.1918 },
  { label: "Chicago, USA", aliases: ["chicago"], tz: "America/Chicago", lat: 41.8781, lon: -87.6298 },
  { label: "Houston, USA", aliases: ["houston"], tz: "America/Chicago", lat: 29.7604, lon: -95.3698 },
  { label: "Denver, USA", aliases: ["denver"], tz: "America/Denver", lat: 39.7392, lon: -104.9903 },
  { label: "Phoenix, USA", aliases: ["phoenix"], tz: "America/Phoenix", lat: 33.4484, lon: -112.074 },
  { label: "Los Angeles, USA", aliases: ["los angeles", "la", "l.a.", "hollywood"], tz: "America/Los_Angeles", lat: 34.0522, lon: -118.2437 },
  { label: "San Francisco, USA", aliases: ["san francisco", "sf", "bay area"], tz: "America/Los_Angeles", lat: 37.7749, lon: -122.4194 },
  { label: "Seattle, USA", aliases: ["seattle"], tz: "America/Los_Angeles", lat: 47.6062, lon: -122.3321 },
  { label: "Anchorage, USA", aliases: ["anchorage", "alaska"], tz: "America/Anchorage", lat: 61.2181, lon: -149.9003 },
  { label: "Honolulu, USA", aliases: ["honolulu", "hawaii"], tz: "Pacific/Honolulu", lat: 21.3069, lon: -157.8583 },
  { label: "Toronto, Canada", aliases: ["toronto", "canada"], tz: "America/Toronto", lat: 43.6532, lon: -79.3832 },
  { label: "Vancouver, Canada", aliases: ["vancouver"], tz: "America/Vancouver", lat: 49.2827, lon: -123.1207 },
  { label: "Mexico City, Mexico", aliases: ["mexico city", "mexico", "cdmx"], tz: "America/Mexico_City", lat: 19.4326, lon: -99.1332 },
  { label: "São Paulo, Brazil", aliases: ["sao paulo", "são paulo", "brazil"], tz: "America/Sao_Paulo", lat: -23.5505, lon: -46.6333 },
  { label: "Buenos Aires, Argentina", aliases: ["buenos aires", "argentina"], tz: "America/Argentina/Buenos_Aires", lat: -34.6037, lon: -58.3816 },
  { label: "Santiago, Chile", aliases: ["santiago", "chile"], tz: "America/Santiago", lat: -33.4489, lon: -70.6693 },
  { label: "Lima, Peru", aliases: ["lima", "peru"], tz: "America/Lima", lat: -12.0464, lon: -77.0428 },
  { label: "Bogotá, Colombia", aliases: ["bogota", "bogotá", "colombia"], tz: "America/Bogota", lat: 4.711, lon: -74.0721 },
  { label: "Sydney, Australia", aliases: ["sydney", "australia"], tz: "Australia/Sydney", lat: -33.8688, lon: 151.2093 },
  { label: "Melbourne, Australia", aliases: ["melbourne"], tz: "Australia/Melbourne", lat: -37.8136, lon: 144.9631 },
  { label: "Auckland, New Zealand", aliases: ["auckland", "new zealand", "nz"], tz: "Pacific/Auckland", lat: -36.8509, lon: 174.7645 },
  { label: "UTC", aliases: ["utc", "gmt", "zulu"], tz: "UTC", lat: null, lon: null },
];

const IANA_TIMEZONES = (() => {
  try {
    if (typeof Intl !== "undefined" && typeof Intl.supportedValuesOf === "function") {
      return Intl.supportedValuesOf("timeZone");
    }
  } catch (_error) {
    /* fall through */
  }
  return Array.from(new Set(["UTC", ...KNOWN_PLACES.map((place) => place.tz)])).sort();
})();

document.addEventListener("DOMContentLoaded", init);

function init() {
  setFormDefaults();
  initTimezonePickers();
  bindNavigation();
  bindForms();
  activateView(viewFromHash(), { updateHash: false });
  window.addEventListener("hashchange", () => {
    activateView(viewFromHash(), { updateHash: false });
  });
  void checkHealth();
  void loadLibrary();
}

function bindNavigation() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => {
      activateView(button.dataset.view || "chart");
    });
  });
}

function bindForms() {
  byId("chart-form").addEventListener("submit", handleChartSubmit);
  byId("save-chart-button").addEventListener("click", handleSaveChart);
  byId("refresh-library-button").addEventListener("click", () => {
    void loadLibrary({ announce: true });
  });
  byId("reinterpret-button").addEventListener("click", handleReinterpret);
  byId("library-transit-button").addEventListener("click", openSelectedTransit);
  byId("transit-form").addEventListener("submit", handleTransitSubmit);
  byId("synastry-form").addEventListener("submit", handleSynastrySubmit);
}

function setFormDefaults() {
  const now = new Date();
  const localDate = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");
  const localTime = `${String(now.getHours()).padStart(2, "0")}:${String(
    now.getMinutes(),
  ).padStart(2, "0")}`;
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  byId("chart-date").value = localDate;
  byId("transit-date").value = localDate;
  byId("transit-time").value = localTime;
  // Hidden tz fields + picker displays are filled by initTimezonePickers / setTimezoneValue.
  state.defaultTimezone = timezone;
}

async function checkHealth() {
  const health = byId("health-status");
  const copy = health.querySelector(".health-copy");
  try {
    const payload = await api("/api/health");
    const backend =
      payload.ephemeris_backend || payload.backend || payload.ephemeris?.backend;
    const version = payload.version || payload.sidereal_version;
    const detail = [version ? `v${version}` : null, backend || null]
      .filter(Boolean)
      .join(" · ");
    copy.textContent = detail ? `Local engine ready · ${detail}` : "Local engine ready";
    health.classList.add("is-ready");
    health.classList.remove("is-error");
  } catch (error) {
    copy.textContent = "Local engine unavailable";
    health.classList.add("is-error");
    health.classList.remove("is-ready");
    health.title = errorMessage(error);
  }
}

async function handleChartSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const root = byId("chart-report");
  const empty = byId("chart-empty");
  clearStatus("chart-form-status");

  try {
    if (!form.reportValidity()) return;
    const payload = chartPayloadFromForm(form);
    state.lastChartPayload = payload;
    state.lastChartReport = null;
    byId("save-chart-button").disabled = true;
    setBusy(submit, true, "Calculating…");
    showLoading(root, empty, "Calculating chart", "The local Python engine is resolving geometry and interpretation records.");
    const report = await api("/api/chart", { method: "POST", body: payload });
    state.lastChartReport = report;
    renderChartReport(report, root);
    const hasLabel = Boolean(payload.moment.label.trim());
    byId("save-chart-button").disabled = !hasLabel;
    setStatus(
      "chart-form-status",
      hasLabel
        ? "Chart calculated. You can save this geometry to the local library."
        : "Chart calculated. Add a label and calculate again to enable saving.",
      "success",
    );
  } catch (error) {
    showError(root, empty, "Chart could not be calculated", errorMessage(error));
    setStatus("chart-form-status", errorMessage(error), "error");
  } finally {
    setBusy(submit, false);
  }
}

async function handleSaveChart() {
  const button = byId("save-chart-button");
  if (!state.lastChartPayload || !state.lastChartReport) return;
  if (!state.lastChartPayload.moment.label.trim()) {
    showToast("A chart label is required before saving.", true);
    return;
  }

  try {
    setBusy(button, true, "Saving…");
    const saved = await api("/api/charts", {
      method: "POST",
      body: state.lastChartPayload,
    });
    state.selectedChartId = saved.id || null;
    await loadLibrary();
    showToast(`Saved “${saved.label || state.lastChartPayload.moment.label}” locally.`);
    setStatus("chart-form-status", "Saved to the local chart library.", "success");
  } catch (error) {
    setStatus("chart-form-status", errorMessage(error), "error");
    showToast(errorMessage(error), true);
  } finally {
    setBusy(button, false);
  }
}

async function loadLibrary({ announce = false } = {}) {
  const list = byId("library-list");
  list.replaceChildren(makeInlineLoader("Loading saved charts…"));
  byId("library-summary").textContent = "Loading…";
  const refresh = byId("refresh-library-button");
  setBusy(refresh, true, "Refreshing…");

  try {
    const payload = await api("/api/charts");
    state.charts = Array.isArray(payload) ? payload : asArray(payload.charts);
    if (
      state.selectedChartId &&
      !state.charts.some((chart) => chart.id === state.selectedChartId)
    ) {
      state.selectedChartId = null;
      state.selectedSavedChart = null;
    }
    renderLibraryList();
    renderNatalOptions();
    if (announce) showToast("Local chart library refreshed.");
  } catch (error) {
    state.charts = [];
    list.replaceChildren(makeInlineError(errorMessage(error)));
    byId("library-summary").textContent = "Unavailable";
    renderNatalOptions();
    if (announce) showToast(errorMessage(error), true);
  } finally {
    setBusy(refresh, false);
  }
}

function renderLibraryList() {
  const list = byId("library-list");
  list.replaceChildren();
  const count = state.charts.length;
  byId("library-summary").textContent = `${count} ${count === 1 ? "chart" : "charts"}`;
  const tabCount = byId("library-count");
  tabCount.textContent = String(count);
  tabCount.hidden = count === 0;

  if (!count) {
    const empty = element("p", "library-empty-list", "No saved charts yet. Calculate a labeled chart and choose “Save to library.”");
    list.append(empty);
    return;
  }

  for (const chart of state.charts) {
    const button = element("button", "library-item");
    button.type = "button";
    button.dataset.chartId = stringValue(chart.id);
    if (chart.id === state.selectedChartId) button.classList.add("is-selected");
    const title = element("span", "library-item-title", chart.label || "Untitled");
    const meta = element(
      "span",
      "library-item-meta",
      [friendlyMoment(chart.local_datetime), chart.tz, asArray(chart.systems).map(displayName).join(" + ")]
        .filter(Boolean)
        .join(" · "),
    );
    button.append(title, meta);
    button.addEventListener("click", () => {
      void selectSavedChart(chart.id);
    });
    list.append(button);
  }
}

function renderNatalOptions() {
  const select = byId("transit-natal");
  const current = state.selectedChartId || select.value;
  select.replaceChildren();
  const prompt = element("option", "", state.charts.length ? "Choose a saved chart…" : "No saved charts available");
  prompt.value = "";
  select.append(prompt);
  for (const chart of state.charts) {
    const option = element("option", "", `${chart.label || "Untitled"} · ${friendlyMoment(chart.local_datetime)}`);
    option.value = stringValue(chart.id);
    select.append(option);
  }
  if (state.charts.some((chart) => chart.id === current)) select.value = current;
  renderSynastryOptions();
}

function renderSynastryOptions() {
  const selectA = byId("synastry-a");
  const selectB = byId("synastry-b");
  const currentA = selectA.value || state.selectedChartId || "";
  const currentB = selectB.value || "";
  for (const [select, promptText] of [
    [selectA, "Choose chart A…"],
    [selectB, "Choose chart B…"],
  ]) {
    select.replaceChildren();
    const prompt = element(
      "option",
      "",
      state.charts.length ? promptText : "No saved charts available",
    );
    prompt.value = "";
    select.append(prompt);
    for (const chart of state.charts) {
      const option = element(
        "option",
        "",
        `${chart.label || "Untitled"} · ${friendlyMoment(chart.local_datetime)}`,
      );
      option.value = stringValue(chart.id);
      select.append(option);
    }
  }
  if (state.charts.some((chart) => chart.id === currentA)) selectA.value = currentA;
  if (state.charts.some((chart) => chart.id === currentB)) {
    selectB.value = currentB;
  } else {
    const alternate = state.charts.find((chart) => chart.id !== selectA.value);
    if (alternate) selectB.value = alternate.id;
  }
}

async function selectSavedChart(chartId) {
  state.selectedChartId = chartId;
  state.selectedSavedChart = null;
  renderLibraryList();
  renderNatalOptions();

  byId("library-empty").hidden = true;
  const selection = byId("library-selection");
  selection.hidden = false;
  const reportRoot = byId("library-report");
  const summary = state.charts.find((chart) => chart.id === chartId);
  byId("selected-chart-title").textContent = summary?.label || "Saved chart";
  clearStatus("library-status");
  reportRoot.replaceChildren(makeInlineLoader("Opening saved geometry…"));

  try {
    const saved = await api(`/api/charts/${encodeURIComponent(chartId)}`);
    state.selectedSavedChart = saved;
    byId("selected-chart-title").textContent = saved.label || summary?.label || "Saved chart";
    renderSavedGeometry(saved, reportRoot);
  } catch (error) {
    reportRoot.replaceChildren(makeInlineError(errorMessage(error)));
    setStatus("library-status", errorMessage(error), "error");
  }
}

async function handleReinterpret() {
  if (!state.selectedChartId) return;
  const button = byId("reinterpret-button");
  const root = byId("library-report");
  clearStatus("library-status");
  try {
    setBusy(button, true, "Interpreting…");
    root.replaceChildren(makeInlineLoader("Joining current interpretation records…"));
    const report = await api(
      `/api/charts/${encodeURIComponent(state.selectedChartId)}/interpret`,
      { method: "POST" },
    );
    renderChartReport(report, root, { saved: true });
    setStatus("library-status", "Re-interpreted against the current local database.", "success");
  } catch (error) {
    root.replaceChildren(makeInlineError(errorMessage(error)));
    setStatus("library-status", errorMessage(error), "error");
  } finally {
    setBusy(button, false);
  }
}

function openSelectedTransit() {
  if (!state.selectedChartId) return;
  byId("transit-natal").value = state.selectedChartId;
  activateView("transit");
  byId("transit-date").focus();
}

async function handleTransitSubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const root = byId("transit-report");
  const empty = byId("transit-empty");
  clearStatus("transit-form-status");

  try {
    if (!form.reportValidity()) return;
    const payload = transitPayloadFromForm(form);
    setBusy(submit, true, "Calculating…");
    showLoading(root, empty, "Calculating transits", "The local engine is comparing the moving sky with fixed natal geometry.");
    const report = await api("/api/transit", { method: "POST", body: payload });
    renderTransitReport(report, root);
    setStatus("transit-form-status", "Transit study calculated locally.", "success");
  } catch (error) {
    showError(root, empty, "Transit study could not be calculated", errorMessage(error));
    setStatus("transit-form-status", errorMessage(error), "error");
  } finally {
    setBusy(submit, false);
  }
}

async function handleSynastrySubmit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const root = byId("synastry-report");
  const empty = byId("synastry-empty");
  clearStatus("synastry-form-status");

  try {
    if (!form.reportValidity()) return;
    const payload = synastryPayloadFromForm(form);
    setBusy(submit, true, "Comparing…");
    showLoading(
      root,
      empty,
      "Comparing two fixed charts",
      "The local engine is matching both chart moments in their common J2000 frame.",
    );
    const report = await api("/api/synastry", { method: "POST", body: payload });
    renderSynastryReport(report, root);
    setStatus("synastry-form-status", "Two-natal study calculated locally.", "success");
  } catch (error) {
    showError(root, empty, "Synastry study could not be calculated", errorMessage(error));
    setStatus("synastry-form-status", errorMessage(error), "error");
  } finally {
    setBusy(submit, false);
  }
}

function chartPayloadFromForm(form) {
  const moment = momentFromForm(form, { timeRequired: false });
  return {
    moment,
    options: {
      compare_tropical: Boolean(form.elements.namedItem("compare_tropical").checked),
      include_houses: Boolean(form.elements.namedItem("include_houses").checked),
    },
  };
}

function transitPayloadFromForm(form) {
  const natalId = fieldValue(form, "natal_id").trim();
  if (!natalId) throw new Error("Choose a saved natal chart.");
  return {
    natal_id: natalId,
    transit: momentFromForm(form, { timeRequired: true }),
    options: {},
  };
}

function synastryPayloadFromForm(form) {
  const aId = fieldValue(form, "a_id").trim();
  const bId = fieldValue(form, "b_id").trim();
  if (!aId || !bId) throw new Error("Choose both saved charts.");
  return { a_id: aId, b_id: bId, options: {} };
}

function momentFromForm(form, { timeRequired }) {
  const date = fieldValue(form, "date");
  const time = fieldValue(form, "time") || null;
  const tz = fieldValue(form, "tz").trim();
  const foldRaw = fieldValue(form, "fold");
  const label = fieldValue(form, "label").trim();
  const { lat, lon } = coordinatePair(form);

  if (!date) throw new Error("A date is required.");
  if (timeRequired && !time) throw new Error("A transit time is required.");
  if (!tz) throw new Error("An IANA timezone is required.");
  if (!time && foldRaw) throw new Error("A repeated-time choice requires a civil time.");

  return {
    date,
    time,
    tz,
    lat,
    lon,
    label,
    fold: foldRaw === "" ? null : Number(foldRaw),
  };
}

function coordinatePair(form) {
  const latRaw = fieldValue(form, "lat").trim();
  const lonRaw = fieldValue(form, "lon").trim();
  if (Boolean(latRaw) !== Boolean(lonRaw)) {
    throw new Error("Latitude and longitude must be supplied together.");
  }
  if (!latRaw) return { lat: null, lon: null };
  const lat = Number(latRaw);
  const lon = Number(lonRaw);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    throw new Error("Latitude and longitude must be finite numbers.");
  }
  if (!(lat > -90 && lat < 90)) {
    throw new Error("Latitude must be strictly between -90 and 90 degrees.");
  }
  if (!(lon >= -180 && lon <= 180)) {
    throw new Error("Longitude must be between -180 and 180 degrees.");
  }
  return { lat, lon };
}

function renderChartReport(report, root, { saved = false } = {}) {
  const chart = asObject(report.chart);
  const meta = asObject(chart.meta);
  const input = asObject(meta.input);
  const interpretation = asObject(report.interpretation);
  const rawPoints = asArray(chart.points);
  const interpretedPlanets = asArray(interpretation.planets);
  const interpretedAngles = asArray(interpretation.angles);
  const interpretedHouses = asArray(interpretation.houses);
  const planets = interpretedPlanets.length
    ? interpretedPlanets
    : rawPoints.filter((point) => !ANGLE_IDS.has(point.id) && point.kind !== "angle").map((point) => ({ point, readings: [] }));
  const angles = interpretedAngles.length
    ? interpretedAngles
    : rawPoints.filter((point) => ANGLE_IDS.has(point.id) || point.kind === "angle").map((point) => ({ point, readings: [] }));
  const houses = interpretedHouses.length
    ? interpretedHouses
    : asArray(chart.cusps).map((cusp) => ({ cusp, readings: [] }));
  const housesCalculated = asArray(chart.cusps).length > 0;

  root.replaceChildren();
  root.hidden = false;
  root.append(
    makeReportHeader({
      chip: saved ? "Saved chart · current interpretation" : "Natal chart study",
      title: input.label || "Untitled chart",
      subtitle: [friendlyMoment(meta.local_datetime || input.local_date), input.tz]
        .filter(Boolean)
        .join(" · "),
      meta: [
        ["Zodiac", displayName(meta.zodiac_system)],
        ["Houses", housesCalculated ? displayName(meta.house_system) : "Not calculated"],
        ["Aspect profile", displayName(meta.aspect_profile)],
        ["Ephemeris", meta.ephemeris_backend || "Unknown"],
        ["Julian day UT", numberText(meta.jd_ut, 6)],
        ["Boundary version", meta.boundary_version || "Unknown"],
      ],
    }),
  );
  root.append(makeEpistemic(report.epistemic_note || CHART_NOTE_FALLBACK));

  if (report.wheel) {
    root.append(makeWheelSection(report.wheel, "13-sign Midpoint wheel"));
  }

  const warnings = [...asArray(meta.warnings)];
  if (meta.calculation_time_assumption) warnings.unshift(meta.calculation_time_assumption);
  if (warnings.length) root.append(makeWarningsSection(warnings, "Calculation notes"));

  root.append(makePointSection("Angles", angles, "No angles were calculated for this chart.", { showReadings: true }));
  root.append(makePointSection("Planets", planets, "No planetary positions are available."));
  root.append(
    makePlanetsInHousesSection(
      planets,
      housesCalculated,
      housesCalculated ? "" : houseOmissionReason(meta),
    ),
  );
  root.append(makeHouseSection(houses));
  root.append(makePlacementSection(planets, interpretedPlanets.length > 0));
  root.append(
    makeRelationshipsSection(
      asArray(interpretation.relationships).length
        ? asArray(interpretation.relationships)
        : asArray(chart.aspects).map((aspect) => ({ aspect, reading: null })),
      { geometryOnly: !asArray(interpretation.relationships).length },
    ),
  );

  const patterns = asArray(interpretation.patterns);
  if (patterns.length) root.append(makePatternsSection(patterns));
  if (report.comparison) root.append(makeComparisonSection(asObject(report.comparison)));
  root.append(makeGapsSection(asArray(report.gaps)));
}

function renderSavedGeometry(saved, root) {
  const chart = asObject(saved.chart);
  const report = {
    chart,
    wheel: saved.wheel || null,
    epistemic_note: CHART_NOTE_FALLBACK,
    interpretation: {},
    gaps: [],
  };
  renderChartReport(report, root, { saved: true });
  const headerChip = root.querySelector(".system-chip");
  if (headerChip) headerChip.textContent = "Saved frozen geometry";
  const placementSection = Array.from(root.querySelectorAll(".report-section")).find(
    (section) => section.dataset.section === "placements",
  );
  if (placementSection) {
    const note = placementSection.querySelector(".none-note");
    if (note) note.textContent = "Choose Re-interpret to join this geometry to the current local interpretation database.";
  }
}

function renderTransitReport(report, root) {
  const natal = asObject(report.natal);
  const transit = asObject(report.transit);
  const placements = asArray(report.placements);
  const relationships = asArray(report.relationships);
  root.replaceChildren();
  root.hidden = false;
  root.append(
    makeReportHeader({
      chip: "Sky ↔ Natal transit",
      title: `${natal.label || "Untitled natal"} · moving sky`,
      subtitle: `Moving sky at ${friendlyMoment(transit.local_datetime)} relative to natal ${natal.label || "chart"} · ${friendlyMoment(natal.local_datetime)}`,
      meta: [
        ["Natal timezone", natal.tz || "Unknown"],
        ["Transit timezone", transit.tz || "Unknown"],
        ["Zodiac", displayName(transit.zodiac_system)],
        [
          "Natal houses",
          natalHouseLabel(natal),
        ],
        ["Ephemeris", transit.ephemeris_backend || "Unknown"],
        ["Natal source", natal.source || "Inline"],
      ],
    }),
  );
  root.append(makeEpistemic(report.epistemic_note || TRANSIT_NOTE_FALLBACK));
  if (report.wheel) {
    root.append(makeWheelSection(report.wheel, "Natal wheel · moving-sky overlay"));
  }
  const warnings = asArray(report.warnings);
  if (warnings.length) root.append(makeWarningsSection(warnings, "Timing notes"));
  root.append(makeTransitPlacementsSection(placements));
  root.append(makeRoleRelationshipsSection(relationships, { mode: "transit" }));
  root.append(makeGapsSection(asArray(report.gaps)));
}

function renderSynastryReport(report, root) {
  const chartA = asObject(report.chart_a);
  const chartB = asObject(report.chart_b);
  const relationships = asArray(report.relationships);
  root.replaceChildren();
  root.hidden = false;
  root.append(
    makeReportHeader({
      chip: "Two fixed charts",
      title: `${chartA.label || "Chart A"} ↔ ${chartB.label || "Chart B"}`,
      subtitle: `A · ${friendlyMoment(chartA.local_datetime)} · B · ${friendlyMoment(chartB.local_datetime)}`,
      meta: [
        ["Chart A timezone", chartA.tz || "Unknown"],
        ["Chart B timezone", chartB.tz || "Unknown"],
        ["Zodiac", displayName(chartA.zodiac_system)],
        ["Frame", "Common J2000"],
        ["Chart A source", chartA.source || "Inline"],
        ["Chart B source", chartB.source || "Inline"],
      ],
    }),
  );
  root.append(makeEpistemic(report.epistemic_note || SYNASTRY_NOTE_FALLBACK));
  const warnings = asArray(report.warnings);
  if (warnings.length) root.append(makeWarningsSection(warnings, "Calculation notes"));
  root.append(makeRoleRelationshipsSection(relationships, { mode: "synastry" }));
  root.append(makeGapsSection(asArray(report.gaps)));
}

function makeReportHeader({ chip, title, subtitle, meta }) {
  const header = element("header", "report-head");
  header.append(element("span", "system-chip", chip));
  header.append(element("h2", "", title));
  if (subtitle) header.append(element("p", "report-subtitle", subtitle));
  const grid = element("dl", "meta-grid");
  for (const [label, value] of meta.filter((item) => item[1] !== undefined && item[1] !== null && item[1] !== "")) {
    const item = element("div", "meta-item");
    item.append(element("dt", "", label), element("dd", "", stringValue(value)));
    grid.append(item);
  }
  header.append(grid);
  return header;
}

function makeEpistemic(note) {
  const card = element("aside", "epistemic-card");
  card.append(element("span", "note-mark", "◇"));
  const copy = element("div");
  copy.append(element("h3", "", "Epistemic note"), element("p", "", note));
  card.append(copy);
  return card;
}

function makeWheelSection(wheelValue, title) {
  const { section, body } = makeSection(title, null, "wheel");
  const wheel = asObject(wheelValue);
  const svgText = stringValue(wheel.svg);
  if (wheel.media_type !== "image/svg+xml" || !svgText.startsWith("<svg")) {
    throw new Error("The local engine returned an invalid wheel image.");
  }
  const frame = element("figure", "wheel-frame");
  const image = element("img");
  image.alt = title;
  image.width = Number(wheel.width) || 640;
  image.loading = "eager";
  image.decoding = "async";
  image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgText)}`;
  frame.append(image, element("figcaption", "wheel-caption", title));
  body.append(frame);
  return section;
}

function makeWarningsSection(warnings, title) {
  const { section, body } = makeSection(title, warnings.length, "warnings");
  const list = element("ul", "warning-list");
  for (const warning of warnings) list.append(element("li", "", warning));
  body.append(list);
  return section;
}

function makePointSection(title, entries, emptyText, { showReadings = false } = {}) {
  const { section, body } = makeSection(title, entries.length, title.toLowerCase());
  if (!entries.length) {
    body.append(element("p", "none-note", emptyText));
    return section;
  }
  const grid = element("div", "point-grid");
  for (const entry of entries) {
    const point = asObject(entry.point || entry);
    const card = element("article", "point-card");
    const head = element("div", "point-card-head");
    head.append(
      element("span", "point-name", displayName(point.name || point.id)),
      element("span", "point-kind", point.kind === "angle" || ANGLE_IDS.has(point.id) ? "Angle" : "Body"),
    );
    card.append(head);
    card.append(
      element(
        "p",
        "placement-line",
        `${displayName(point.sign || "Unknown")} ${numberText(point.degree_in_sign, 4)}°`,
      ),
    );
    const details = element("div", "point-detail");
    if (point.house !== null && point.house !== undefined) details.append(detailChip(`House ${point.house}`));
    if (point.retro) details.append(detailChip("Retrograde"));
    if (point.blend && point.secondary_sign) {
      details.append(detailChip(`Within boundary orb · ${displayName(point.secondary_sign)}`, "blend"));
    }
    if (details.childElementCount) card.append(details);
    const readings = asArray(entry.readings);
    if (showReadings && readings.length) {
      const readingList = element("div", "reading-list point-readings");
      for (const reading of readings) readingList.append(makeReadingCard(asObject(reading)));
      card.append(readingList);
    }
    grid.append(card);
  }
  body.append(grid);
  return section;
}

function makePlanetsInHousesSection(entries, housesCalculated, omissionReason = "") {
  const housed = entries.filter(
    (entry) => asObject(entry.point).house !== null && asObject(entry.point).house !== undefined,
  );
  const { section, body } = makeSection("Planets in houses", housed.length || null, "planets-in-houses");
  body.append(
    element(
      "p",
      "section-note",
      housesCalculated
        ? "Each body is shown in its equal-house arena (1–12). House text is symbolic life-area language, not a prediction."
        : omissionReason || "Houses were not calculated for this chart.",
    ),
  );
  if (!housesCalculated || !housed.length) {
    body.append(
      element(
        "p",
        "none-note",
        housesCalculated
          ? "No planetary house assignments are available."
          : "House placements are unavailable for this chart.",
      ),
    );
    return section;
  }

  const table = element("table", "data-table");
  const head = element("thead");
  const headRow = element("tr");
  for (const label of ["Planet", "House", "Sign", "Degree", "Notes"]) headRow.append(element("th", "", label));
  head.append(headRow);
  const tbody = element("tbody");
  const sorted = [...housed].sort((left, right) => {
    const a = asObject(left.point);
    const b = asObject(right.point);
    const houseDelta = Number(a.house) - Number(b.house);
    if (houseDelta !== 0) return houseDelta;
    return String(a.id).localeCompare(String(b.id));
  });
  for (const entry of sorted) {
    const point = asObject(entry.point);
    const row = element("tr");
    const notes = [];
    if (point.retro) notes.push("Rx");
    if (point.blend && point.secondary_sign) notes.push(`blend ${displayName(point.secondary_sign)}`);
    row.append(
      element("td", "", displayName(point.name || point.id)),
      element("td", "house-number-cell", String(point.house)),
      element("td", "", displayName(point.sign || "Unknown")),
      element("td", "", `${numberText(point.degree_in_sign, 4)}°`),
      element("td", "", notes.join(" · ") || "—"),
    );
    tbody.append(row);
  }
  table.append(head, tbody);
  const scroll = element("div", "table-scroll");
  scroll.append(table);
  body.append(scroll);

  const byHouse = new Map();
  for (const entry of sorted) {
    const house = Number(asObject(entry.point).house);
    if (!byHouse.has(house)) byHouse.set(house, []);
    byHouse.get(house).push(entry);
  }
  const stack = element("div", "readings-stack house-occupancy-stack");
  for (const house of [...byHouse.keys()].sort((a, b) => a - b)) {
    const group = element("article", "house-occupancy-card");
    const occupants = byHouse.get(house);
    group.append(
      element(
        "h4",
        "",
        `House ${house} · ${occupants.map((entry) => displayName(asObject(entry.point).name || asObject(entry.point).id)).join(", ")}`,
      ),
    );
    for (const entry of occupants) {
      const point = asObject(entry.point);
      const block = element("div", "house-occupant-block");
      block.append(
        element(
          "p",
          "placement-line",
          `${displayName(point.name || point.id)} in House ${point.house} · ${displayName(point.sign)} ${numberText(point.degree_in_sign, 4)}°`,
        ),
      );
      const houseReadings = asArray(entry.readings).filter((reading) =>
        String(asObject(reading).id || "").startsWith("planet_in_house:"),
      );
      const readingList = element("div", "reading-list");
      if (houseReadings.length) {
        for (const reading of houseReadings) readingList.append(makeReadingCard(asObject(reading)));
      } else {
        readingList.append(
          element(
            "p",
            "none-note",
            "No planet-in-house interpretation record was joined for this placement.",
          ),
        );
      }
      block.append(readingList);
      group.append(block);
    }
    stack.append(group);
  }
  body.append(stack);
  return section;
}

function makeHouseSection(entries) {
  const { section, body } = makeSection("Sign on each house", entries.length, "houses");
  if (!entries.length) {
    body.append(element("p", "none-note", "Houses were not calculated; no cusp signs have been inferred."));
    return section;
  }
  const table = element("table", "data-table");
  const head = element("thead");
  const headRow = element("tr");
  for (const label of ["House", "Sign", "Degree", "Boundary note"]) headRow.append(element("th", "", label));
  head.append(headRow);
  const tbody = element("tbody");
  for (const entry of entries) {
    const cusp = asObject(entry.cusp || entry);
    const row = element("tr");
    row.append(
      element("td", "", stringValue(cusp.number || cusp.house || "—")),
      element("td", "", displayName(cusp.sign || "Unknown")),
      element("td", "", `${numberText(cusp.degree_in_sign, 4)}°`),
      element(
        "td",
        cusp.blend ? "labels-differ" : "",
        cusp.blend && cusp.secondary_sign
          ? `Within boundary orb with ${displayName(cusp.secondary_sign)}`
          : "—",
      ),
    );
    tbody.append(row);
  }
  table.append(head, tbody);
  const scroll = element("div", "table-scroll");
  scroll.append(table);
  body.append(scroll);
  const readingEntries = entries.filter((entry) => asArray(entry.readings).length);
  if (readingEntries.length) {
    const stack = element("div", "readings-stack house-reading-stack");
    for (const entry of readingEntries) {
      const cusp = asObject(entry.cusp || entry);
      const article = element("article", "placement-reading");
      article.append(
        element("h4", "", `House ${cusp.number || cusp.house} · ${displayName(cusp.sign)}`),
      );
      const readings = element("div", "reading-list");
      for (const reading of asArray(entry.readings)) {
        readings.append(makeReadingCard(asObject(reading)));
      }
      article.append(readings);
      stack.append(article);
    }
    body.append(stack);
  }
  return section;
}

function makePlacementSection(entries, hasInterpretation) {
  const { section, body } = makeSection("Placement readings", hasInterpretation ? entries.length : null, "placements");
  if (!hasInterpretation) {
    body.append(element("p", "none-note", "No composed placement readings are present in this geometry-only view."));
    return section;
  }
  if (!entries.length) {
    body.append(element("p", "none-note", "No placement readings are available."));
    return section;
  }
  const stack = element("div", "readings-stack");
  for (const entry of entries) {
    const point = asObject(entry.point);
    const article = element("article", "placement-reading");
    const heading = [
      displayName(point.name || point.id),
      displayName(point.sign),
      point.house !== null && point.house !== undefined ? `House ${point.house}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    article.append(element("h4", "", heading));
    if (point.blend && point.secondary_sign) {
      article.append(element("p", "section-note", `Within the configured boundary orb with ${displayName(point.secondary_sign)}.`));
    }
    const list = element("div", "reading-list");
    const readings = asArray(entry.readings);
    if (readings.length) {
      for (const reading of readings) list.append(makeReadingCard(asObject(reading)));
    } else {
      list.append(element("p", "none-note", "No interpretation records were joined."));
    }
    article.append(list);
    stack.append(article);
  }
  body.append(stack);
  return section;
}

function makeRoleRelationshipsSection(entries, { mode }) {
  const transit = mode === "transit";
  const title = transit ? "Sky–Natal aspects (transits)" : "Two-natal aspects";
  const { section, body } = makeSection(title, entries.length, `${mode}-relationships`);
  if (!entries.length) {
    body.append(element("p", "none-note", "No configured major cross-chart aspects were found."));
    return section;
  }
  body.append(
    element(
      "p",
      "section-note",
      transit
        ? "Moving-sky bodies are compared with fixed natal points. Same-body timing contacts are separated below."
        : "Chart A and Chart B remain distinct fixed roles. This is relationship symbolism, not a compatibility score.",
    ),
  );
  const groups = [
    [transit ? "Same-body sky–natal contacts" : "Same-body contacts", entries.filter((entry) => entry.same_body)],
    [transit ? "Other sky–natal contacts" : "Other cross-chart contacts", entries.filter((entry) => !entry.same_body)],
  ];
  for (const [groupTitle, groupEntries] of groups) {
    if (!groupEntries.length) continue;
    body.append(element("h4", "relationship-group-title", groupTitle));
    const list = element("div", "relationships-list");
    for (const entry of groupEntries) {
      const aspect = asObject(entry.aspect);
      const reading = entry.reading ? asObject(entry.reading) : null;
      const character = asObject(entry.character);
      const bodyA = transit ? aspect.transit_body : aspect.a_point;
      const bodyB = transit ? aspect.natal_point : aspect.b_point;
      const roleA = transit ? "Transit" : "A ·";
      const roleB = transit ? "natal" : "B ·";
      const fallbackTitle = `${roleA} ${displayName(bodyA)} ${displayName(aspect.aspect_id).toLowerCase()} ${roleB} ${displayName(bodyB)}`;
      const card = element("article", "relationship-card");
      const head = element("div", "relationship-head");
      head.append(element("h5", "relationship-title", character.title || fallbackTitle));
      if (Number.isFinite(Number(aspect.force))) {
        const meter = element("progress", "force-meter");
        meter.max = 1;
        meter.value = Math.max(0, Math.min(1, Number(aspect.force)));
        meter.title = `Force ${numberText(aspect.force, 3)}`;
        head.append(meter);
      }
      card.append(head);
      const geometryBits = [
        `separation ${numberText(aspect.separation, 4)}°`,
        `orb ${numberText(aspect.exactness, 4)}°`,
        transit ? motionState(aspect) : "two fixed chart moments",
      ];
      card.append(element("p", "relationship-meta", geometryBits.join(" · ")));
      if (character.synthesis) {
        card.append(element("p", "character-synthesis", character.synthesis));
      }
      if (reading) card.append(makeReadingCard(reading));

      const placementSides = transit
        ? [
            ["transit_placement", "Transit · sign character"],
            ["natal_placement", "Natal · sign character"],
          ]
        : [
            ["a_placement", "Chart A · sign character"],
            ["b_placement", "Chart B · sign character"],
          ];
      for (const [key, label] of placementSides) {
        const side = asObject(character[key]);
        const sideReading = side.reading ? asObject(side.reading) : null;
        if (!sideReading) continue;
        const block = element("div", "character-placement");
        const headingBits = [label];
        if (side.sign) headingBits.push(displayName(side.sign));
        if (side.house !== null && side.house !== undefined) {
          headingBits.push(`House ${side.house}`);
        }
        if (side.natal_house !== null && side.natal_house !== undefined) {
          headingBits.push(`Natal house ${side.natal_house}`);
        }
        block.append(element("h6", "", headingBits.join(" · ")));
        block.append(makeReadingCard(sideReading));
        card.append(block);
      }
      list.append(card);
    }
    body.append(list);
  }
  return section;
}

function makeRelationshipsSection(entries, { transit = false, geometryOnly = false } = {}) {
  const title = transit ? "Transit–natal relationships" : "Relationships";
  const { section, body } = makeSection(title, entries.length, "relationships");
  if (!entries.length) {
    body.append(element("p", "none-note", "No configured major aspects were found."));
    return section;
  }
  body.append(
    element(
      "p",
      "section-note",
      transit
        ? "Each hit includes planetary aspect lore plus Midpoint sign character for the moving body and the natal point."
        : "Each aspect includes planetary relationship lore plus Midpoint zodiac character for both bodies as placed in this chart.",
    ),
  );
  const list = element("div", "relationships-list");
  for (const entry of entries) {
    const aspect = asObject(entry.aspect || entry);
    const reading = entry.reading ? asObject(entry.reading) : null;
    const character = asObject(entry.character);
    const card = element("article", "relationship-card");
    const head = element("div", "relationship-head");
    const bodyA = transit ? aspect.transit_body : aspect.body_a;
    const bodyB = transit ? aspect.natal_point : aspect.body_b;
    const fallbackTitle = transit
      ? `Transit ${displayName(bodyA)} ${displayName(aspect.aspect_id).toLowerCase()} natal ${displayName(bodyB)}`
      : `${displayName(bodyA)} ${displayName(aspect.aspect_id).toLowerCase()} ${displayName(bodyB)}`;
    head.append(element("h4", "relationship-title", character.title || fallbackTitle));
    if (Number.isFinite(Number(aspect.force))) {
      const meter = element("progress", "force-meter");
      meter.max = 1;
      meter.value = Math.max(0, Math.min(1, Number(aspect.force)));
      meter.title = `Force ${numberText(aspect.force, 3)}`;
      head.append(meter);
    }
    card.append(head);
    card.append(
      element(
        "p",
        "relationship-meta",
        [
          `separation ${numberText(aspect.separation, 4)}°`,
          `orb ${numberText(aspect.exactness, 4)}°`,
          motionState(aspect),
        ].join(" · "),
      ),
    );
    if (character.synthesis) {
      card.append(element("p", "character-synthesis", character.synthesis));
    }
    if (reading) {
      card.append(makeReadingCard(reading));
    } else if (geometryOnly) {
      card.append(element("p", "none-note", "Geometry only. Re-interpret this chart to join current reading text."));
    }
    const placementSides = transit
      ? [
          ["transit_placement", "Transit · sign character"],
          ["natal_placement", "Natal · sign character"],
        ]
      : [
          ["body_a_placement", "First body · sign character"],
          ["body_b_placement", "Second body · sign character"],
        ];
    for (const [key, label] of placementSides) {
      const side = asObject(character[key]);
      const sideReading = side.reading ? asObject(side.reading) : null;
      if (!sideReading) continue;
      const block = element("div", "character-placement");
      const headingBits = [label];
      if (side.sign) headingBits.push(displayName(side.sign));
      if (side.house !== null && side.house !== undefined) headingBits.push(`House ${side.house}`);
      if (side.natal_house !== null && side.natal_house !== undefined) {
        headingBits.push(`Natal house ${side.natal_house}`);
      }
      block.append(element("h5", "", headingBits.join(" · ")));
      block.append(makeReadingCard(sideReading));
      card.append(block);
    }
    list.append(card);
  }
  body.append(list);
  return section;
}

function makePatternsSection(entries) {
  const { section, body } = makeSection("Patterns", entries.length, "patterns");
  const list = element("div", "relationships-list");
  for (const entry of entries) {
    const pattern = asObject(entry.pattern);
    const article = element("article", "relationship-card");
    article.append(element("h4", "relationship-title", displayName(pattern.pattern_id)));
    const members = asArray(pattern.members).map(displayName).join(", ");
    if (members) article.append(element("p", "relationship-meta", `Members · ${members}`));
    if (entry.reading) article.append(makeReadingCard(asObject(entry.reading)));
    list.append(article);
  }
  body.append(list);
  return section;
}

function makeComparisonSection(comparison) {
  const points = asArray(comparison.points);
  const cusps = asArray(comparison.cusps);
  const systems = asArray(comparison.systems);
  const { section, body } = makeSection("Zodiac comparison", points.length + cusps.length, "comparison");
  body.append(
    element(
      "p",
      "comparison-note",
      comparison.note || "These are neutral labels over the same underlying geometry; neither zodiac is declared true.",
    ),
  );
  const list = element("div", "comparison-list");
  for (const point of points) list.append(makeComparisonRow(displayName(point.id), point, systems));
  if (cusps.length) {
    list.append(element("h4", "", "House cusp labels"));
    for (const cusp of cusps) list.append(makeComparisonRow(`House ${cusp.number}`, cusp, systems));
  }
  body.append(list);
  return section;
}

function makeComparisonRow(label, record, systems) {
  const row = element("div", "comparison-row");
  const labelCell = element("div", "comparison-cell");
  labelCell.append(element("strong", "", label));
  if (record.labels_differ) labelCell.append(element("span", "labels-differ", "Labels differ"));
  row.append(labelCell);
  const placements = asObject(record.systems);
  for (const system of systems) {
    const placement = asObject(placements[system]);
    const cell = element("div", "comparison-cell");
    cell.append(
      element("strong", "", displayName(system)),
      element("span", "", `${displayName(placement.sign || "Unknown")} ${numberText(placement.degree_in_sign, 4)}°`),
    );
    row.append(cell);
  }
  return row;
}

function makeGapsSection(gaps) {
  const { section, body } = makeSection("Interpretation gaps", gaps.length, "gaps");
  if (!gaps.length) {
    body.append(element("p", "none-note", "None for this report."));
    return section;
  }
  body.append(element("p", "section-note", "Gaps are shown explicitly so unfinished or absent symbolic text is never presented as complete."));
  const list = element("div", "gap-list");
  for (const gap of gaps) {
    const item = element("article", "gap-item");
    const head = element("div", "gap-head");
    head.append(element("code", "gap-key", gap.key || "Unknown key"), makeStatusBadge(gap.kind || "missing"));
    item.append(head);
    const contexts = asArray(gap.contexts).join("; ");
    if (contexts) item.append(element("p", "gap-context", contexts));
    list.append(item);
  }
  body.append(list);
  return section;
}

function makeTransitPlacementsSection(placements) {
  const { section, body } = makeSection("Transit placements", placements.length, "transit-placements");
  if (!placements.length) {
    body.append(element("p", "none-note", "No transit placements are available."));
    return section;
  }
  body.append(
    element(
      "p",
      "section-note",
      "Moving bodies are labeled in Midpoint signs. When the natal has houses, each transit body is also shown in the natal house it occupies.",
    ),
  );

  const table = element("table", "data-table");
  const head = element("thead");
  const headRow = element("tr");
  for (const label of ["Transit body", "Sign", "Degree", "Natal house", "Notes"]) {
    headRow.append(element("th", "", label));
  }
  head.append(headRow);
  const tbody = element("tbody");
  const sorted = [...placements].sort((left, right) => {
    const houseLeft = left.natal_house == null ? 99 : Number(left.natal_house);
    const houseRight = right.natal_house == null ? 99 : Number(right.natal_house);
    if (houseLeft !== houseRight) return houseLeft - houseRight;
    return String(left.id).localeCompare(String(right.id));
  });
  for (const placement of sorted) {
    const row = element("tr");
    const notes = transitPlacementNotes(placement);
    row.append(
      element("td", "", displayName(placement.id)),
      element("td", "", displayName(placement.sign)),
      element("td", "", `${numberText(placement.degree_in_sign, 4)}°`),
      element(
        "td",
        "house-number-cell",
        placement.natal_house !== null && placement.natal_house !== undefined
          ? String(placement.natal_house)
          : "—",
      ),
      element("td", "", notes.join(" · ") || "—"),
    );
    tbody.append(row);
  }
  table.append(head, tbody);
  const scroll = element("div", "table-scroll");
  scroll.append(table);
  body.append(scroll);

  const withHouse = sorted.filter(
    (placement) => placement.natal_house !== null && placement.natal_house !== undefined,
  );
  if (withHouse.length) {
    const byHouse = new Map();
    for (const placement of withHouse) {
      const house = Number(placement.natal_house);
      if (!byHouse.has(house)) byHouse.set(house, []);
      byHouse.get(house).push(placement);
    }
    const stack = element("div", "readings-stack house-occupancy-stack");
    stack.append(element("h4", "", "By natal house"));
    for (const house of [...byHouse.keys()].sort((a, b) => a - b)) {
      const group = element("article", "house-occupancy-card");
      const occupants = byHouse.get(house);
      group.append(
        element(
          "h4",
          "",
          `Natal house ${house} · transit ${occupants.map((item) => displayName(item.id)).join(", ")}`,
        ),
      );
      const list = element("ul", "house-occupant-list");
      for (const placement of occupants) {
        const notes = transitPlacementNotes(placement);
        const noteSuffix = notes.length ? `; ${notes.join(" · ")}` : "";
        list.append(
          element(
            "li",
            "",
            `Transit ${displayName(placement.id)} in ${displayName(placement.sign)} ${numberText(placement.degree_in_sign, 4)}° (natal house ${placement.natal_house}${noteSuffix})`,
          ),
        );
      }
      group.append(list);
      stack.append(group);
    }
    body.append(stack);
  }
  return section;
}

function initTimezonePickers() {
  document.querySelectorAll("[data-timezone-picker]").forEach((root) => {
    const search = root.querySelector(".tz-search");
    const hidden = root.querySelector('input[type="hidden"][name="tz"]');
    const results = root.querySelector(".tz-results");
    const display = root.querySelector(".tz-current-value");
    if (!search || !hidden || !results || !display) return;

    const setValue = (tz, meta = {}) => {
      hidden.value = tz;
      display.textContent = tz || "—";
      if (meta.label) display.title = meta.label;
      else display.removeAttribute("title");
      search.dataset.resolvedTz = tz || "";
      if (meta.fillCoords) {
        maybeFillCoords(root, meta.lat, meta.lon);
      }
    };

    const closeResults = () => {
      results.hidden = true;
      search.setAttribute("aria-expanded", "false");
      search.removeAttribute("aria-activedescendant");
      search.dataset.activeIndex = "-1";
      for (const option of results.querySelectorAll("[data-tz]")) {
        option.classList.remove("is-active");
        option.setAttribute("aria-selected", "false");
      }
    };

    const selectOption = (option) => {
      if (!option) return;
      const tz = option.getAttribute("data-tz");
      const label = option.getAttribute("data-label") || tz;
      const lat = option.getAttribute("data-lat");
      const lon = option.getAttribute("data-lon");
      setValue(tz, {
        label,
        fillCoords: true,
        lat: lat === "" || lat == null ? null : Number(lat),
        lon: lon === "" || lon == null ? null : Number(lon),
      });
      search.value = label.includes("/") ? tz : `${label} · ${tz}`;
      closeResults();
      if (blurTimer) window.clearTimeout(blurTimer);
    };

    const moveActiveOption = (direction) => {
      if (results.hidden) renderTimezoneResults(root, search.value);
      const options = Array.from(results.querySelectorAll("[data-tz]"));
      if (!options.length) return;
      const current = Number(search.dataset.activeIndex || -1);
      const next = current < 0
        ? (direction > 0 ? 0 : options.length - 1)
        : (current + direction + options.length) % options.length;
      options.forEach((option, index) => {
        const active = index === next;
        option.classList.toggle("is-active", active);
        option.setAttribute("aria-selected", active ? "true" : "false");
      });
      const active = options[next];
      search.dataset.activeIndex = String(next);
      search.setAttribute("aria-activedescendant", active.id);
      active.scrollIntoView({ block: "nearest" });
    };

    const defaultTz = state.defaultTimezone || "UTC";
    setValue(defaultTz);
    search.value = defaultTz;
    search.placeholder = "Tokyo, Japan or Asia/Tokyo";

    let blurTimer = null;
    search.addEventListener("focus", () => {
      renderTimezoneResults(root, search.value);
    });
    search.addEventListener("input", () => {
      // Typing invalidates the prior explicit selection; never submit a stale zone.
      setValue("");
      renderTimezoneResults(root, search.value);
    });
    search.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        moveActiveOption(event.key === "ArrowDown" ? 1 : -1);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        closeResults();
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const activeId = search.getAttribute("aria-activedescendant");
        const active = activeId ? document.getElementById(activeId) : null;
        const option = active || results.querySelector("[data-tz]");
        if (option) {
          selectOption(option);
          return;
        }
        const resolved = resolveTimezoneInput(search.value);
        if (resolved) {
          setValue(resolved);
          search.value = resolved;
          closeResults();
        }
      }
    });
    search.addEventListener("blur", () => {
      // Resolve direct zone input before a following form submit can read the field.
      const typed = search.value.trim();
      const resolved = resolveTimezoneInput(typed);
      if (resolved) {
        setValue(resolved);
        search.value = resolved;
      }
      blurTimer = window.setTimeout(() => {
        closeResults();
      }, 150);
    });
    results.addEventListener("mousedown", (event) => {
      // Keep focus long enough for the click to register.
      event.preventDefault();
    });
    results.addEventListener("click", (event) => {
      const option = event.target.closest("[data-tz]");
      if (!option) return;
      selectOption(option);
    });

    const latInput = byId(root.getAttribute("data-lat-field"));
    const lonInput = byId(root.getAttribute("data-lon-field"));
    const clearCoordinateProvenance = () => {
      if (latInput) delete latInput.dataset.timezoneAutofill;
      if (lonInput) delete lonInput.dataset.timezoneAutofill;
    };
    if (latInput) latInput.addEventListener("input", clearCoordinateProvenance);
    if (lonInput) lonInput.addEventListener("input", clearCoordinateProvenance);
  });
}

function maybeFillCoords(pickerRoot, lat, lon) {
  if (lat == null || lon == null || Number.isNaN(lat) || Number.isNaN(lon)) return;
  const latId = pickerRoot.getAttribute("data-lat-field");
  const lonId = pickerRoot.getAttribute("data-lon-field");
  if (!latId || !lonId) return;
  const latInput = byId(latId);
  const lonInput = byId(lonId);
  if (!latInput || !lonInput) return;
  const latValue = String(latInput.value || "").trim();
  const lonValue = String(lonInput.value || "").trim();
  const bothEmpty = !latValue && !lonValue;
  const stillAutofilled =
    Object.hasOwn(latInput.dataset, "timezoneAutofill")
    && Object.hasOwn(lonInput.dataset, "timezoneAutofill")
    && latValue === latInput.dataset.timezoneAutofill
    && lonValue === lonInput.dataset.timezoneAutofill;
  if (!bothEmpty && !stillAutofilled) return;
  latInput.value = String(lat);
  lonInput.value = String(lon);
  latInput.dataset.timezoneAutofill = String(lat);
  lonInput.dataset.timezoneAutofill = String(lon);
}

function resolveTimezoneInput(value) {
  const candidate = String(value || "").trim();
  if (!candidate) return null;
  if (["UTC", "GMT", "Z"].includes(candidate.toUpperCase())) return "UTC";
  try {
    const resolved = new Intl.DateTimeFormat("en-US", { timeZone: candidate })
      .resolvedOptions().timeZone;
    return ["Etc/UTC", "Etc/GMT", "GMT"].includes(resolved) ? "UTC" : resolved;
  } catch (_error) {
    return null;
  }
}

function normalizeSearchText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[_/,-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function searchTimezoneMatches(query, limit = 80) {
  const q = normalizeSearchText(query);
  const matches = [];
  const seen = new Set();

  const push = (item) => {
    const key = `${item.tz}::${item.label}`;
    if (seen.has(key)) return;
    seen.add(key);
    matches.push(item);
  };

  if (!q) {
    for (const place of KNOWN_PLACES.slice(0, 24)) {
      push({
        kind: "place",
        label: place.label,
        tz: place.tz,
        lat: place.lat,
        lon: place.lon,
        rank: 0,
      });
    }
    for (const tz of IANA_TIMEZONES.slice(0, limit)) {
      push({ kind: "zone", label: tz, tz, lat: null, lon: null, rank: 1 });
    }
    return matches.slice(0, limit);
  }

  for (const place of KNOWN_PLACES) {
    const haystacks = [place.label, place.tz, ...place.aliases].map(normalizeSearchText);
    const hit = haystacks.some((text) => text.includes(q));
    if (!hit) continue;
    const exact = haystacks.some((text) => text === q);
    push({
      kind: "place",
      label: place.label,
      tz: place.tz,
      lat: place.lat,
      lon: place.lon,
      rank: exact ? 0 : 1,
    });
  }

  for (const tz of IANA_TIMEZONES) {
    const norm = normalizeSearchText(tz);
    if (!(norm.includes(q) || tz.toLowerCase().includes(query.trim().toLowerCase()))) continue;
    push({
      kind: "zone",
      label: tz,
      tz,
      lat: null,
      lon: null,
      rank: norm === q ? 0 : norm.startsWith(q) ? 2 : 3,
    });
  }

  matches.sort((a, b) => a.rank - b.rank || a.label.localeCompare(b.label));
  return matches.slice(0, limit);
}

function renderTimezoneResults(pickerRoot, query) {
  const results = pickerRoot.querySelector(".tz-results");
  const search = pickerRoot.querySelector(".tz-search");
  if (!results) return;
  const matches = searchTimezoneMatches(query, 100);
  results.replaceChildren();
  if (search) {
    search.dataset.activeIndex = "-1";
    search.removeAttribute("aria-activedescendant");
    search.setAttribute("aria-expanded", "true");
  }
  if (!matches.length) {
    results.append(element("li", "tz-empty", "No matching place or IANA zone."));
    results.hidden = false;
    return;
  }
  for (const [index, match] of matches.entries()) {
    const item = element("li", "tz-option");
    item.id = `${results.id}-option-${index}`;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", "false");
    item.setAttribute("data-tz", match.tz);
    item.setAttribute("data-label", match.label);
    item.setAttribute("data-lat", match.lat == null ? "" : String(match.lat));
    item.setAttribute("data-lon", match.lon == null ? "" : String(match.lon));
    const title = element("span", "tz-option-title", match.label);
    const meta = element(
      "span",
      "tz-option-meta",
      match.kind === "place" ? match.tz : "IANA timezone",
    );
    item.append(title, meta);
    results.append(item);
  }
  results.hidden = false;
}

function houseOmissionReason(meta) {
  if (meta.houses_enabled === false) {
    return "Houses were not calculated because angles and houses were disabled for this chart.";
  }
  if (meta.time_known === false) {
    return "Houses were not calculated because the civil time is unknown.";
  }
  if (meta.location_known === false) {
    return "Houses were not calculated because both latitude and longitude are required.";
  }
  return "Houses were not calculated for this chart.";
}

function natalHouseLabel(natal) {
  return natal.house_system ? displayName(natal.house_system) : "Not calculated";
}

function transitPlacementNotes(placement) {
  const notes = [];
  if (placement.retro) notes.push("retrograde");
  if (placement.time_sensitive) notes.push("time-sensitive");
  if (placement.blend && placement.secondary_sign) {
    notes.push(`blend ${displayName(placement.secondary_sign)}`);
  }
  return notes;
}

function makeReadingCard(reading) {
  const status = ["ready", "stub", "missing"].includes(reading.status)
    ? reading.status
    : reading.status || "missing";
  const card = element("div", "reading-card");
  card.dataset.status = status;
  const head = element("div", "reading-head");
  head.append(
    element("span", "reading-title", reading.title || reading.id || "Interpretation"),
    makeStatusBadge(status),
  );
  card.append(head);
  const summary = stringValue(reading.summary).trim();
  card.append(
    element(
      "p",
      "reading-summary",
      summary || (status === "missing" ? "Interpretation record missing." : "Interpretation text is not yet authored."),
    ),
  );
  for (const [key, label] of [
    ["body", "Notes"],
    ["shadow", "Lower-expression notes"],
    ["growth", "Development notes"],
    ["blend_note", "Boundary note"],
  ]) {
    if (reading[key]) card.append(element("p", "reading-extra", `${label}: ${reading[key]}`));
  }
  return card;
}

function makeStatusBadge(status) {
  const normalized = ["stub", "missing"].includes(status) ? status : "ready";
  const badge = element("span", `status-badge ${normalized === "ready" ? "" : normalized}`, status || "ready");
  return badge;
}

function makeSection(title, count, key) {
  const section = element("section", "report-section");
  section.dataset.section = key;
  const head = element("div", "report-section-head");
  head.append(element("h3", "", title));
  if (count !== null && count !== undefined) {
    head.append(element("span", "section-count", `${count} ${count === 1 ? "item" : "items"}`));
  }
  const body = element("div", "report-section-body");
  section.append(head, body);
  return { section, body };
}

function detailChip(text, extraClass = "") {
  return element("span", `detail-chip ${extraClass}`.trim(), text);
}

function motionState(aspect) {
  if (Math.abs(Number(aspect.exactness || 0)) <= 1e-10) return "exact";
  if (aspect.applying === true) return "applying";
  if (aspect.applying === false) return "separating";
  return "motion indeterminate";
}

function showLoading(root, empty, title, detail) {
  empty.hidden = true;
  root.hidden = false;
  const loading = element("div", "loading-state");
  loading.append(element("span", "loader"), element("h3", "", title), element("p", "", detail));
  root.replaceChildren(loading);
}

function showError(root, empty, title, detail) {
  empty.hidden = true;
  root.hidden = false;
  const error = element("div", "error-state");
  error.append(element("span", "error-symbol", "!"), element("h3", "", title), element("p", "", detail));
  root.replaceChildren(error);
}

function makeInlineLoader(text) {
  const item = element("div", "inline-state");
  item.append(element("span", "loader"), element("p", "", text));
  return item;
}

function makeInlineError(text) {
  const item = element("div", "inline-state inline-error");
  item.append(element("span", "error-symbol", "!"), element("p", "", text));
  return item;
}

function activateView(name, { updateHash = true } = {}) {
  const valid = ["chart", "library", "transit", "synastry"].includes(name)
    ? name
    : "chart";
  document.querySelectorAll("[data-panel]").forEach((panel) => {
    const active = panel.dataset.panel === valid;
    panel.hidden = !active;
    panel.classList.toggle("is-active", active);
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    const active = button.dataset.view === valid;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  if (updateHash && window.location.hash !== `#${valid}`) {
    history.pushState(null, "", `#${valid}`);
  }
  if (valid === "library" && state.charts.length === 0) void loadLibrary();
}

function viewFromHash() {
  return window.location.hash.replace(/^#/, "") || "chart";
}

async function api(path, { method = "GET", body } = {}) {
  const options = {
    method,
    headers: { Accept: "application/json" },
  };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch (error) {
    throw new Error(`Could not reach the local Sidereal server: ${errorMessage(error)}`);
  }
  const contentType = response.headers.get("content-type") || "";
  let payload;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    payload = await response.text();
  }
  if (!response.ok) {
    const detail = asObject(payload).detail ?? payload;
    throw new Error(formatApiDetail(detail, response.status));
  }
  return payload;
}

function formatApiDetail(detail, status) {
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      const record = asObject(item);
      const location = asArray(record.loc).filter((part) => part !== "body").join(" → ");
      return [location, record.msg].filter(Boolean).join(": ");
    });
    return messages.filter(Boolean).join("; ") || `Local API request failed (${status}).`;
  }
  if (detail && typeof detail === "object") {
    return detail.message || detail.error || JSON.stringify(detail);
  }
  return stringValue(detail).trim() || `Local API request failed (${status}).`;
}

function setBusy(button, busy, busyText) {
  if (!button) return;
  if (busy) {
    button.dataset.idleText = button.textContent;
    if (busyText) button.textContent = busyText;
  } else if (button.dataset.idleText) {
    button.textContent = button.dataset.idleText;
    delete button.dataset.idleText;
  }
  button.disabled = busy;
  button.setAttribute("aria-busy", busy ? "true" : "false");
}

function setStatus(id, message, kind = "") {
  const target = byId(id);
  target.textContent = message;
  target.classList.toggle("is-error", kind === "error");
  target.classList.toggle("is-success", kind === "success");
}

function clearStatus(id) {
  setStatus(id, "");
}

function showToast(message, isError = false) {
  const toast = byId("toast");
  if (state.toastTimer) window.clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.hidden = false;
  state.toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    state.toastTimer = null;
  }, 4200);
}

function fieldValue(form, name) {
  const field = form.elements.namedItem(name);
  return field && "value" in field ? field.value : "";
}

function element(tag, className = "", text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = stringValue(text);
  return item;
}

function byId(id) {
  return document.getElementById(id);
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function stringValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

function numberText(value, places) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(places) : "—";
}

function displayName(identifier) {
  const raw = stringValue(identifier);
  if (!raw) return "Unknown";
  if (DISPLAY_NAMES[raw]) return DISPLAY_NAMES[raw];
  return raw
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function friendlyMoment(value) {
  const raw = stringValue(value);
  if (!raw) return "Unknown moment";
  return raw.replace("T", " ").replace(/([+-]\d\d:\d\d|Z)$/, " $1");
}

function errorMessage(error) {
  return error instanceof Error ? error.message : stringValue(error) || "Unknown error";
}

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
const CHART_NOTE_FALLBACK =
  "Positions, houses, and angular relationships are astronomical geometry. Interpretations are symbolic cultural study notes, not scientific claims about personality, fate, health, or outcomes.";

document.addEventListener("DOMContentLoaded", init);

function init() {
  setFormDefaults();
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
  byId("chart-tz").value = timezone;
  byId("transit-date").value = localDate;
  byId("transit-time").value = localTime;
  byId("transit-tz").value = timezone;
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
        ["Houses", asArray(chart.cusps).length ? displayName(meta.house_system) : "Not calculated"],
        ["Aspect profile", displayName(meta.aspect_profile)],
        ["Ephemeris", meta.ephemeris_backend || "Unknown"],
        ["Julian day UT", numberText(meta.jd_ut, 6)],
        ["Boundary version", meta.boundary_version || "Unknown"],
      ],
    }),
  );
  root.append(makeEpistemic(report.epistemic_note || CHART_NOTE_FALLBACK));

  const warnings = [...asArray(meta.warnings)];
  if (meta.calculation_time_assumption) warnings.unshift(meta.calculation_time_assumption);
  if (warnings.length) root.append(makeWarningsSection(warnings, "Calculation notes"));

  root.append(makePointSection("Angles", angles, "No angles were calculated for this chart.", { showReadings: true }));
  root.append(makePointSection("Planets", planets, "No planetary positions are available."));
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
      chip: "Transit study",
      title: `${natal.label || "Untitled natal"} · transits`,
      subtitle: `Moving sky ${friendlyMoment(transit.local_datetime)} · fixed natal ${friendlyMoment(natal.local_datetime)}`,
      meta: [
        ["Natal timezone", natal.tz || "Unknown"],
        ["Transit timezone", transit.tz || "Unknown"],
        ["Zodiac", displayName(transit.zodiac_system)],
        [
          "Natal houses",
          natal.time_known && natal.location_known
            ? displayName(natal.house_system)
            : "Not calculated",
        ],
        ["Ephemeris", transit.ephemeris_backend || "Unknown"],
        ["Natal source", natal.source || "Inline"],
      ],
    }),
  );
  root.append(makeEpistemic(report.epistemic_note || TRANSIT_NOTE_FALLBACK));
  const warnings = asArray(report.warnings);
  if (warnings.length) root.append(makeWarningsSection(warnings, "Timing notes"));
  root.append(makeTransitPlacementsSection(placements));
  root.append(makeRelationshipsSection(relationships, { transit: true }));
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

function makeRelationshipsSection(entries, { transit = false, geometryOnly = false } = {}) {
  const title = transit ? "Transit–natal relationships" : "Relationships";
  const { section, body } = makeSection(title, entries.length, "relationships");
  if (!entries.length) {
    body.append(element("p", "none-note", "No configured major aspects were found."));
    return section;
  }
  const list = element("div", "relationships-list");
  for (const entry of entries) {
    const aspect = asObject(entry.aspect || entry);
    const reading = entry.reading ? asObject(entry.reading) : null;
    const card = element("article", "relationship-card");
    const head = element("div", "relationship-head");
    const bodyA = transit ? aspect.transit_body : aspect.body_a;
    const bodyB = transit ? aspect.natal_point : aspect.body_b;
    const prefixA = transit ? `Transit ${displayName(bodyA)}` : displayName(bodyA);
    const prefixB = transit ? `natal ${displayName(bodyB)}` : displayName(bodyB);
    head.append(element("h4", "relationship-title", `${prefixA} ${displayName(aspect.aspect_id).toLowerCase()} ${prefixB}`));
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
    if (reading) {
      card.append(makeReadingCard(reading));
    } else if (geometryOnly) {
      card.append(element("p", "none-note", "Geometry only. Re-interpret this chart to join current reading text."));
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
  const grid = element("div", "placement-grid");
  for (const placement of placements) {
    const card = element("article", "placement-card");
    const head = element("div", "placement-card-head");
    head.append(
      element("span", "placement-name", displayName(placement.id)),
      placement.time_sensitive ? element("span", "status-badge stub", "Time-sensitive") : element("span"),
    );
    card.append(head);
    card.append(element("p", "placement-line", `${displayName(placement.sign)} ${numberText(placement.degree_in_sign, 4)}°`));
    const details = element("div", "point-detail");
    if (placement.natal_house !== null && placement.natal_house !== undefined) {
      details.append(detailChip(`Natal house ${placement.natal_house}`));
    }
    if (placement.blend && placement.secondary_sign) {
      details.append(detailChip(`Boundary blend · ${displayName(placement.secondary_sign)}`, "blend"));
    }
    if (details.childElementCount) card.append(details);
    grid.append(card);
  }
  body.append(grid);
  return section;
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
  const valid = ["chart", "library", "transit"].includes(name) ? name : "chart";
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

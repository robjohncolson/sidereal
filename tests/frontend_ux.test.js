"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const appPath = path.join(__dirname, "..", "src/sidereal/web/static/app.js");
const source = fs.readFileSync(appPath, "utf8");
const html = fs.readFileSync(
  path.join(__dirname, "..", "src/sidereal/web/static/index.html"),
  "utf8",
);
const css = fs.readFileSync(
  path.join(__dirname, "..", "src/sidereal/web/static/styles.css"),
  "utf8",
);
const inputs = {
  "test-lat": { value: "", dataset: {} },
  "test-lon": { value: "", dataset: {} },
};
const sandbox = {
  console,
  Intl,
  document: {
    addEventListener() {},
    getElementById(id) {
      return inputs[id] || null;
    },
  },
};
vm.createContext(sandbox);
vm.runInContext(
  `${source}\n` +
    "globalThis.__ux = { searchTimezoneMatches, resolveTimezoneInput, " +
    "maybeFillCoords, houseOmissionReason, natalHouseLabel, transitPlacementNotes };",
  sandbox,
  { filename: appPath },
);

const ux = sandbox.__ux;
const tokyo = ux.searchTimezoneMatches("Tokyo, Japan")[0];
assert.equal(tokyo.label, "Tokyo, Japan");
assert.equal(tokyo.tz, "Asia/Tokyo");
assert.equal(tokyo.lat, 35.6762);
assert.equal(tokyo.lon, 139.6503);

for (const query of ["Atlanta", "Kuala Lumpur"]) {
  assert.equal(
    ux.searchTimezoneMatches(query).some((item) => item.label === "Los Angeles, USA"),
    false,
    `${query} must not match the short alias LA`,
  );
}
assert.equal(
  ux.searchTimezoneMatches("Kuala Lumpur").some((item) => item.tz === "Asia/Kuala_Lumpur"),
  true,
);

assert.equal(ux.resolveTimezoneInput("UTC"), "UTC");
assert.equal(ux.resolveTimezoneInput("America/New_York"), "America/New_York");
assert.equal(ux.resolveTimezoneInput("not/a_timezone"), null);

const pickerRoot = {
  getAttribute(name) {
    return name === "data-lat-field" ? "test-lat" : "test-lon";
  },
};
ux.maybeFillCoords(pickerRoot, 35.6762, 139.6503);
assert.equal(inputs["test-lat"].value, "35.6762");
assert.equal(inputs["test-lon"].value, "139.6503");
ux.maybeFillCoords(pickerRoot, 40.7128, -74.006);
assert.equal(inputs["test-lat"].value, "40.7128");
assert.equal(inputs["test-lon"].value, "-74.006");
inputs["test-lat"].value = "41";
ux.maybeFillCoords(pickerRoot, 51.5074, -0.1278);
assert.equal(inputs["test-lat"].value, "41");
assert.equal(inputs["test-lon"].value, "-74.006");

assert.match(
  ux.houseOmissionReason({ houses_enabled: false, time_known: true, location_known: true }),
  /disabled/,
);
assert.match(
  ux.houseOmissionReason({ houses_enabled: true, time_known: false, location_known: true }),
  /civil time is unknown/,
);
assert.equal(ux.natalHouseLabel({ house_system: null }), "Not calculated");
assert.equal(ux.natalHouseLabel({ house_system: "equal_house_12" }), "Equal 12 houses");
assert.deepEqual(
  Array.from(ux.transitPlacementNotes({ retro: true, time_sensitive: true })),
  ["retrograde", "time-sensitive"],
);

for (const id of ["synastry-view", "synastry-form", "synastry-a", "synastry-b", "synastry-report"]) {
  assert.match(html, new RegExp(`id=["']${id}["']`));
}
for (const id of [
  "synastry-library-list",
  "refresh-synastry-library-button",
  "synastry-selection",
  "refresh-synastry-button",
]) {
  assert.match(html, new RegExp(`id=["']${id}["']`));
}
assert.match(html, /Transits \(sky vs birth chart\)/);
assert.match(html, /id=["']library-transit-button["']/);
assert.match(source, /byId\("transit-date"\)\.value = localDate/);
assert.match(source, /addEventListener\("click", openSelectedTransit\)/);
assert.match(source, /function openSelectedTransit\(\)[\s\S]*activateView\("transit"\)/);
assert.match(source, /api\("\/api\/synastry"/);
assert.match(source, /api\("\/api\/synastries"/);
assert.match(source, /\/api\/synastries\/\$\{encodeURIComponent\(state\.selectedSynastryId\)\}\/refresh/);
assert.match(source, /save_synastry/);
assert.match(source, /Same-body sky–natal contacts/);
assert.match(source, /Two-natal aspects/);
assert.match(source, /function makePlanetsInHousesSection\(/);
assert.match(source, /makeSection\("Planets in houses"/);
assert.match(source, /function makeTransitPlacementsSection\(/);
assert.match(source, /"By natal house"/);
for (const key of ["ArrowUp", "ArrowDown", "Enter", "Escape"]) {
  assert.match(source, new RegExp(`event\\.key === ["']${key}["']`));
}
assert.match(css, /\.tz-results\s*\{[^}]*overflow-y:\s*auto/s);
assert.match(source, /data:image\/svg\+xml;charset=utf-8/);
assert.doesNotMatch(source, /\.innerHTML\s*=/);
assert.match(source, /makeWheelSection\(report\.wheel/);
assert.doesNotMatch(`${html}\n${source}`, /\b(?:bobby|mom|dad)\b/i);

console.log("frontend UX tests passed");

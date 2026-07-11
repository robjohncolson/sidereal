# Codex implementation prompt — Sidereal Phase 5

Work in:

`/mnt/c/Users/rober/Downloads/Projects/sidereal`

**Authority:** `SPEC.md` > this prompt > `CLAUDE.md` > existing code.
**Epistemic split remains law:** geometry is astronomy; text is symbolic study notes — never predictions, medical claims, or “true destiny.”

---

## Already shipped (do not rebuild)

| Phase | Commit | What |
|-------|--------|------|
| 1–2 | `d0473e2` | Engine, Midpoint 13, Seeds 0–2, SQLite |
| 3 | `e5bdf74` | Seed 3, tropical compare, save/list/show |
| 4 | `cf3b53e` | Seeds 4–5, scoped gaps, **transit CLI**, FastAPI web desk |

**Inventory at Phase 4:** 746 ready / 166 stub / 0 missing · **167 tests**
Transit already compares a **moving sky moment** to a **fixed natal** using shared **J2000** longitudes. Web UI: `python -m sidereal serve --host 127.0.0.1 --port 8742`.

### Working-tree UX already done — PRESERVE AND COMMIT FIRST

These edits may be **uncommitted** when you start. **Do not revert or simplify them.** Commit them early (own commit or first Phase 5 commit) before larger work:

| Feature | Files | Behavior to keep |
|---------|-------|------------------|
| **Timezone / place picker** | `web/static/{index.html,app.js,styles.css}` | Searchable + **scrollable** list; `"Tokyo, Japan"` / `tokyo` → `Asia/Tokyo`; full IANA via `Intl.supportedValuesOf('timeZone')` + curated `KNOWN_PLACES`; selecting a known place **fills empty lat/lon** |
| **Planets in houses UI** | same | Chart report section **Planets in houses**: overview table + grouped by house with `planet_in_house:*` readings; transit placements table + **by natal house** |

If anything regresses these, Phase 5 is incomplete.

---

## Mission (Phase 5)

Deliverables, **in this order**:

0. **Commit preserved UX** (timezone picker + planets-in-houses) if still dirty
1. **Same-body transit aspect keys** (Seed 6)
2. **Sky↔natal (transit) polish** + **two-natal synastry**
3. **Wheel SVG** (13-sign Midpoint) in CLI + web
4. **httpx2 deprecation** only if cheap — do not block

---

## Terminology (truth-seeking — use this language in UI/docs)

| Term | Meaning in this project |
|------|-------------------------|
| **Natal** | Chart for a birth/event moment (saved or inline) |
| **Transit** | Moving sky at date T vs one natal (already implemented) |
| **Synastry (two-natals)** | Relationship between **two fixed charts** (two people / two events) |
| **“Current date vs birth”** | **Transit**, not two-natal synastry — improve UX wording so users aren’t confused |

The user’s mental model is “synastry with the sky.” **Do not remove transit.** Improve labeling and add two-natal synastry as a **separate** command/tab.

---

## Non-negotiables

1. No second calculation stack in JS — SVG is pure rendering of computed JSON.
2. Midpoint remains unequal 13 segments; Ophiuchus first-class; tropical compare unchanged.
3. Same J2000 common-frame rules for any cross-chart aspects (transit and two-natal).
4. Seeds deterministic; higher version upgrades; original non-fatalistic prose.
5. Never commit `.se1`, `*.db`, `charts/`, `reports/`, `.venv/`.
6. Web stays localhost-default with Host/DNS-rebinding protection.
7. Geometry modules stay free of interpretive essays.
8. **Keep** timezone picker + planets-in-houses report sections when editing `app.js` / HTML / CSS.

---

# Workstream 1 — Same-body transit aspect keys (Seed 6)

### Problem

Transit can hit e.g. **transit Jupiter × natal Jupiter**. Inventory was built from `combinations(distinct bodies)`, so keys like:

`aspect:jupiter:sextile:jupiter`

never exist → report gaps `kind: missing`.

### Required

1. Extend inventory **or** add Seed 6 that introduces **same-body major aspect keys** for every body in `ASPECT_BODIES` that can appear on both sides of a transit pair.

   Bodies that need self-aspects: at least all planets + nodes used in transit
   `sun, moon, mercury, venus, mars, jupiter, saturn, uranus, neptune, pluto, north_node`
   (Asc/MC self-aspects are nonsense for transit-planet×natal-angle; skip angle self-keys.)

2. For each body B and each major aspect type T ∈ {conjunction, opposition, trine, square, sextile}:

   - ID: `aspect:{B}:{T}:{B}` (body appears twice; validate schema allows `body_a == body_b` for this case **or** use a dedicated type — prefer allowing equal bodies only when `body_a == body_b` and document it)

3. **Schema change carefully:**
   - Today SQLite may enforce `body_a < body_b`. If so, migrate CHECK to
     `body_a < body_b OR body_a = body_b`
   - Bump schema only if needed; keep backward-compatible import.
   - Update `aspect_key()` / validation / `TOTAL_INVENTORY_COUNT` / Seed 0 generator.

4. **Seed 6 ready text** (`seed_6_self_aspects_v1.json`):
   - Ready (not stub) summaries for self-aspects that matter most in transit:
     **all 5 aspects × personal planets (sun–saturn)** = 35
   - Stub inventory rows for outer self-aspects if you add them to inventory, **or** also ready them if cheap (5 × remaining bodies).
   - Prefer: full inventory coverage (no missing), ready quality for sun–saturn self-aspects; outers can be stub.

5. Tone examples:
   - Conjunction: “theme of B is emphasized / renewed by timing”
   - Square: “friction within the same planetary principle across time”
   - Opposition: “polarization or rebalancing of that principle”
   Always: not predictive of events.

6. Tests:
   - Key `aspect:jupiter:sextile:jupiter` exists after import
   - Transit report for a synthetic or golden case with self-aspect does not list that key as `missing`
   - Inventory counts exact

---

# Workstream 2 — “Synastry” UX + optional two-natal

### 2A. Transit presentation polish (required — this is what the user wants first)

Treat transit reports as **“Sky ↔ Natal”** study:

1. **CLI + Markdown + Web** labels:
   - Section title options: “Sky–Natal aspects (transits)”
   - Subtitle: “Moving sky at {T} relative to natal {label}”
   - Avoid implying romantic synastry unless two human natals

2. **Highlight same-body hits** (e.g. “Transit Saturn to natal Saturn”) in a dedicated subsection when present

3. **Web UI:**
   - Rename/clarify transit tab: “Transits (sky vs birth chart)”
   - Default transit date = **today** in the browser’s local timezone (editable)
   - One-click “Transit for selected saved chart”

4. Docs in README: short “Transit vs two-person synastry” callout

### 2B. Two-natal synastry (required if 2A is done; small solid version)

```bash
python -m sidereal synastry \
  --a Me --b Partner \
  # or inline moments for A and B
  --db data/sidereal.db \
  --md ... --out ...
```

- Compute two natal charts (existing `compute`)
- Cross aspects: every body/angle in A to every body/angle in B (majors only), **J2000 common frame** if charts differ in epoch (they will) — reuse transit aspect machinery where possible
- Orbs: same profile as natal/transit
- Interpretation: reuse `aspect:{a}:{type}:{b}` keys
- Output JSON+MD + web API `POST /api/synastry` + UI form (two saved charts or two moment forms)
- Epistemic note: symbolic relationship language, not compatibility scores or destiny

**Out of scope for 2B:** composite charts, Davison, house overlays beyond optional “A’s planets in B’s houses” as a stretch.

### Stretch (only after 2B works)

- A’s planets in B’s houses (and reverse) when both times known

---

# Workstream 3 — Wheel SVG

### Goal

A clean **13-sign Midpoint wheel** for natal (and optionally transit overlay).

### Geometry (render-only)

- Outer ring: unequal arcs from `midpoint_j2000_v1` lengths (normalized to 360°)
- Sign labels including Ophiuchus
- Planet ticks/glyphs or abbreviations at degree-in-sign positions along Midpoint frame
- House cusps as lines from center (equal 12 from Asc) when time known
- Asc at traditional “9 o’clock” or eastern horizon convention — **pick one, document, test**
- Blend zones: optional soft tick at boundaries

### Outputs

1. **Pure function** e.g. `sidereal.wheel.render_svg(chart, *, width=640) -> str`
2. Embed SVG in Markdown reports as fenced raw HTML only if viewer supports it; **always** also write `*.svg` alongside `--md` when `--svg path` or default next to `--out`
3. Web UI: show wheel above the placement table for chart + transit (transit: natal wheel + outer transit ticks, or two colors)

### Quality bar

- Readable at 640–900px
- Works in light background; web theme-compatible
- No JS canvas dependency required for export
- Unit test: SVG contains 13 sign ids / Ophiuchus string; planet count matches

### Non-goals

- 3D sky, animation, drag-and-drop, print-shop quality

---

# Workstream 4 — httpx2 deprecation (lowest priority)

**What it is:** Pytest shows
`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
This is an **upstream TestClient dependency warning**, not a user-facing bug. It does **not** affect the astrology app.

**Do if easy:**

- Add `httpx2` (or whatever current Starlette docs recommend) to `[web]` / `[dev]` extras
- Confirm warning gone under `pytest`
- If httpx2 is immature or breaks TestClient, **skip** and document in `IMPLEMENTATION_NOTES.md`

Do **not** spend more than ~30 minutes on this. Prefer Seeds + synastry + SVG.

---

## Implementation order (strict)

```
1. Schema/inventory support for same-body aspect keys
2. Seed 6 generator + import + transit gap tests
3. Transit UI/docs “sky vs natal” polish + same-body subsection
4. Wheel SVG pure renderer + natal report/web embed
5. Two-natal synastry CLI + API + UI
6. Transit overlay on wheel (nice)
7. httpx2 only if time left
8. pytest + smoke + README/CLAUDE
9. Commit on main
```

---

## Acceptance checklist

- [ ] After `db import`, `aspect:sun:conjunction:sun` (and jupiter self-aspects) exist; transit self-hits not `missing`
- [ ] Inventory still 0 missing; ready count increased by Seed 6 readies
- [ ] Web transit form defaults to today; clear “sky vs birth” labeling
- [ ] Natal report can emit SVG wheel with 13 signs + planets
- [ ] Web shows wheel for a computed chart
- [ ] `synastry` CLI produces cross aspects for two saved charts
- [ ] `POST /api/synastry` works; UI can run it
- [ ] pytest green; no secrets/ephe binaries committed
- [ ] httpx warning fixed **or** explicitly deferred in notes

---

## Out of scope

- Cloud, auth, multi-user
- Composite/Davison charts
- Progressions, solar return (future phase)
- Scraping commercial copy
- Rewriting Phase 1–4 geometry
- Public bind by default

---

## Manual smoke

```bash
python -m sidereal db import --db data/sidereal.db
python -m sidereal transit --natal Demo --date 2026-07-11 --time 12:00 --tz UTC \
  --db data/sidereal.db --out /tmp/tr.json --md /tmp/tr.md --svg /tmp/tr.svg
# confirm no missing aspect:jupiter:*:jupiter style gaps for self hits present

python -m sidereal chart --date 2000-12-12 --time 12:00 --tz UTC --lat 0 --lon 0 \
  --db data/sidereal.db --svg /tmp/wheel.svg --md /tmp/c.md

python -m sidereal synastry --a Demo --b Demo2 --db data/sidereal.db --md /tmp/syn.md

python -m sidereal serve --host 127.0.0.1 --port 8742 --db data/sidereal.db
pytest
```

---

## Definition of done

Phase 5 done when: same-body transit keys no longer leave holes; users can read **sky vs natal** clearly (and optionally two-natals); and a **13-sign SVG wheel** appears in CLI export and the local web desk.

Start with Workstream 1. Prefer a correct small wheel over a fancy incomplete one.

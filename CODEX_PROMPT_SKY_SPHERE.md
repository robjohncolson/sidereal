# Codex prompt — sky sphere reference math (Parcel F)

Copy everything below the line into Codex. Working directory: **sidereal**.

---

## Mission

Implement **Parcel F** of Personal Planetarium **v2.1**: pure, tested **reference math** for a simplified rotating celestial sphere so Moon Chorus can spin constellations + planets together and use a real horizon.

You do **not** edit aim-dojo. You do **not** need to change skypack schema (v2 fields already shipped).

## Required reading (first)

1. **Plan (source of truth):**  
   `/mnt/c/Users/rober/Downloads/Projects/aim-dojo/SPEC_PERSONAL_PLANETARIUM_V2_1.md`  
   Read §0–4, §6–9 (Parcel F). **Plan wins** on conflict.

2. Optional context: `SPEC_PERSONAL_PLANETARIUM_V2.md` (Δ/seals/sticks — already done; do not re-litigate).

## Scope — Parcel F

| ID | Deliverable |
|----|-------------|
| F1 | Module e.g. `src/sidereal/sky_sphere.py` with pure functions |
| F2 | Unit tests: noon elev max; half-turn sun below horizon; co-rotation sanity |
| F3 | Short doc: `docs/sky_sphere_v2_1.md` **or** README subsection with formulas + frame |
| F4 | Skypack tests still pass; no aim-dojo files |

## Frame contract (implement exactly unless you document a better equivalent)

Use a **right-handed** unit-sphere model Fable can copy:

### Coordinates (sphere-local, before diurnal spin)

- Ecliptic longitude `lon_deg` ∈ [0, 360), latitude `lat_deg` (default 0).
- Simplified: treat ecliptic as the sphere’s “equator” in local frame:

```text
az = radians(lon_deg)
el = radians(lat_deg)    # 0 for most bodies in v2.1
x = cos(el) * cos(az)
y = sin(el)              # "north pole" of this simplified frame
z = cos(el) * (-sin(az)) # match common Three.js-ish chartLonDir if helpful
```

Document the exact formulas you ship; consistency > astronomy textbook purity.

### Diurnal spin

- `spin_phase` ∈ [0, 1): fraction of a diurnal cycle (theatre or civil).
- `sun_lon_deg`: epoch solar ecliptic longitude (from pack mover sun).
- **Noon policy:** at `spin_phase == 0` (define as **solar noon**), after applying spin, the **sun direction’s elevation is maximal** among spin phases (test this).
- Suggested:

```text
sphere_angle_deg = normalize(noon_anchor_deg - sun_lon_deg + spin_phase * 360)
```

Choose `noon_anchor_deg` so the noon test passes; document the constant.

- Apply spin as rotation about **+Y** (vertical in sphere-local / world-up after identity parent):

```text
R_y(sphere_angle) * p_local  →  p_world
```

### Horizon

- `above_horizon(p_world, y_horizon=0.0) -> bool` using `p_world.y > y_horizon` (epsilon OK).
- At `spin_phase = 0` (noon): sun **above** horizon and elev near max.
- At `spin_phase = 0.5`: sun **below** horizon.

### API sketch (names flexible, behavior not)

```python
def ecliptic_to_vec(lon_deg: float, lat_deg: float = 0.0) -> tuple[float, float, float]: ...
def sphere_angle_deg(spin_phase: float, sun_lon_deg: float, *, noon_anchor_deg: float = ...) -> float: ...
def apply_spin(vec, angle_deg: float) -> tuple[float, float, float]: ...
def elevation_deg(vec) -> float: ...  # asin(y) or atan2
def above_horizon(vec, y_horizon: float = 0.0, eps: float = 1e-9) -> bool: ...
def sun_world_dir(sun_lon_deg: float, spin_phase: float, **kw) -> tuple[float, float, float]: ...
```

All angles in degrees at the public API unless you document radians consistently.

## Tests (required)

File e.g. `tests/test_sky_sphere.py`:

1. `ecliptic_to_vec` unit length; lon 0 vs 90 differ.
2. For a fixed `sun_lon`, sample spin phases: **max elevation at phase 0** (noon), **min or negative at 0.5**.
3. `above_horizon(sun, 0)` True at 0, False at 0.5.
4. Two points with lon differing by 0: after same spin, still same vector (co-located).
5. Two points with fixed lon separation: angular separation preserved under spin (constellations locked to sun separation).
6. Invalid inputs (non-finite) raise clear errors matching project style.

Run:

```bash
pytest tests/test_sky_sphere.py -q
pytest tests/test_skypack.py -q
```

## Out of scope

- Three.js / aim-dojo
- Changing skypack JSON schema
- Full LST, observer lat/lon, refraction
- Swiss Ephemeris calls inside these helpers (they are pure geometry)

## Definition of done

- [ ] F1–F4 complete  
- [ ] Tests green  
- [ ] Doc lists formulas Fable must mirror  
- [ ] Print: module path, noon_anchor choice, example numbers for sun_lon=109°, phase=0 and 0.5  

**Begin:** read the v2.1 plan §4, then implement F1.

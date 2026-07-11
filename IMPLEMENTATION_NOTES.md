# Implementation notes

## J2000 conversion for equal-house cusps and angles

Swiss Ephemeris directly converts calculated bodies with `FLG_J2000`, but its
sidereal-house projection is not a per-vector conversion of tropical equal
houses. The Swiss programmer documentation explicitly excludes that shortcut
for equal houses. Sidereal therefore:

1. calculates Ascendant, Midheaven, and twelve equal cusps in the tropical
   ecliptic of date with `houses_ex2(..., b"E")`;
2. requests Cartesian (`FLG_XYZ`) vectors for the required bodies in both the
   date and `FLG_J2000` frames;
3. chooses the widest-separated reference pair, constructs corresponding
   orthonormal bases, and derives the rigid rotation
   `R = B_j2000 × transpose(B_date)`;
4. applies `R` independently to every tropical cusp/angle unit vector before
   Midpoint boundary lookup.

This remains tied to Swiss Ephemeris' selected precession/nutation model,
including long-range dates, without using a private C API or adding another
astronomy dependency. Tests compare the recovered transform with direct
`FLG_J2000` body results to floating-point precision and include a real cusp
that changes from Gemini to Cancer when transformed correctly.

Revalidate this path when upgrading Swiss Ephemeris by running
`tests/test_ephemeris.py` and the full chart golden suite.

## Tropical comparison frame

Comparison mode deliberately computes the primary Midpoint chart only once.
Its existing sign fields come from J2000 longitude and the unequal Midpoint
table. The tropical mapper instead reads each point or cusp's already-computed
`lon_date` and applies twelve half-open 30° slices beginning at 0° Aries.

This keeps the civil moment, equal-house geometry, house assignments, aspects,
and patterns identical between the displayed columns. Only sign labels and
degrees within those signs change. The comparison is attached to the report as
geometry and never generates a second set of interpretation lookups or gaps.
Saved charts retain both longitude frames, so the same comparison can be
reconstructed from a local geometry snapshot without another ephemeris call.

## Common frame for cross-time transit geometry

Within one natal or transit chart, ordinary aspects use tropical ecliptic
longitude of that chart's date: every point shares the same instantaneous
frame, so their angular separations are coherent. A transit comparison joins
two different dates. Comparing each point's `lon_date` directly would mix two
precessing axes and can change aspect membership or put a moving planet on the
wrong side of a natal house cusp.

Transit-to-natal aspects therefore compare both points' `lon_j2000` values,
and natal-house overlays compare the transit body's J2000 longitude with the
natal Ascendant's J2000 longitude. Applying/separating uses the moving body's
Swiss Ephemeris `FLG_J2000` longitudinal speed while the natal point remains a
fixed reference. Older saved snapshots that predate the additive J2000-speed
field remain loadable and fall back to their stored date-frame speed; newly
calculated and saved charts retain both speed frames.

## Same-body aspect inventory and database migration

Cross-time comparisons can legitimately contain the same planetary principle
on each side, such as moving Jupiter sextile natal Jupiter. The interpretation
inventory therefore contains five major-aspect keys for each body that can
appear on both sides: Sun through Pluto plus North Node. Equal bodies remain
invalid for every other interpretation type and for Ascendant, Midheaven, and
South Node aspect keys.

Seed JSON keeps schema version 1. The SQLite interpretation database is version
2 because its original table constraint required `body_a < body_b`. Opening a
version 1 database for import rebuilds the entries table transactionally with
the narrow same-body allowlist, copies every existing column and user record,
recreates indexes and metadata, and rolls back the whole migration on failure.
Compatible user-created indexes and triggers are replayed in the same
transaction; an incompatible extension aborts instead of being silently lost.
Newer unknown database versions are rejected rather than guessed at.

## Two-fixed-chart synastry geometry

Two-natal synastry reuses the cross-chart major-aspect matcher and compares the
stored `lon_j2000` values for chart A and chart B. Roles are never canonicalized
away: JSON retains `a_point` and `b_point`, while the interpretation lookup alone
uses the existing canonical aspect key. Ascendant and Midheaven participate
only for a side whose time and location are known. Derived Descendant, IC, and
South Node remain excluded to avoid duplicate geometry.

Both source charts are fixed snapshots, so applying/separating has no temporal
direction and is serialized as `null`. The report describes symbolic
relationship themes without compatibility scores, destiny language, or
predictions. Composite/Davison charts and cross-house overlays are intentionally
outside Phase 5.

## Midpoint SVG wheel

`sidereal.wheel.render_svg` is a deterministic renderer over a computed chart;
it never calls Swiss Ephemeris or remaps a sign. It draws the thirteen canonical
J2000 Midpoint arcs directly from consecutive boundary starts, places a known
Ascendant at 9 o'clock, and omits house lines for unknown-time charts. Nearby
point labels use deterministic radial lanes. An optional already-computed
moving chart is drawn in a distinct outer lane for transit reports.

The CLI writes a standalone SVG and links it from Markdown. The web API returns
the same SVG with explicit media/kind metadata, and the browser displays it as
an inert data-URI image rather than injecting its markup into the document.
The renderer rejects malformed/non-Midpoint input and emits no scripts,
external references, event attributes, embedded images, or `foreignObject`.

## Starlette TestClient transport

Starlette 1.x prefers `httpx2` for `TestClient` and warns when falling back to
the deprecated plain-`httpx` transport. The optional `web` extra therefore adds
`httpx2>=2,<3`; it also retains `httpx>=0.27,<1` for the older FastAPI/Starlette
versions allowed by the project's compatibility range. Current Starlette picks
`httpx2`, so the web/API suite can be exercised with
`StarletteDeprecationWarning` promoted to an error so a future dependency change
cannot silently restore the fallback.

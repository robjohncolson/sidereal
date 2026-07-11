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

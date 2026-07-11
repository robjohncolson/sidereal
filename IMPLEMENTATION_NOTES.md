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

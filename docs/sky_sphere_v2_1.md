# Sky sphere v2.1 reference frame

This is the geometry contract for Moon Chorus to mirror. It is deliberately a
simplified rotating unit sphere, not observer-specific horizon astronomy. All
public angles are degrees.

## Frames and formulas

For ecliptic longitude `lon` and latitude `lat`, first build a sphere-local
direction. The local ecliptic is the XZ great circle and local +Y is ecliptic
north:

```text
a = radians(normalize(lon))
e = radians(lat)

p_local = (
  cos(e) * cos(a),
  sin(e),
  cos(e) * -sin(a)
)
```

The diurnal yaw is:

```text
NOON_ANCHOR_DEG = 90
sphere_angle = normalize(90 - sun_lon + spin_phase * 360)
```

`spin_phase` is in `[0, 1)`. Phase 0 means solar noon; phase 0.5 is the
opposite half-turn. `sun_lon` is the Sun's fixed epoch longitude from the
skypack. Theatre time advances `spin_phase`, never `sun_lon` or another body's
longitude.

The world transform is a local +Y yaw followed by a fixed +90-degree X basis
tilt:

```text
p_world = R_x(+90 degrees) * R_y(sphere_angle) * p_local
```

For a latitude-zero body, the combined formula simplifies to:

```text
u = radians(lon + sphere_angle)
p_world = (cos(u), sin(u), 0)
```

The fixed tilt is necessary. A bare `R_y` applied to the specified local frame
preserves `p_local.y`; every latitude-zero body would remain on the horizon and
could never rise or set. The tilt maps local `(x, y, z)` after yaw to world
`(x, -z, y)`. Equivalently, the local polar axis lies along world +Z, on the
horizon. This is a coherent equatorial-observer simplification: it is not LST,
observer latitude, obliquity, or refraction.

In a nested Three.js-style scene graph, the same transform can be represented
by a fixed parent X rotation of `+pi/2` and a child sphere Y rotation of
`radians(sphere_angle)`. All sticks, bodies, ghosts, labels, and seals must be
children of that same rotating sphere so their angular separations stay fixed.

## Elevation and horizon

World +Y is up. For a non-zero world direction `(x, y, z)`:

```text
elevation_deg = degrees(atan2(y, hypot(x, z)))
above_horizon = y > y_horizon + epsilon
```

The reference epsilon is `1e-9`; a point exactly on the horizon is not above
it. Lighting should derive from the spun Sun's world Y/elevation, not from a
separate art-disc clock.

For `sun_lon = 109 degrees`:

| Phase | Sphere angle | Sun world direction | Elevation | Above horizon |
|---:|---:|---:|---:|:---:|
| `0.0` | `341 degrees` | approximately `(0, 1, 0)` | `+90 degrees` | yes |
| `0.5` | `161 degrees` | approximately `(0, -1, 0)` | `-90 degrees` | no |

The Python reference implementation is
[`src/sidereal/sky_sphere.py`](../src/sidereal/sky_sphere.py).

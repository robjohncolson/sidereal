from __future__ import annotations

from sidereal.interpret.compose import _relationship_sort_key
from sidereal.types import AspectHit


def test_relationship_sort_keeps_spec_priority_then_uses_force_and_exactness() -> None:
    luminary = AspectHit(
        "moon", "sun", "square", 87.0, 9.0, 3.0, 0.1, False
    )
    tight_personal = AspectHit(
        "mars", "venus", "trine", 120.2, 8.0, 0.2, 0.975, True
    )
    loose_personal = AspectHit(
        "mercury", "venus", "sextile", 61.5, 6.0, 1.5, 0.75, False
    )

    ordered = sorted(
        (loose_personal, tight_personal, luminary),
        key=_relationship_sort_key,
    )

    assert ordered == [luminary, tight_personal, loose_personal]

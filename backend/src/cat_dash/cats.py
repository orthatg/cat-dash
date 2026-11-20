"""Which cat used the litter box: match each weight reading to a Whisker pet profile.

Whisker's own per-pet weight history only reaches back about a week, while the box's
activity log (which Cat Dash keeps) has every reading. Assigning each reading to the
pet whose profile weight is closest agreed with Whisker's attribution on all 77
overlapping readings (2026-11-20; cats about 5.4 lb and 14.7 lb).
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import CatProfile

# A reading further than this fraction from every profile is left unattributed.
MAX_RELATIVE_DISTANCE = 0.35


def attribute(weight: float | None, cats: Sequence[CatProfile]) -> str | None:
    if weight is None or not cats:
        return None
    best = min(cats, key=lambda cat: abs(cat.weight_lbs - weight))
    if (
        best.weight_lbs <= 0
        or abs(best.weight_lbs - weight) / best.weight_lbs > MAX_RELATIVE_DISTANCE
    ):
        return None
    return best.name

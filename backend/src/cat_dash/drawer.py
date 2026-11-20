"""Waste drawer tracking: infer "drawer emptied" from the drawer level history.

The Litter-Robot 4 logs no "drawer emptied" event and has no reset command; its
laser just measures the drawer. Its own DFINumberOfCycles counter does not reset
when the drawer is emptied either (checked against a live LR4, 2026-11-20).

What does work: the DFILevelPercent readings logged after each clean cycle climb
as the drawer fills, then fall to 0 once it's emptied (the Whisker app shows
"Empty"). Smaller dips (e.g. 92 -> 68, 81 -> 55) are sensor noise and are ignored.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

# A reading at or below this counts as an empty drawer...
EMPTY_AT_OR_BELOW = 5.0
# ...if the reading before it was at least this full.
MIN_LEVEL_BEFORE = 30.0


def detect_empties(
    levels: Iterable[tuple[datetime, float]],
) -> list[tuple[datetime, float]]:
    """Return (emptied_at, level_before) for each empty, from (time, percent) readings."""
    empties: list[tuple[datetime, float]] = []
    previous: float | None = None
    for timestamp, percent in sorted(levels):
        if previous is not None and percent <= EMPTY_AT_OR_BELOW and previous >= MIN_LEVEL_BEFORE:
            empties.append((timestamp, previous))
        previous = percent
    return empties

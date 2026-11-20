"""Waste drawer tracking: infer "drawer emptied" from the drawer level history.

The Litter-Robot 4 logs no "drawer emptied" event and has no reset command; its
laser just measures the drawer. Its own DFINumberOfCycles counter does not reset
when the drawer is emptied either (checked against a live LR4, 2026-11-20).

What does work: the DFILevelPercent readings logged after each clean cycle climb
as the drawer fills, then fall to 0 once it's emptied (the Whisker app shows
"Empty"). Smaller dips (e.g. 92 -> 68, 81 -> 55) are sensor noise and are ignored.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

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


# --- When will it need emptying? ---------------------------------------------------

FULL_PERCENT = 100.0
# How many recent fill cycles to learn from (median, so one odd cycle doesn't skew it).
RECENT_CYCLES = 5


@dataclass(frozen=True)
class FillModel:
    """How fast this drawer fills, learned from past fill cycles."""

    rate_percent_per_day: float
    usual_empty_percent: float  # the level the drawer is typically emptied at
    cycles_used: int


@dataclass(frozen=True)
class DrawerForecast:
    needs_emptying_at: datetime  # reaches the usual emptying level
    full_at: datetime  # reaches 100%


def fill_model(empties: Sequence[tuple[datetime, float]]) -> FillModel | None:
    """Each pair of consecutive empties is one fill cycle: 0% -> level_before over that
    many days. Live LR4 (Oct-Nov 2026): 9.7-22.4 %/day, median 18.8; usually emptied
    around 82%."""
    ordered = sorted(empties)
    rates = [
        level / days
        for (previous, _), (emptied_at, level) in zip(ordered, ordered[1:], strict=False)
        if (days := (emptied_at - previous).total_seconds() / 86400) > 0.25 and level > 0
    ][-RECENT_CYCLES:]
    if not rates:
        return None
    usual = median(level for _, level in ordered[-RECENT_CYCLES:])
    # Never forecast "needs emptying" past full.
    return FillModel(
        rate_percent_per_day=median(rates),
        usual_empty_percent=min(usual, FULL_PERCENT),
        cycles_used=len(rates),
    )


def forecast(model: FillModel, current_percent: float, now: datetime) -> DrawerForecast:
    def when(target: float) -> datetime:
        remaining = max(0.0, target - current_percent)
        return now + timedelta(days=remaining / model.rate_percent_per_day)

    return DrawerForecast(
        needs_emptying_at=when(model.usual_empty_percent),
        full_at=when(FULL_PERCENT),
    )

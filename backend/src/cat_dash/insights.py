"""Behaviour insights that combine the litter box and the feeders (same room).

- Time between litter box visits, per cat.
- Litter box visits relative to meals: how many minutes after (or before) a cat's
  feeder visit it uses the litter box, compared with what chance alone would give.

Checked on live data (Oct 21 - Nov 20, 2026): Zora used the box within 15 min after
eating 45% of the time vs 16% expected by chance; Maui within 30 min 48% vs 17%.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from datetime import datetime, timedelta
from statistics import median, quantiles

# Weight readings closer than this are one visit (a cat can step on and off).
SAME_VISIT = timedelta(minutes=10)
GAP_BINS_HOURS = [0, 1, 2, 3, 4, 6, 8, 12, 18, 24, 36, 48]
OFFSET_WINDOW_MIN = 120
OFFSET_BIN_MIN = 10
AFTER_MEAL_WINDOWS_MIN = (15, 30, 60)


def merge_visits(times: Sequence[datetime]) -> list[datetime]:
    visits: list[datetime] = []
    for t in sorted(times):
        if not visits or t - visits[-1] > SAME_VISIT:
            visits.append(t)
    return visits


def visit_gaps(visits: Sequence[datetime]) -> dict | None:
    """Hours between consecutive litter box visits: median, quartiles and a histogram."""
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(visits, visits[1:], strict=False)]
    if len(gaps) < 2:
        return None
    q1, _, q3 = quantiles(gaps, n=4)
    bins = []
    edges = [*GAP_BINS_HOURS, None]
    for lo, hi in zip(edges, edges[1:], strict=False):
        count = sum(1 for g in gaps if g >= lo and (hi is None or g < hi))
        bins.append({"from_hours": lo, "to_hours": hi, "count": count})
    while bins and bins[-1]["count"] == 0:  # trim empty tail bins
        bins.pop()
    return {
        "visits": len(visits),
        "median_hours": round(median(gaps), 2),
        "p25_hours": round(q1, 2),
        "p75_hours": round(q3, 2),
        "histogram": bins,
    }


def _coverage_after(
    meals: Sequence[datetime], minutes: int, start: datetime, end: datetime
) -> float:
    """Fraction of [start, end] that lies within `minutes` after some meal (chance level)."""
    total = (end - start).total_seconds()
    if total <= 0:
        return 0.0
    covered = 0.0
    covered_until = start
    for meal in meals:
        lo = max(meal, covered_until, start)
        hi = min(meal + timedelta(minutes=minutes), end)
        if hi > lo:
            covered += (hi - lo).total_seconds()
            covered_until = hi
    return covered / total


def meal_timing(litter_visits: Sequence[datetime], meals: Sequence[datetime]) -> dict | None:
    """How litter box visits line up with feeder visits for the same cat."""
    meals = sorted(meals)
    if len(meals) < 2 or len(litter_visits) < 2:
        return None
    start = max(meals[0], litter_visits[0])
    end = min(meals[-1], litter_visits[-1])
    visits = [t for t in litter_visits if start <= t <= end]
    if len(visits) < 2:
        return None

    # Minutes since the most recent meal, for each litter visit.
    since_meal = []
    for t in visits:
        i = bisect_right(meals, t)
        if i:
            since_meal.append((t - meals[i - 1]).total_seconds() / 60)
    after = []
    for window in AFTER_MEAL_WINDOWS_MIN:
        share = sum(1 for m in since_meal if m <= window) / len(visits)
        after.append(
            {
                "within_minutes": window,
                "share": round(share, 3),
                "chance": round(_coverage_after(meals, window, start, end), 3),
            }
        )

    # Offsets of every meal within +-2 h of each litter visit (litter time - meal time).
    window = timedelta(minutes=OFFSET_WINDOW_MIN)
    counts = [0] * (2 * OFFSET_WINDOW_MIN // OFFSET_BIN_MIN)
    for t in visits:
        for meal in meals[bisect_left(meals, t - window) : bisect_right(meals, t + window)]:
            offset = (t - meal).total_seconds() / 60
            index = int((offset + OFFSET_WINDOW_MIN) // OFFSET_BIN_MIN)
            if 0 <= index < len(counts):
                counts[index] += 1
    span_minutes = (end - start).total_seconds() / 60
    meals_in_span = sum(1 for m in meals if start <= m <= end)
    expected = len(visits) * meals_in_span / span_minutes * OFFSET_BIN_MIN if span_minutes else 0
    return {
        "litter_visits": len(visits),
        "meals": meals_in_span,
        "median_minutes_after_meal": round(median(since_meal)) if since_meal else None,
        "after_meal": after,
        "offsets": {
            "bin_minutes": OFFSET_BIN_MIN,
            "bins": [
                {"from_minutes": -OFFSET_WINDOW_MIN + i * OFFSET_BIN_MIN, "count": c}
                for i, c in enumerate(counts)
            ],
            "expected_per_bin": round(expected, 2),
        },
    }

from datetime import UTC, datetime, timedelta

from cat_dash.insights import meal_timing, merge_visits, visit_gaps

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def test_merge_visits_joins_readings_minutes_apart():
    assert merge_visits([at(0), at(4), at(9), at(60)]) == [at(0), at(60)]


def test_visit_gaps():
    visits = [at(h * 60) for h in (0, 2, 4.5, 7, 9.5)]  # gaps 2, 2.5, 2.5, 2.5 h
    gaps = visit_gaps(visits)
    assert gaps["visits"] == 5
    assert gaps["median_hours"] == 2.5
    counts = {b["from_hours"]: b["count"] for b in gaps["histogram"]}
    assert counts[2] == 4 and sum(counts.values()) == 4
    assert visit_gaps([at(0), at(60)]) is None  # one gap is not a distribution


def test_meal_timing_detects_litter_after_meals():
    # Meals every 4 h; the cat always uses the box 10 min after eating.
    meals = [at(m) for m in range(0, 24 * 60 * 5, 240)]
    litter = [m + timedelta(minutes=10) for m in meals[:-1]]
    timing = meal_timing(litter, meals)
    within15 = next(a for a in timing["after_meal"] if a["within_minutes"] == 15)
    assert within15["share"] == 1.0
    assert 0.05 < within15["chance"] < 0.08  # 15 of every 240 minutes
    assert timing["median_minutes_after_meal"] == 10
    bins = {b["from_minutes"]: b["count"] for b in timing["offsets"]["bins"]}
    assert bins[10] == len(litter)  # all at +10..+20 min
    assert bins[-120] == 0
    # If unrelated: visits x 10-min bin x one meal per 240 min.
    assert timing["offsets"]["expected_per_bin"] == round(len(litter) * 10 / 240, 2)


def test_meal_timing_needs_overlap():
    assert meal_timing([at(0)], [at(0), at(10)]) is None
    assert meal_timing([at(0), at(10)], []) is None

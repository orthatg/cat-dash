"""Vendor-neutral models the frontend sees."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CatProfile(BaseModel):
    """A pet profile from the Whisker app (used to tell cats apart by weight)."""

    name: str
    weight_lbs: float


class LitterBoxStatus(BaseModel):
    device_id: str
    name: str
    model: str
    serial: str
    online: bool
    powered_on: bool
    status_code: str | None
    status_text: str | None
    waste_drawer_percent: float
    waste_drawer_full: bool
    # "empty" / "partial" / "full", matching the Whisker app.
    waste_drawer_state: str | None = None
    litter_level_percent: float | None
    litter_level_state: str | None = None
    cat_weight_lbs: float | None
    lifetime_cycles: int | None = None
    sleeping: bool
    # From the activity history (synced every few minutes).
    last_clean_cycle_at: datetime | None = None
    last_cat_detected_at: datetime | None = None
    # Whisker pet profiles, and which of them the latest weight reading matches.
    cats: list[CatProfile] = Field(default_factory=list)
    last_cat: str | None = None
    # Inferred from the drawer level falling to ~0 (see cat_dash.drawer).
    last_emptied_at: datetime | None = None
    cycles_since_emptied: int | None = None
    # Forecast from the drawer's own fill history (see cat_dash.drawer.fill_model).
    drawer_fill_rate_per_day: float | None = None
    drawer_usual_empty_percent: float | None = None
    drawer_needs_emptying_at: datetime | None = None
    drawer_full_at: datetime | None = None
    updated_at: datetime


class FeederStatus(BaseModel):
    device_id: str
    name: str
    model: str | None
    online: bool | None
    food_low: bool | None
    battery_percent: float | None
    battery_state: str | None
    # Quantities are in the feeder's native portions (1 portion = 1/12 cup).
    today_dispensed_portions: int | None
    today_feed_count: int | None
    today_eat_count: int | None
    today_eat_seconds: int | None = None
    last_feed_at: datetime | None
    last_feed_portions: int | None
    next_feed_at: datetime | None
    next_feed_portions: int | None
    # Negative means overdue by that many days.
    desiccant_days_left: float | None
    desiccant_state: str | None = None
    problems: list[str] = Field(default_factory=list)
    updated_at: datetime


class DrawerEmptied(BaseModel):
    device_id: str
    timestamp: datetime
    level_before_percent: float | None
    # Clean cycles between the previous empty and this one.
    clean_cycles: int | None = None
    days_since_previous: float | None = None


class LitterEvent(BaseModel):
    device_id: str
    timestamp: datetime
    code: str | None
    text: str
    cat_weight_lbs: float | None = None


class FeedEvent(BaseModel):
    device_id: str
    timestamp: datetime
    portions: int


class PetVisit(BaseModel):
    """A cat identified by RFID eating at a feeder."""

    device_id: str
    timestamp: datetime
    pet_id: int | None
    pet_name: str | None
    seconds: int | None
    event_type: str | None = None


class DashboardStatus(BaseModel):
    litter_boxes: list[LitterBoxStatus] = Field(default_factory=list)
    feeders: list[FeederStatus] = Field(default_factory=list)
    # Integration name -> last error message, for showing "can't reach Petlibro" etc.
    errors: dict[str, str] = Field(default_factory=dict)
    configured: dict[str, bool] = Field(default_factory=dict)

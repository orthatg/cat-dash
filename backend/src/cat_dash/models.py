"""Vendor-neutral models the frontend sees."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    litter_level_percent: float | None
    cat_weight_lbs: float | None
    cycles_since_drawer_reset: int
    sleeping: bool
    last_seen: datetime | None
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
    last_feed_at: datetime | None
    last_feed_portions: int | None
    next_feed_at: datetime | None
    next_feed_portions: int | None
    desiccant_days_left: float | None
    problems: list[str] = Field(default_factory=list)
    updated_at: datetime


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


class DashboardStatus(BaseModel):
    litter_boxes: list[LitterBoxStatus] = Field(default_factory=list)
    feeders: list[FeederStatus] = Field(default_factory=list)
    # Integration name -> last error message, for showing "can't reach Petlibro" etc.
    errors: dict[str, str] = Field(default_factory=dict)
    configured: dict[str, bool] = Field(default_factory=dict)

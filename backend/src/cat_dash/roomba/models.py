"""What the frontend sees for the Roomba. Vendor field names stay in parse.py."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScheduleEntry(BaseModel):
    weekday: int  # 0 = Monday ... 6 = Sunday (ISO-ish, Python's weekday())
    time: str  # "HH:MM", robot-local
    enabled: bool


class RoombaStatus(BaseModel):
    device_id: str  # BLID
    name: str | None
    model: str | None
    software_version: str | None
    battery_percent: int | None
    # docked / charging / cleaning / paused / returning / stuck / idle / error / unknown
    state: str
    phase: str | None  # raw vendor phase (charge, run, hmUsrDock, ...)
    cycle: str | None  # raw vendor cycle (none, quick, spot, ...)
    error_code: int
    error_text: str | None
    not_ready_code: int
    problems: list[str] = Field(default_factory=list)
    bin_present: bool | None
    bin_full: bool | None
    # Last mission. last_mission_started_at (cleanMissionStatus.mssnStrtTm) is reliable.
    # last_command_at is the robot's last received command; often null, a fallback only.
    last_mission_started_at: datetime | None = None
    last_command: str | None
    last_command_at: datetime | None
    last_command_initiator: str | None
    last_mission_minutes: int | None
    last_mission_sqft: int | None
    mission_number: int | None
    missions_total: int | None
    missions_ok: int | None
    missions_cancelled: int | None
    missions_failed: int | None
    next_scheduled_at: datetime | None
    schedule: list[ScheduleEntry] = Field(default_factory=list)
    wifi_rssi: int | None
    wifi_snr: int | None
    # Extras "for fun": lifetime counters (bbrun, bbchg3, bbswitch, ...) as the robot sent them.
    sensors: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime

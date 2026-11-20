"""Holds the latest status from every integration and fans changes out to listeners."""

from __future__ import annotations

import asyncio
import logging

from .models import DashboardStatus, FeederStatus, LitterBoxStatus

_LOGGER = logging.getLogger(__name__)


class Hub:
    def __init__(self) -> None:
        self._litter: dict[str, LitterBoxStatus] = {}
        self._feeders: dict[str, FeederStatus] = {}
        self._errors: dict[str, str] = {}
        self._configured: dict[str, bool] = {}
        self._listeners: set[asyncio.Queue[DashboardStatus]] = set()

    def snapshot(self) -> DashboardStatus:
        return DashboardStatus(
            litter_boxes=list(self._litter.values()),
            feeders=list(self._feeders.values()),
            errors=dict(self._errors),
            configured=dict(self._configured),
        )

    def litter_box(self, device_id: str) -> LitterBoxStatus | None:
        return self._litter.get(device_id)

    def feeder(self, device_id: str) -> FeederStatus | None:
        return self._feeders.get(device_id)

    # Updates are synchronous so they can be called from pylitterbot's (sync) callbacks.
    def set_configured(self, integration: str, configured: bool) -> None:
        self._configured[integration] = configured

    def update_litter_box(self, status: LitterBoxStatus) -> None:
        self._litter[status.device_id] = status
        self._notify()

    def update_feeder(self, status: FeederStatus) -> None:
        self._feeders[status.device_id] = status
        self._notify()

    def set_error(self, integration: str, message: str | None) -> None:
        changed = self._errors.get(integration) != message
        if message is None:
            self._errors.pop(integration, None)
        else:
            self._errors[integration] = message
        if changed:
            self._notify()

    def subscribe(self) -> asyncio.Queue[DashboardStatus]:
        queue: asyncio.Queue[DashboardStatus] = asyncio.Queue(maxsize=10)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[DashboardStatus]) -> None:
        self._listeners.discard(queue)

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for queue in list(self._listeners):
            if queue.full():
                # Slow consumer: drop the oldest; only the latest state matters.
                queue.get_nowait()
            queue.put_nowait(snapshot)

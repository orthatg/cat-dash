"""FastAPI app: current status, history for charts, and a live SSE stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .adapters.litterrobot import LitterRobotAdapter, TokenFile
from .adapters.petlibro import PetlibroAdapter
from .cats import attribute
from .config import Settings
from .hub import Hub
from .insights import meal_timing, merge_visits, visit_gaps
from .models import DashboardStatus, DrawerEmptied, FeedEvent, LitterEvent, PetVisit
from .petlibro import PetlibroClient
from .store import Store

_LOGGER = logging.getLogger(__name__)
CLEAN_CYCLE_COMPLETE = "CCC"


def build_adapters(settings: Settings, hub: Hub, store: Store) -> list:
    adapters: list = []
    lr_password = settings.litterrobot_password_value()
    pl_password = settings.petlibro_password_value()
    hub.set_configured("litterrobot", bool(settings.litterrobot_username and lr_password))
    hub.set_configured("petlibro", bool(settings.petlibro_email and pl_password))
    if settings.litterrobot_username and lr_password:
        adapters.append(
            LitterRobotAdapter(
                hub,
                store,
                settings.litterrobot_username,
                lr_password,
                TokenFile(settings.litterrobot_token_path),
                history_poll_seconds=settings.litterrobot_history_poll_seconds,
            )
        )
    else:
        _LOGGER.warning(
            "Litter-Robot not configured; set CATDASH_LITTERROBOT_USERNAME in .env and run "
            "`uv run cat-dash-secrets set litterrobot`"
        )
    if settings.petlibro_email and pl_password:
        client = PetlibroClient(
            settings.petlibro_email,
            pl_password,
            region=settings.petlibro_region,
            timezone=settings.timezone,
        )
        adapters.append(
            PetlibroAdapter(
                hub,
                store,
                client,
                timezone=settings.timezone,
                poll_seconds=settings.petlibro_poll_seconds,
                token_path=settings.petlibro_token_path,
            )
        )
    else:
        _LOGGER.warning(
            "Petlibro not configured; set CATDASH_PETLIBRO_EMAIL in .env and run "
            "`uv run cat-dash-secrets set petlibro`"
        )
    return adapters


def create_app(
    settings: Settings | None = None,
    *,
    store: Store | None = None,
    hub: Hub | None = None,
    adapters: list | None = None,
) -> FastAPI:
    settings = settings or Settings()
    hub = hub or Hub()
    store = store or Store(settings.db_path)
    tz = ZoneInfo(settings.timezone)
    if adapters is None:
        adapters = build_adapters(settings, hub, store)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for adapter in adapters:
            await adapter.start()
        try:
            yield
        finally:
            for adapter in adapters:
                with contextlib.suppress(Exception):
                    await adapter.stop()
            store.close()

    app = FastAPI(title="Cat Dash", lifespan=lifespan)
    app.state.hub, app.state.store, app.state.adapters = hub, store, adapters
    # Local frontend dev servers / Electron. Tighten when deployed.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|app://.*|file://.*)$",
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    def since(days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=days)

    def local_day(ts: datetime) -> str:
        return ts.astimezone(tz).date().isoformat()

    @app.get("/api/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/api/status", response_model=DashboardStatus)
    async def status() -> DashboardStatus:
        return hub.snapshot()

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Server-sent events: a full DashboardStatus on connect and on every change."""

        async def events() -> AsyncIterator[str]:
            queue = hub.subscribe()
            try:
                yield f"data: {hub.snapshot().model_dump_json()}\n\n"
                while not await request.is_disconnected():
                    try:
                        snapshot = await asyncio.wait_for(queue.get(), timeout=25)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"data: {snapshot.model_dump_json()}\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(events(), media_type="text/event-stream")

    # --- litter box history ---
    def require_litter_box(device_id: str) -> None:
        if hub.litter_box(device_id) is None:
            raise HTTPException(404, "Unknown litter box")

    @app.get("/api/litterbox/{device_id}/events", response_model=list[LitterEvent])
    async def litter_events(device_id: str, days: int = Query(7, ge=1, le=365)):
        return await store.litter_events(device_id, since(days))

    @app.get("/api/litterbox/{device_id}/daily")
    async def litter_daily(device_id: str, days: int = Query(30, ge=1, le=365)) -> list[dict]:
        """Clean cycles per local day, plus the median cat weight that day.

        Median, not last: a box can log occasional readings far off the usual weight
        (e.g. ~15 lb among ~5.4 lb), which would otherwise become the day's value.
        """
        cycles: dict[str, int] = defaultdict(int)
        weights: dict[str, list[float]] = defaultdict(list)
        for event in await store.litter_events(device_id, since(days)):
            day = local_day(event.timestamp)
            if event.code == CLEAN_CYCLE_COMPLETE:
                cycles[day] += 1
            if event.cat_weight_lbs is not None:
                weights[day].append(event.cat_weight_lbs)
        return [
            {
                "date": day,
                "clean_cycles": cycles.get(day, 0),
                "cat_weight_lbs": round(median(weights[day]), 2) if weights.get(day) else None,
                "weight_readings": len(weights.get(day, [])),
            }
            for day in sorted(set(cycles) | set(weights))
        ]

    @app.get("/api/litterbox/{device_id}/cats/daily")
    async def litter_cats_daily(device_id: str, days: int = Query(30, ge=1, le=365)) -> list[dict]:
        """Per cat per local day: litter box visits (weight readings) and median weight.
        Readings are matched to Whisker pet profiles by weight (see cat_dash.cats)."""
        box = hub.litter_box(device_id)
        cats = box.cats if box else []
        readings: dict[tuple[str, str], list[float]] = defaultdict(list)
        for event in await store.litter_events(device_id, since(days)):
            if event.cat_weight_lbs is None:
                continue
            name = attribute(event.cat_weight_lbs, cats) or "Unknown"
            readings[(local_day(event.timestamp), name)].append(event.cat_weight_lbs)
        return [
            {
                "date": day,
                "cat": name,
                "visits": len(values),
                "weight_lbs": round(median(values), 2),
            }
            for (day, name), values in sorted(readings.items())
        ]

    @app.get("/api/litterbox/{device_id}/levels")
    async def litter_levels(device_id: str, days: int = Query(7, ge=1, le=365)) -> list[dict]:
        """Waste drawer and litter level over time."""
        return await store.litter_snapshots(device_id, since(days))

    @app.get("/api/litterbox/{device_id}/drawer")
    async def litter_drawer(device_id: str, days: int = Query(90, ge=1, le=3650)) -> dict:
        """Waste drawer tracking: when it was emptied, how full it got, and the level
        after each clean cycle. Empties are inferred from the level falling to ~0."""
        empties = await store.drawer_empties(device_id)
        history: list[DrawerEmptied] = []
        previous: datetime | None = None
        for ts, level_before in empties:
            history.append(
                DrawerEmptied(
                    device_id=device_id,
                    timestamp=ts,
                    level_before_percent=level_before,
                    clean_cycles=(
                        await store.count_litter_events(
                            device_id, CLEAN_CYCLE_COMPLETE, after=previous, before=ts
                        )
                        if previous
                        else None
                    ),
                    days_since_previous=(
                        round((ts - previous).total_seconds() / 86400, 2) if previous else None
                    ),
                )
            )
            previous = ts
        intervals = [e.days_since_previous for e in history if e.days_since_previous]
        cycles = [e.clean_cycles for e in history if e.clean_cycles is not None]
        cutoff = since(days)
        box = hub.litter_box(device_id)
        return {
            "current_percent": box.waste_drawer_percent if box else None,
            "current_state": box.waste_drawer_state if box else None,
            "last_emptied_at": previous,
            "days_since_emptied": (
                round((datetime.now(UTC) - previous).total_seconds() / 86400, 2)
                if previous
                else None
            ),
            "cycles_since_emptied": box.cycles_since_emptied if box else None,
            "fill_rate_per_day": box.drawer_fill_rate_per_day if box else None,
            "usual_empty_percent": box.drawer_usual_empty_percent if box else None,
            "needs_emptying_at": box.drawer_needs_emptying_at if box else None,
            "full_at": box.drawer_full_at if box else None,
            "average_days_between_empties": (
                round(sum(intervals) / len(intervals), 2) if intervals else None
            ),
            "average_cycles_between_empties": (
                round(sum(cycles) / len(cycles), 1) if cycles else None
            ),
            "emptied": [e for e in history if e.timestamp >= cutoff],
            "levels": [
                {"timestamp": ts, "percent": pct}
                for ts, pct in await store.drawer_levels(device_id, cutoff)
            ],
        }

    @app.get("/api/litterbox/{device_id}/insight")
    async def litter_insight(device_id: str) -> dict:
        require_litter_box(device_id)
        adapter = next((a for a in adapters if isinstance(a, LitterRobotAdapter)), None)
        insight = adapter.insight(device_id) if adapter else None
        if insight is None:
            raise HTTPException(404, "No insight loaded yet")
        return {
            "total_cycles": insight.total_cycles,
            "average_cycles": insight.average_cycles,
            "cycle_history": [
                {"date": day.isoformat(), "cycles": count} for day, count in insight.cycle_history
            ],
        }

    # --- feeder history ---
    @app.get("/api/feeder/{device_id}/events", response_model=list[FeedEvent])
    async def feeder_events(device_id: str, days: int = Query(7, ge=1, le=365)):
        return await store.feed_events(device_id, since(days))

    @app.get("/api/feeder/{device_id}/daily")
    async def feeder_daily(device_id: str, days: int = Query(30, ge=1, le=365)) -> list[dict]:
        """Portions dispensed and number of feeds per local day."""
        portions: dict[str, int] = defaultdict(int)
        feeds: dict[str, int] = defaultdict(int)
        for event in await store.feed_events(device_id, since(days)):
            day = local_day(event.timestamp)
            portions[day] += event.portions
            feeds[day] += 1
        return [
            {"date": day, "portions": portions[day], "feeds": feeds[day]} for day in sorted(feeds)
        ]

    @app.get("/api/feeder/{device_id}/visits", response_model=list[PetVisit])
    async def feeder_visits(device_id: str, days: int = Query(7, ge=1, le=365)):
        """Each RFID-identified eating visit (cat, time, seconds)."""
        return await store.pet_visits(device_id, since(days))

    @app.get("/api/insights")
    async def insights(days: int = Query(30, ge=7, le=365)) -> dict:
        """Per cat: time between litter box visits, and litter visits relative to meals.
        Cats are matched across devices by name (Whisker pet profile = Petlibro RFID pet)."""
        cutoff = since(days)
        litter: dict[str, list[datetime]] = defaultdict(list)
        for box in hub.snapshot().litter_boxes:
            for event in await store.litter_events(box.device_id, cutoff):
                if event.cat_weight_lbs is None:
                    continue
                if name := attribute(event.cat_weight_lbs, box.cats):
                    litter[name.casefold()].append(event.timestamp)
        meals: dict[str, list[datetime]] = defaultdict(list)
        names: dict[str, str] = {}
        for feeder in hub.snapshot().feeders:
            for visit in await store.pet_visits(feeder.device_id, cutoff):
                if visit.pet_name:
                    meals[visit.pet_name.casefold()].append(visit.timestamp)
                    names.setdefault(visit.pet_name.casefold(), visit.pet_name)
        for box in hub.snapshot().litter_boxes:
            for cat in box.cats:
                names.setdefault(cat.name.casefold(), cat.name)
        cats = []
        for key in sorted(set(litter) | set(meals)):
            visits = merge_visits(litter.get(key, []))
            cats.append(
                {
                    "name": names.get(key, key),
                    "litter_gaps": visit_gaps(visits),
                    "meal_timing": meal_timing(visits, meals.get(key, [])),
                }
            )
        return {"days": days, "cats": cats}

    @app.get("/api/feeder/{device_id}/visits/daily")
    async def feeder_visits_daily(
        device_id: str, days: int = Query(30, ge=1, le=365)
    ) -> list[dict]:
        """Per cat per local day: number of visits and total seconds eating."""
        totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
        for visit in await store.pet_visits(device_id, since(days)):
            key = (local_day(visit.timestamp), visit.pet_name or "Unknown")
            totals[key][0] += 1
            totals[key][1] += visit.seconds or 0
        return [
            {"date": day, "pet_name": pet, "visits": v[0], "eating_seconds": v[1]}
            for (day, pet), v in sorted(totals.items())
        ]

    @app.middleware("http")
    async def revalidate_dashboard(request: Request, call_next):
        # Dashboard files change without a build step: make browsers re-check them
        # (cheap 304s via ETag) instead of reusing a stale copy.
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    # The dashboard (static files, no build step). Mounted last so /api/* wins.
    if settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    else:
        _LOGGER.warning("Dashboard folder not found: %s", settings.frontend_dir)

    return app

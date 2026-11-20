# Cat Dash

A cat module for a larger home integration dashboard. Cat Dash pulls data from
**Litter-Robot** and **Petlibro** devices and shows charts and current status for
the litter box and the automatic feeder.

## Goals

- Current status at a glance: litter box (waste drawer level, last cycle, errors) and feeder (food level, last/next feeding).
- Historical charts: litter box usage over time, feeding amounts and schedule.
- Embeddable as a module in a larger home dashboard.

## Planned stack

- **Backend:** Python (device API clients, polling, data storage, HTTP API)
- **Frontend:** JavaScript web app (Electron wrapper is a possibility)

## Layout

- `backend/`: Python service (see [backend/README.md](backend/README.md))
- `frontend/`: the dashboard (plain HTML/CSS/JS modules, no build step), served by the backend at `/`
- `docs/integration-plan.md`: how each device's data is accessed, and what's still unverified

## Configuration

Account credentials for Litter-Robot and Petlibro must never be committed.
Login emails go in `backend/.env` (git-ignored; template in `backend/.env.example`);
passwords go in the macOS Keychain via `uv run cat-dash-secrets set <integration>`.

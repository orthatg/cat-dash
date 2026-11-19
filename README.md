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

Nothing is decided yet beyond this; the structure will be filled in as the project develops.

## Configuration

Account credentials for Litter-Robot and Petlibro must never be committed.
Keep them in a local `.env` file (git-ignored).

# Cat Dash backend

Python service that talks to the Litter-Robot 4 and the Petlibro One RFID feeder,
keeps history in SQLite, and serves JSON plus a live event stream to the frontend.

## Setup

```bash
brew install uv           # once
cd backend
uv sync                   # creates .venv with Python 3.12 + deps
cp .env.example .env      # then fill in the two login emails
uv run cat-dash-secrets set litterrobot   # password -> macOS Keychain (hidden prompt)
uv run cat-dash-secrets set petlibro
uv run cat-dash-secrets check             # confirms both are found
```

Passwords live in the Keychain (Keychain Access, name `cat-dash`), never in `.env`
or git. macOS may ask once to let Python read them; choose **Always Allow**.

## First run: probe the real devices

The device field names come from reading other projects, not from your devices. Run
the probes first and compare what they print with the vendor apps:

```bash
uv run python scripts/probe_petlibro.py
uv run python scripts/probe_litterrobot.py 300   # listens 5 min for live pushes
```

Redacted raw dumps land in `data/probe/` (git-ignored).

## Run

```bash
uv run cat-dash           # dashboard at http://127.0.0.1:8000, API docs at /docs
uv run pytest             # tests (no network)
```

## API

| Endpoint | What |
|---|---|
| `GET /api/status` | Current status of every litter box and feeder, plus integration errors |
| `GET /api/stream` | Server-sent events: full status on connect and on every change |
| `GET /api/litterbox/{id}/events?days=7` | Activity log (clean cycles, cat detected, weights...) |
| `GET /api/litterbox/{id}/daily?days=30` | Clean cycles per day and cat weight |
| `GET /api/litterbox/{id}/cats/daily?days=30` | Per cat per day: litter box visits and median weight (readings matched to Whisker pet profiles) |
| `GET /api/litterbox/{id}/levels?days=7` | Waste drawer % and litter level % over time |
| `GET /api/litterbox/{id}/drawer?days=90` | Waste drawer: last emptied, cycles since, every empty (inferred), averages, level history |
| `GET /api/litterbox/{id}/insight` | Whisker's own 30-day cycle summary |
| `GET /api/feeder/{id}/events?days=7` | Each feed (portions; 1 portion = 1/12 cup) |
| `GET /api/feeder/{id}/daily?days=30` | Portions and feeds per day |
| `GET /api/feeder/{id}/visits?days=7` | Each RFID-identified cat visit (cat, time, seconds eating) |
| `GET /api/feeder/{id}/visits/daily?days=30` | Visits and eating seconds per cat per day |

## How data arrives

- **Litter-Robot 4:** pushed. `pylitterbot` holds a websocket subscription and status
  updates arrive within seconds. Activity history is pulled every 15 min, and a full
  refresh runs every 5 min in case the websocket goes quiet.
- **Petlibro:** polled every 60 s (no push channel exists).

Both APIs are unofficial and can break without notice. Vendor code lives in
`src/cat_dash/adapters/` and `src/cat_dash/petlibro/`; everything else uses the
vendor-neutral models in `models.py`.

## Local files (git-ignored)

`data/cat_dash.sqlite3` (history), `data/litterrobot_tokens.json` and
`data/petlibro_token.txt` (login tokens, mode 600, so restarts don't resend passwords).

# Gridlytics

A Chrome extension that overlays fantasy football analytics directly on your Sleeper or ESPN
league page: standings, power rankings, playoff odds, roster efficiency, weekly recaps, player
rankings, start/sit recommendations, waiver suggestions, and a trade analyzer.

## What it does

- Connects to a real Sleeper or ESPN league (no separate account, reuses your existing session)
- Runs an in-house opportunity-based player projection model on real NFL play-by-play, target
  share, and snap share data (via [nflverse](https://github.com/nflverse)), blended with each
  platform's own projections
- Optimizes a lineup against real slot eligibility (FLEX/SUPER_FLEX, custom roster shapes) and
  explains each recommendation with real signals (usage trend, matchup, injury status, sample
  size) instead of a black-box score
- Analyzes proposed trades by simulating each team's optimal lineup before and after, isolating
  the trade's own rest-of-season value from unrelated lineup-management decisions

## Architecture

**Backend** (`backend/`): FastAPI + async SQLAlchemy + PostgreSQL, deployed on Railway. Both
platforms sync into one shared schema (`League`/`Team`/`RosterSlot`/`Player`) so every analytics
function is platform-agnostic above the sync layer. Schema changes are managed with Alembic.

**Extension** (`extension/`): Manifest V3 Chrome extension. A content script injects a React
overlay on league pages; a background service worker handles all network requests (extensions
aren't subject to CORS the way a page is, given declared `host_permissions`). Bundled with
esbuild, no framework beyond React itself.

## Stack

- Backend: FastAPI, SQLAlchemy (async), PostgreSQL, Alembic, slowapi (rate limiting), pytest
- Extension: React, TypeScript, esbuild, Vitest
- Data: [nflverse](https://github.com/nflverse) public CSV releases (play-by-play, weekly stats,
  snap counts, schedules), fetched directly via httpx/pandas

## Running locally

**Backend**

```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
docker compose -f ../docker-compose.yml up -d   # local Postgres on :5433
python -m alembic upgrade head
uvicorn app.main:app --reload --port 8001
```

Copy `.env.example` to `.env` if you need to override the default local `DATABASE_URL`.

**Extension**

```
cd extension
npm install
npm run build:dev   # points the extension at http://127.0.0.1:8001
```

Then load `extension/` as an unpacked extension in `chrome://extensions` (developer mode on).

## Testing

```
cd backend && pytest
cd extension && npm test
```

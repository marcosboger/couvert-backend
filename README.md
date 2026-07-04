# couvert-backend

Backend for [couvert-app](../couvert-app): FastAPI API serving the app + offline jobs feeding Cosmos DB. Roadmap: `../LONGTERM.md`; current milestone: `../SHORTTERM.md`; frontend contract: `../FRONT.md`.

## Layout

- `core/` — shared: settings, Pydantic wire models, Cosmos client + repositories
- `api/` — FastAPI app: Firebase token verification, `/user/*` routes
- `jobs/` — Typer CLI scripts: DB init, fixture seeding (later: Excel + Google Maps ingestion)

## Setup

1. Install deps: `uv sync` (or `python -m uv sync`)
2. `cp .env.example .env` and fill in Cosmos endpoint/key + Firebase service-account path
   (Cosmos: NoSQL API account with the free-tier discount; Firebase: service account of the
   project the app signs into — currently `template-react-native-b8abd`).
3. One-time DB bootstrap: `uv run python -m jobs.seed_fixtures init-db`
4. Seed restaurants: `uv run python -m jobs.seed_fixtures seed`

## Run

```bash
uv run uvicorn api.main:app --port 5000 --reload
```

Port **5000 is mandatory** — the app's `BASE_URL` is hardcoded to `http://127.0.0.1:5000`
(`couvert-app/src/diplomat/httpClient.ts`). Android emulator: `adb reverse tcp:5000 tcp:5000`.

Interactive docs at http://127.0.0.1:5000/docs.

## Test & lint

```bash
uv run pytest
uv run ruff check .
```

Tests fake auth and the repository — no Cosmos or Firebase credentials needed.

## Contract notes (do not break)

- `GET /user/me` **must 404** when the user document doesn't exist — the app's `AuthContext`
  maps 404 → account-setup screen. Never return an empty 200.
- All responses are snake_case wire format; `age`, `phone`, `zip_code` are **strings**.
- `POST /user/login` is called after every Firebase sign-in and upserts-on-login.

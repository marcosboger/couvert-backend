# couvert-backend

Backend for [couvert-app](../couvert-app): FastAPI API serving the app + offline jobs feeding Cosmos DB. Roadmap: `../LONGTERM.md`; current milestone: `../SHORTTERM.md`; frontend contract: `../FRONT.md`.

**Deployed and public:**

```
https://couvert-api.agreeabledesert-5db4d03a.eastus.azurecontainerapps.io
```

Azure Container Apps, East US. Deploy procedure, operating commands and gotchas: **`DEPLOY.md`**. Frontend integration guide: **`../couvert-app/API_HANDOFF.md`**.

## Layout

- `core/` — shared: settings, Pydantic wire models, Cosmos client + repositories, caching, canonical cuisine vocabulary
- `api/` — FastAPI app: Firebase token verification, `/user/*` routes, and the public `/couvert/*` content routes
- `jobs/` — Typer CLI scripts: DB init, fixture seeding, Excel ingestion, Google Maps resolution, restaurant seeding. **Excluded from the container image** so the billable Places key never ships

## Setup

1. Install deps: `uv sync` (or `python -m uv sync`)
2. `cp .env.example .env` and fill in Cosmos endpoint/key + Firebase service-account path
   (Cosmos: NoSQL API account `db-food-app`, database `CouvertApp`, free-tier discount
   confirmed applied; Firebase: service account of the project the app signs into —
   **`couvert-app`**, migrated 2026-07-04).
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

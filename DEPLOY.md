# Deploying the Couvert API

Target: **Azure Container Apps, consumption plan** — HTTPS at the ingress, same region as
Cosmos so there's no cross-cloud latency, and about **$4.30/month** with one replica always
warm (see §7 for the arithmetic). The image lives in a **private GHCR package** rather than
ACR, which has no free tier and would add $5/month — at the cost of a transfer quota worth
watching (§2).

Everything below is a one-time setup except §4, which is the repeat deploy.

> **Verified locally** (2026-07-26, Docker 27.5.1 in WSL Ubuntu 24.04). The image builds,
> runs, and serves every content endpoint against live Cosmos: 250 MB, non-root uid 10001,
> `/app` contains only `.venv`, `api` and `core` — no `.env`, no service-account file, no
> `jobs/`, no `data/`, no `tests/`, and no `uv` in the runtime layer. Health came up in 3s
> and the first browse request was already warm. What is **not** verified is Azure itself:
> the `az` commands below have never been run.

## 1. What the container needs

| Setting | Value | Notes |
|---|---|---|
| `COSMOS_ENDPOINT` | `https://db-food-app.documents.azure.com:443/` | plain env var |
| `COSMOS_KEY` | account key | **secret** |
| `COSMOS_DATABASE` | `CouvertApp` | |
| `FIREBASE_CREDENTIALS_JSON` | the whole service-account JSON | **secret** — a container has no file to mount, so this replaces `FIREBASE_CREDENTIALS_PATH` |
| `CORS_ORIGIN_REGEX` | regex of allowed browser origins | defaults to localhost only, which blocks a deployed web build |
| `CONTENT_CACHE_SECONDS` | `600` | in-memory catalog TTL and the client `max-age` |

`GOOGLE_MAPS_API_KEY` is deliberately **not** deployed. Only the offline jobs call Google,
and `jobs/` is excluded from the image, so a compromised container cannot spend money.

## 2. Push the image to GHCR (private)

Needs a classic Personal Access Token with `write:packages` to push and `read:packages`
for Container Apps to pull. Build locally through WSL (see §8), then:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
docker build -t ghcr.io/<github-user>/couvert-api:v1 .
docker push ghcr.io/<github-user>/couvert-api:v1
```

Use a real tag per deploy — a git short SHA — never `latest`, which causes caching
confusion on revision updates.

> **Watch the transfer quota.** A private GHCR package on the GitHub Free plan includes
> **500 MB storage and 1 GB/month data transfer**, and pulls from Azure count against the
> transfer. At a 250 MB image that's roughly **four pulls a month**, and when the quota is
> exhausted with no payment method on file GitHub **blocks** further usage.
>
> Container Apps pulls on every new revision and on any replica reschedule — not on a
> plain restart, since the image is cached on the node. So a stable deployment sits well
> inside the quota, while a week of heavy iteration can blow through it.
>
> **The symptom is the app failing to start with an image-pull error**, which is easy to
> misread as a broken build. If it happens, the escape hatches are quick: flip the package
> to public in the repo's Packages settings (free and unlimited, but publishes the source),
> switch to a Docker Hub private repo (free, no bandwidth quota), or pay $0.1666/day for
> ACR Basic. Check usage under GitHub → Settings → Billing → Packages.

## 3. One-time Azure setup

```bash
RG=couvert-rg
LOC=brazilsouth          # match the Cosmos account's region
ENV=couvert-env
APP=couvert-api

az group create -n $RG -l $LOC
az containerapp env create -n $ENV -g $RG -l $LOC
```

## 4. Create the app

```bash
az containerapp create \
  -n $APP -g $RG --environment $ENV \
  --image ghcr.io/<github-user>/couvert-api:v1 \
  --registry-server ghcr.io \
  --registry-username <github-user> --registry-password <ghcr-token> \
  --target-port 5000 --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --cpu 0.25 --memory 0.5Gi \
  --secrets cosmos-key="<COSMOS_KEY>" firebase-json="$(cat firebase-service-account.json)" \
  --env-vars \
     COSMOS_ENDPOINT="https://db-food-app.documents.azure.com:443/" \
     COSMOS_DATABASE="CouvertApp" \
     CONTENT_CACHE_SECONDS="600" \
     COSMOS_KEY=secretref:cosmos-key \
     FIREBASE_CREDENTIALS_JSON=secretref:firebase-json
```

Why these numbers:

- **`--min-replicas 1`** — no cold starts, which is the point. Scale-to-zero would be free
  but makes some user wait several seconds for a container to boot.
- **`--max-replicas 2`** — when a revision scales *above* its minimum, **every** replica
  bills at the active rate, not just the extra one. Keep the ceiling low.
- **`--cpu 0.25 --memory 0.5Gi`** — the smallest valid combination, and measured to be
  ample: the container idles at 79 MB and peaks at 85 MB of 512 MB, and served 200 requests
  capped at 0.25 CPU without an OOM kill. Doubling to 0.5/1.0Gi would roughly double the
  bill for capacity we don't use.

Then read the URL and check it:

```bash
az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv
curl https://<fqdn>/health
curl https://<fqdn>/couvert/cuisines
```

## 5. Redeploying

```bash
TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/<github-user>/couvert-api:$TAG .
docker push ghcr.io/<github-user>/couvert-api:$TAG
az containerapp update -n $APP -g $RG --image ghcr.io/<github-user>/couvert-api:$TAG
```

Every redeploy is a fresh 250 MB pull against the GHCR transfer quota (§2), so delete old
tags from the package page occasionally to stay inside the 500 MB storage allowance too.

Worth automating in a `deploy.yml` workflow on a push to `main` once the first manual
deploy works — build and push in Actions, then `az containerapp update` with an Azure
service principal or OIDC federated credentials.

Each new revision restarts the container, so it warms its cache again on startup; the first
request after a deploy is served warm rather than paying for 14 round trips to Cosmos.

## 6. After the first deploy

- **Point the app at it.** `BASE_URL` is hardcoded in
  `couvert-app/src/diplomat/httpClient.ts:11`; move it into `src/config/` (base, staging
  and prod files already exist). Then Android's `usesCleartextTraffic` can go, since the
  ingress is HTTPS.
- **Set `CORS_ORIGIN_REGEX`** to the real web origins, or Expo web gets blocked. Native
  apps send no `Origin` header and don't care.
- **Health probes**: point liveness and readiness at `/health`. Probe requests aren't
  billable and don't disqualify a replica from idle rates.
- **Confirm the Cosmos free-tier discount** is applied on `db-food-app`. If it isn't, the
  1000 RU/s bills roughly $58/month — an order of magnitude more than the hosting, and
  still an open item in `NEXTSTEPS.md`.
- **Watch log volume once.** Log Analytics ingestion is $4.60/GB beyond the free
  allowance. An idle API writes a few MB a month, so this should be nothing — but confirm
  it in the portal rather than assuming, since it's the one line item that can grow quietly.

## 7. What it costs

Verified against the Azure Retail Prices API for `brazilsouth` in USD, 2026-07-26. A month
is 730 hours = 2,628,000 seconds. Free grant per subscription per month: 180,000
vCPU-seconds, 360,000 GiB-seconds, 2M requests.

At `--cpu 0.25 --memory 0.5Gi --min-replicas 1`, running continuously:

| | Seconds billed | Rate | Cost |
|---|---|---|---|
| vCPU (idle) | 657,000 − 180,000 free = 477,000 | $0.000003 | $1.43 |
| Memory | 1,314,000 − 360,000 free = 954,000 | $0.000003 | $2.86 |
| Requests | under the 2M grant | $0.40/M | $0 |
| Registry | Docker Hub free private repo | — | $0 |
| **Total** | | | **≈ $4.29/month** |

Two things move that number:

- **Idle versus active.** A replica bills at the reduced idle rate only while it is scaled
  at its minimum, processing no HTTP requests, using under 0.01 vCPU and receiving under
  1,000 bytes/second. Real traffic bills at the active vCPU rate, which is 8× higher.
  Worst case — never idle for a whole month — is **$14.31**. Dev and tester traffic sits
  near the floor.
- **Allocation.** Memory is the larger half of the idle bill, because idle vCPU and memory
  bill at the same per-second rate while the 2:1 ratio allocates twice as many
  GiB-seconds. The old 0.5/1.0Gi configuration would have been **$10.20/month** idle and
  $34 active, for headroom the measurements say we don't need.

## 8. Local check before pushing to Azure

Docker via WSL works on this machine, so the image can be verified end to end without
touching Azure:

```bash
wsl -d Ubuntu-24.04
cd /mnt/c/Users/Dell/Desktop/couvert-new/couvert-backend
docker build -t couvert-api:test .
docker run --rm -p 5001:5000 --env-file .env couvert-api:test
curl -s localhost:5001/couvert/cuisines | head -c 200
```

To exercise the deployment credential path specifically — the one thing local development
never uses, because locally you have a file:

```bash
docker run --rm -e FIREBASE_CREDENTIALS_JSON="$(cat firebase-service-account.json)" \
  --entrypoint python couvert-api:test -c \
  'from api.auth import _ensure_firebase; from core.config import Settings; import firebase_admin;
   _ensure_firebase(Settings()); print(firebase_admin.get_app().project_id)'
```

That prints `couvert-app` when the secret is wired correctly.

## 9. Known rough edges

- `openpyxl` and `typer` are declared as main dependencies but are only used by `jobs/`,
  so the runtime image installs them for nothing. Moving them to an optional dependency
  group would slim the image; harmless otherwise.
- The in-memory cache is per replica, so if it ever scales to 2 each replica keeps its own
  copy and warms independently. That's correct for a read-only catalog, just worth knowing
  when reading RU metrics.
- Cosmos is reached with an account key. Managed identity plus Cosmos RBAC would be
  better; it needs role assignments and a code change to `DefaultAzureCredential`.
- `firebase_admin.initialize_app()` succeeds even with no credentials at all and only
  fails at the first token verification. Startup therefore logs an explicit warning when
  neither `FIREBASE_CREDENTIALS_JSON` nor `FIREBASE_CREDENTIALS_PATH` is set — **check the
  container log after the first deploy**, because public content will serve happily while
  every `/user/*` route is broken.

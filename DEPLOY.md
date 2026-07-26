# Deploying the Couvert API

Target: **Azure Container Apps, consumption plan** — free monthly grant, scales to zero,
HTTPS at the ingress, same region as Cosmos so there's no cross-cloud latency.

Everything below is a one-time setup except §4, which is the repeat deploy.

> **Not yet verified by a real build.** Docker isn't installed on the machine where the
> Dockerfile was written, so `docker build` has never run against it. Expect to fix a
> line or two on the first attempt. CI (`.github/workflows/ci.yml`) builds the image on
> every push, so the first push will tell you.

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

## 2. One-time Azure setup

```bash
RG=couvert-rg
LOC=brazilsouth          # match the Cosmos account's region
ACR=couvertacr           # must be globally unique
ENV=couvert-env
APP=couvert-api

az group create -n $RG -l $LOC
az acr create -n $ACR -g $RG --sku Basic --admin-enabled true
az containerapp env create -n $ENV -g $RG -l $LOC
```

## 3. Build, push, create the app

```bash
# Build in the cloud — no local Docker needed.
az acr build -r $ACR -t couvert-api:v1 .

az containerapp create \
  -n $APP -g $RG --environment $ENV \
  --image $ACR.azurecr.io/couvert-api:v1 \
  --registry-server $ACR.azurecr.io \
  --target-port 5000 --ingress external \
  --min-replicas 0 --max-replicas 3 \
  --cpu 0.5 --memory 1.0Gi \
  --secrets cosmos-key="<COSMOS_KEY>" firebase-json="$(cat firebase-service-account.json)" \
  --env-vars \
     COSMOS_ENDPOINT="https://db-food-app.documents.azure.com:443/" \
     COSMOS_DATABASE="CouvertApp" \
     CONTENT_CACHE_SECONDS="600" \
     COSMOS_KEY=secretref:cosmos-key \
     FIREBASE_CREDENTIALS_JSON=secretref:firebase-json
```

Then read the URL and check it:

```bash
az containerapp show -n $APP -g $RG --query properties.configuration.ingress.fqdn -o tsv
curl https://<fqdn>/health
curl https://<fqdn>/couvert/cuisines
```

## 4. Redeploying

```bash
az acr build -r $ACR -t couvert-api:$(git rev-parse --short HEAD) .
az containerapp update -n $APP -g $RG \
  --image $ACR.azurecr.io/couvert-api:$(git rev-parse --short HEAD)
```

Worth automating in a `deploy.yml` workflow on a push to `main` once the first manual
deploy works — use an Azure service principal or OIDC federated credentials, not the ACR
admin password.

## 5. After the first deploy

- **Point the app at it.** `BASE_URL` is hardcoded in
  `couvert-app/src/diplomat/httpClient.ts:11`; move it into `src/config/` (base, staging
  and prod files already exist). Then Android's `usesCleartextTraffic` can go, since the
  ingress is HTTPS.
- **Set `CORS_ORIGIN_REGEX`** to the real web origins, or Expo web gets blocked. Native
  apps send no `Origin` header and don't care.
- **Health probes**: point liveness and readiness at `/health`.
- **Cold starts are visible.** With `--min-replicas 0`, the first request after idle pays
  container start plus a cache warm — several seconds, noticeable on a phone. The app
  warms the catalog cache in the background on startup, which helps but doesn't remove it.
  `--min-replicas 1` fixes it and gives up the scale-to-zero saving; fine to accept for
  dev and testers, revisit before real users.
- **Confirm the Cosmos free-tier discount** is applied on `db-food-app`. If it isn't, the
  1000 RU/s bills roughly $58/month — still an open item in `NEXTSTEPS.md`.

## 6. Known rough edges

- `openpyxl` and `typer` are declared as main dependencies but are only used by `jobs/`,
  so the runtime image installs them for nothing. Moving them to an optional dependency
  group would slim the image; harmless otherwise.
- The in-memory cache is per replica, so with `--max-replicas 3` each replica keeps its
  own copy and warms independently. That's correct for a read-only catalog, just worth
  knowing when reading RU metrics.
- Cosmos is reached with an account key. Managed identity plus Cosmos RBAC would be
  better; it needs role assignments and a code change to `DefaultAzureCredential`.

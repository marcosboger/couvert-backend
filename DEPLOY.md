# Deploying the Couvert API

**Status: deployed and live since 2026-07-26.**

```
https://couvert-api.agreeabledesert-5db4d03a.eastus.azurecontainerapps.io
```

Azure Container Apps, consumption plan, in **East US** — the same region as the Cosmos
account, so there is no cross-region hop on the database. The image lives in a **private
GHCR package** rather than ACR, which has no free tier and would add ~$5/month, at the cost
of a transfer quota worth watching (§2).

Everything below is a one-time setup except §5, which is the repeat deploy.

## 0. What is actually deployed

| | |
|---|---|
| Resource group | `couvert-rg` (East US) |
| Environment | `couvert-env` — created with `--logs-destination none` |
| Container app | `couvert-api` |
| Image | `ghcr.io/marcosboger/couvert-api:a4bf0a9` |
| Digest | `sha256:1ed01f0734899754566fb6e4dd4945764d677524da0a0d77806b5f2fa86d7a89` |
| Scale | `--min-replicas 1 --max-replicas 2`, `0.25 vCPU / 0.5Gi` |
| Secrets | `cosmos-key`, `firebase-json`, `ghcrio-marcosboger` (registry password, added by the CLI) |
| Subscription | `Marcos' Personal Subscription` `77019903-50ae-4d75-892b-489a7e414419` |

Verified on first deploy: revision `couvert-api--02g19oq` Healthy with 1 replica, **17/17
endpoint checks** against the public FQDN, `Cache-Control` and `ETag` surviving the ingress
with a 0-byte `304`, a clean startup log with no credential warnings, and
`GOOGLE_MAPS_API_KEY` confirmed absent from the container's environment.

**Cosmos free tier is confirmed applied** — `az cosmosdb list` reports `FreeTier: True` on
`db-food-app` (East US, resource group `MVP_FOOD_APP`). That closes the largest open cost
risk in `LONGTERM.md` §5: the 1000 RU/s really is free, not quietly billing ~$58/month.

## 1. What the container needs

| Setting | Value | Notes |
|---|---|---|
| `COSMOS_ENDPOINT` | `https://db-food-app.documents.azure.com:443/` | plain env var |
| `COSMOS_KEY` | account key | **secret** (`secretref:cosmos-key`) |
| `COSMOS_DATABASE` | `CouvertApp` | |
| `FIREBASE_CREDENTIALS_JSON` | the whole service-account JSON, one line | **secret** — a container has no file to mount, so this replaces `FIREBASE_CREDENTIALS_PATH` |
| `CORS_ORIGIN_REGEX` | regex of allowed browser origins | **not set in the deployment**, so it falls back to localhost-only. Native apps send no `Origin` and don't care; a deployed *web* build would be blocked |
| `CONTENT_CACHE_SECONDS` | `600` | in-memory catalog TTL and the client `max-age` |

`GOOGLE_MAPS_API_KEY` is deliberately **not** deployed. Only the offline jobs call Google,
and `jobs/` is excluded from the image, so a compromised container cannot spend money.

## 2. Push the image to GHCR (private)

Needs a classic Personal Access Token with `write:packages` to push and `read:packages`
for Container Apps to pull. Build through WSL (see §8), then:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u marcosboger --password-stdin
TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/marcosboger/couvert-api:$TAG .
docker push ghcr.io/marcosboger/couvert-api:$TAG
```

Use a real tag per deploy — a git short SHA — never `latest`, which causes caching
confusion on revision updates. **Tag from a clean tree**, or the tag names a commit that
doesn't contain what's inside the image.

> **Watch the transfer quota.** A private GHCR package on the GitHub Free plan includes
> **500 MB storage and 1 GB/month data transfer**, and pulls from Azure count against the
> transfer. At a 250 MB image that's roughly **four pulls a month**, and when the quota is
> exhausted with no payment method on file GitHub **blocks** further usage. The first
> deploy spent one.
>
> Container Apps pulls on every new revision and on any replica reschedule — not on a
> plain restart, since the image is cached on the node.
>
> **The symptom is the app failing to start with an image-pull error**, which is easy to
> misread as a broken build. Escape hatches: flip the package to public in the repo's
> Packages settings (free and unlimited, but publishes the source), switch to a Docker Hub
> private repo, or pay $0.1666/day for ACR Basic. Check usage under GitHub → Settings →
> Billing → Packages.

## 3. One-time Azure setup — already done

Recorded so it can be rebuilt from scratch, not because it needs running again.

```bash
az login --tenant bc142eb8-62eb-4d3d-99a1-f6bc6ca93d93 \
         --scope https://management.core.windows.net//.default

az provider register -n Microsoft.App
az provider register -n Microsoft.OperationalInsights

az group create -n couvert-rg -l eastus
az containerapp env create -n couvert-env -g couvert-rg -l eastus --logs-destination none
```

**The plain `az login` is not enough on this tenant.** It authenticates the account, then
fails with `Status_InteractionRequired` against tenant `bc142eb8-…` and reports "No
subscriptions found". Passing `--tenant` explicitly is what works. If it still fails, the
local MSAL cache is corrupt rather than expired — `az account clear` then log in again, or
use `az login --use-device-code`.

`--logs-destination none` skips creating a Log Analytics workspace, removing the one line
item that can grow quietly ($4.60/GB beyond the free 5 GB). **Live log streaming still
works** (§6); what's lost is queryable history. Switch it on with
`az containerapp env update -n couvert-env -g couvert-rg --logs-destination log-analytics`
plus a workspace, if history is ever wanted.

Environment creation took **~7 minutes** and sat in `provisioningState: Waiting` the whole
time. That is normal — poll rather than assume it hung.

## 4. Create the app — already done

```bash
az containerapp create \
  -n couvert-api -g couvert-rg --environment couvert-env \
  --image ghcr.io/marcosboger/couvert-api:a4bf0a9 \
  --registry-server ghcr.io \
  --registry-username marcosboger --registry-password "$GHCR_TOKEN" \
  --target-port 5000 --ingress external \
  --min-replicas 1 --max-replicas 2 \
  --cpu 0.25 --memory 0.5Gi \
  --secrets cosmos-key="$COSMOS_KEY" firebase-json="$(cat firebase-service-account.json)" \
  --env-vars \
     COSMOS_ENDPOINT="https://db-food-app.documents.azure.com:443/" \
     COSMOS_DATABASE="CouvertApp" \
     CONTENT_CACHE_SECONDS="600" \
     COSMOS_KEY=secretref:cosmos-key \
     FIREBASE_CREDENTIALS_JSON=secretref:firebase-json
```

> Passing the service-account JSON through a shell is the fiddly part — it is 2.3 KB with
> embedded quotes. The first deploy was driven from a Python script that built the argv
> list directly (`subprocess.run` with no shell), which sidesteps quoting entirely. Worth
> repeating if a hand-typed command misbehaves.

Why these numbers:

- **`--min-replicas 1`** — no cold starts, which is the point. Scale-to-zero would be free
  but makes some user wait several seconds for a container to boot.
- **`--max-replicas 2`** — when a revision scales *above* its minimum, **every** replica
  bills at the active rate, not just the extra one. Keep the ceiling low.
- **`--cpu 0.25 --memory 0.5Gi`** — the smallest valid combination, and measured to be
  ample: the container idles at 79 MB and peaks at 85 MB of 512 MB, and served 200 requests
  capped at 0.25 CPU without an OOM kill.

## 5. Redeploying

```bash
TAG=$(git rev-parse --short HEAD)
docker build -t ghcr.io/marcosboger/couvert-api:$TAG .
docker push ghcr.io/marcosboger/couvert-api:$TAG
az containerapp update -n couvert-api -g couvert-rg \
  --image ghcr.io/marcosboger/couvert-api:$TAG
```

Every redeploy is a fresh 250 MB pull against the GHCR transfer quota (§2), so delete old
tags from the package page occasionally to stay inside the 500 MB storage allowance too.

Each new revision restarts the container, so it warms its cache again on startup; the first
request after a deploy is served warm rather than paying for 14 round trips to Cosmos.

Worth automating in a `deploy.yml` workflow on a push to `main` — build and push in
Actions, then `az containerapp update` with an Azure service principal or OIDC federated
credentials.

## 6. Operating it

```bash
# health of the current revision
az containerapp revision list -n couvert-api -g couvert-rg \
  --query "[].{name:name, active:properties.active, replicas:properties.replicas, health:properties.healthState}" -o table

# live console logs (works despite --logs-destination none)
az containerapp logs show -n couvert-api -g couvert-rg --tail 40 --type console

# confirm no secret leaked into plain env vars
az containerapp show -n couvert-api -g couvert-rg \
  --query "properties.template.containers[0].env[].{name:name, value:value, secretRef:secretRef}" -o table
```

**Read the startup log after every deploy.** `firebase_admin.initialize_app()` succeeds
with no credentials at all and only fails at the first token verification, so a
misconfigured deploy serves public content happily while every `/user/*` route is broken.
The app logs an explicit warning when neither `FIREBASE_CREDENTIALS_JSON` nor
`FIREBASE_CREDENTIALS_PATH` is set — a clean log means both Cosmos and Firebase were found.

Still open from the original checklist:

- **Point the app at this URL.** `BASE_URL` is hardcoded in
  `couvert-app/src/diplomat/httpClient.ts:11`; move it into `src/config/` (base, staging
  and prod files already exist). Then Android's `usesCleartextTraffic` can go, since the
  ingress is HTTPS.
- **Set `CORS_ORIGIN_REGEX`** before any deployed *web* build — it is currently unset and
  falls back to localhost-only.
- **Health probes**: liveness and readiness aren't configured. Point them at `/health`;
  probe requests aren't billable and don't disqualify a replica from idle rates.
- **Managed identity** for Cosmos instead of an account key.

## 7. What it costs

**⚠️ The figures below were verified for `brazilsouth`, and the service is deployed in
`eastus`. They have not been re-checked against East US retail prices.** East US is
typically one of Azure's cheaper regions, so the real bill should be at or below these
numbers — but treat them as an upper estimate rather than a verified figure until someone
re-runs the arithmetic against the Azure Retail Prices API for `eastus`.

A month is 730 hours = 2,628,000 seconds. Free grant per subscription per month: 180,000
vCPU-seconds, 360,000 GiB-seconds, 2M requests. At `--cpu 0.25 --memory 0.5Gi
--min-replicas 1`, running continuously:

| | Seconds billed | Rate | Cost |
|---|---|---|---|
| vCPU (idle) | 657,000 − 180,000 free = 477,000 | $0.000003 | $1.43 |
| Memory | 1,314,000 − 360,000 free = 954,000 | $0.000003 | $2.86 |
| Requests | under the 2M grant | $0.40/M | $0 |
| Registry | private GHCR package | — | $0 |
| Log Analytics | not provisioned (`--logs-destination none`) | — | $0 |
| Cosmos | free tier **confirmed applied** | — | $0 |
| **Total** | | | **≈ $4.29/month** |

Two things move that number:

- **Idle versus active.** A replica bills at the reduced idle rate only while it is scaled
  at its minimum, processing no HTTP requests, using under 0.01 vCPU and receiving under
  1,000 bytes/second. Real traffic bills at the active vCPU rate, which is 8× higher.
  Worst case — never idle for a whole month — was **$14.31** at brazilsouth rates. Dev and
  tester traffic sits near the floor.
- **Allocation.** Memory is the larger half of the idle bill, because idle vCPU and memory
  bill at the same per-second rate while the 2:1 ratio allocates twice as many GiB-seconds.

## 8. Local check before pushing to Azure

Docker runs in WSL on this machine, so the image can be verified end to end without
touching Azure. **Drive `wsl` from PowerShell, not Git Bash** — MSYS path conversion
rewrites arguments (`/tmp/x` becomes `C:/Program Files/Git/tmp/x`) and mangles backslash
escapes, which produces baffling failures.

```powershell
wsl -d Ubuntu-24.04 docker build -t couvert-api:test .
wsl -d Ubuntu-24.04 docker run -d --name couvert-smoke -p 5000:5000 --env-file /tmp/couvert.env couvert-api:test
```

Two environment traps, both of which cost time on the first attempt:

- **The WSL distro shuts down as soon as the last `wsl` command exits**, taking dockerd and
  every running container with it — the container shows `Exited (255)` and `/tmp` is wiped
  between invocations. Hold it open with a long-running background process
  (`wsl -d Ubuntu-24.04 sleep 1800`) for as long as the container is needed.
- **`.env` has CRLF line endings and `--env-file` does not strip `\r`**, so values silently
  gain a trailing carriage return. Build a normalised env file instead; and note that
  `tr -d "\r"` through nested shells can delete literal `r` characters rather than carriage
  returns. A short Python script is the reliable way.

Port 5000 matters: the app's `BASE_URL` is hardcoded to `http://127.0.0.1:5000`, so a
container published on 5000 needs no app changes for a local end-to-end test.

To exercise the deployment credential path specifically — the one thing local development
never uses, because locally you have a file:

```bash
docker run --rm -e FIREBASE_CREDENTIALS_JSON="$(cat firebase-service-account.json)" \
  --entrypoint python couvert-api:test -c \
  'from api.auth import _ensure_firebase; from core.config import Settings; import firebase_admin;
   _ensure_firebase(Settings()); print(firebase_admin.get_app().project_id)'
```

That prints `couvert-app` when the secret is wired correctly.

> **A garbage token proves less than it looks.** `verify_id_token()` rejects a malformed JWT
> at the decode/signature stage, before the service account's `project_id` is ever compared
> against the token's `aud` — so a container wired to the **wrong Firebase project** returns
> a byte-identical `401 Invalid or expired token`. Only a real ID token minted by the app
> distinguishes them. That end-to-end login was verified against the container before
> deploying.

## 9. Known rough edges

- `openpyxl` and `typer` are declared as main dependencies but are only used by `jobs/`,
  so the runtime image installs them for nothing. Moving them to an optional dependency
  group would slim the image; harmless otherwise.
- The in-memory cache is per replica, so if it ever scales to 2 each replica keeps its own
  copy and warms independently. That's correct for a read-only catalog, just worth knowing
  when reading RU metrics.
- Cosmos is reached with an account key. Managed identity plus Cosmos RBAC would be better;
  it needs role assignments and a code change to `DefaultAzureCredential`.
- `CORS_ORIGIN_REGEX` is unset in the deployment, so only localhost origins are allowed.
- No Log Analytics workspace, so there is no queryable log history — only live streaming.

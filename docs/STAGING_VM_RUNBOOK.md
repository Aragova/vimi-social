# ViMi Social staging VM runbook

This runbook deploys the first end-to-end ViMi Social staging slice on one Linux VM.
It is intentionally a staging topology, not the final horizontally scaled production topology.

## What runs on the VM

- Caddy: public HTTPS ingress for the Telegram webhook.
- Telegram bot FastAPI process.
- Core Temporal worker.
- Media Temporal worker with ffmpeg/ffprobe and optional visual moderation.
- Destination Temporal worker for X publication/reconciliation and user-context interest sync.
- Internal API process.
- PostgreSQL 17.
- Temporal 1.27.2.
- One-shot database role provisioning and Alembic migration steps.
- Persistent PostgreSQL, media, and Caddy volumes.

Only ports 80/443 are published by the staging compose file. PostgreSQL and Temporal remain on the internal Docker network. Processes that must call Telegram/X/OpenAI also join a separate egress-capable Docker bridge; they still publish no host ports.

The Compose model deliberately scopes credentials by process: Caddy does not receive application secrets; source-search credentials stay with the core worker; visual-moderation credentials, when configured, stay with the media worker; and the X user-context/publication credential stays with the destination worker.

## VM prerequisites

Recommended starting point for staging:

- Ubuntu 24.04 LTS or another current Linux distribution supported by Docker.
- 4 vCPU.
- 8 GB RAM.
- At least 60 GB SSD, with additional disk if media retention grows.
- Public IPv4/IPv6 address.
- A staging DNS hostname whose A/AAAA record points to the VM.
- Docker Engine and Docker Compose v2.
- Git access to the private `Aragova/vimi-social` repository.

Do not use the production Telegram bot or production X account for the first smoke test.

## 1. Clone the repository

```bash
git clone git@github.com:Aragova/vimi-social.git
cd vimi-social
git checkout main
git pull --ff-only
```

Confirm the expected deployed commit before proceeding:

```bash
git rev-parse HEAD
```

## 2. Create staging secrets

```bash
cp .env.staging.example .env.staging
chmod 600 .env.staging
nano .env.staging
```

Replace every `CHANGE_ME` value and fill these external credentials:

- `VIMI_PUBLIC_HOST`: staging DNS hostname, without `https://`.
- `VIMI_TELEGRAM_BOT_TOKEN`: dedicated staging Telegram bot token.
- `VIMI_TELEGRAM_WEBHOOK_SECRET`: random webhook secret.
- `VIMI_X_BEARER_TOKEN`: X source-search credential.
- `VIMI_OPENAI_API_KEY`: optional key used by sampled-frame visual moderation; leave it blank to disable that OpenAI-backed stage.
- `VIMI_DEST_X_PRIMARY_TOKEN`: user-context X credential allowed to upload media, create posts, and read the explicitly authorized personalization signals.

Database passwords are passed to PostgreSQL through environment variables and to psycopg through `PGPASSWORD`; they are not embedded in application DSNs.

Keep `VIMI_POSTGRES_BOOTSTRAP_PASSWORD` stable after the PostgreSQL volume has been initialized. The official PostgreSQL image consumes `POSTGRES_PASSWORD` when creating a fresh cluster; changing the value in `.env.staging` later does not itself rotate the existing `vimi_bootstrap` database password. App and migrator passwords are re-applied by `db-provision` on every deployment.

Never commit `.env.staging`.

## 3. Verify DNS and firewall

The staging hostname must resolve to this VM before Caddy can obtain a public TLS certificate.
Allow inbound TCP 80 and TCP/UDP 443. Do not expose 5432 or 7233 publicly.

## 4. Deploy

Use the deterministic deploy helper rather than manually relying on the lifecycle of previously completed one-shot Compose services:

```bash
sh scripts/deploy_staging.sh
```

The helper performs, in order:

1. validates `.env.staging`, rejects `CHANGE_ME` placeholders and requires the DB/Telegram/X values needed for the staging path; `VIMI_OPENAI_API_KEY` may remain empty;
2. validates the Compose model;
3. builds one shared Python runtime image for the application processes;
4. starts and waits for PostgreSQL;
5. force-recreates and runs password-backed DB role provisioning;
6. force-recreates and runs Alembic migrations with the migrator role;
7. force-recreates media-volume initialization for the non-root runtime UID;
8. starts Temporal;
9. starts bot/core/media/destination/API/Caddy services;
10. prints final Compose status.

The completed one-shot service containers remain as the exact `service_completed_successfully` dependency evidence for the application startup. This sequence is used for both the first deployment and later updates, so database role provisioning and migrations are explicit every time.

## 5. Check deployment state

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  ps
```

Check database provisioning and migration output when troubleshooting:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  logs db-provision migrate
```

Follow application logs:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  logs -f bot worker media-worker destination-worker caddy
```

## 6. Verify public health

```bash
curl -fsS "https://YOUR_STAGING_HOST/health"
```

Expected response:

```json
{"status":"ok"}
```

Do not continue to Telegram webhook configuration until HTTPS health succeeds.

## 7. Register the Telegram webhook

The bot container already contains the helper script and the minimal environment it needs.

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  exec bot python scripts/configure_telegram_webhook.py
```

The script configures:

`https://<VIMI_PUBLIC_HOST>/telegram/webhook`

with the configured Telegram secret-token header and verifies the resulting webhook URL.

## 8. Create the first Telegram workspace

Open the dedicated staging bot in Telegram and send `/start`.
This creates/resolves the Telegram identity, user, workspace, tenant, locale, and initial usage capacity through the normal application path.

To identify the staging tenant and user while OAuth/account-management UI is not implemented yet, resolve each Telegram identity through its workspace membership using the same default-first ordering as the application:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  exec postgres \
  psql -U vimi_bootstrap -d vimi \
  -c "SELECT ti.telegram_user_id, ti.user_id, wm.tenant_id, ti.username, ti.last_seen_at FROM telegram_identity AS ti JOIN LATERAL (SELECT tenant_id FROM workspace_membership WHERE user_id = ti.user_id ORDER BY is_default DESC, created_at ASC LIMIT 1) AS wm ON TRUE ORDER BY ti.last_seen_at DESC;"
```

Use the tenant UUID and user UUID belonging to the staging Telegram account only.

## 9. Authorize and provision one staging X account

Until customer OAuth/account-management lands, staging uses the repository OAuth helper. Re-authorize whenever the requested X OAuth scopes change. The current helper requests read scopes for follows, likes, Lists, and bookmarks in addition to the existing post/user/media/offline scopes. The token value is written to `.env.staging` and is never printed back after exchange.

For the standalone staging topology in this runbook, Caddy does not expose an nginx access log. Use manual callback mode:

```bash
PYTHONPATH=src python3 scripts/configure_staging_x_oauth.py --manual-callback
```

Open the printed X authorization URL. After X redirects the browser back to `https://<VIMI_PUBLIC_HOST>/?state=...&code=...`, the root route may display `Not Found`; that is expected. Copy the complete URL from the browser address bar and paste it into the helper prompt. The helper validates the OAuth state before exchanging the short-lived code.

On the nginx co-host staging topology, the helper can capture the callback automatically from `/var/log/nginx/access.log`, so use:

```bash
PYTHONPATH=src python3 scripts/configure_staging_x_oauth.py
```

After either authorization flow succeeds, recreate the destination worker before any personalization or publication smoke test. The OAuth helper updates `.env.staging`, while a running container keeps its previous environment until it is recreated.

For standalone staging:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  up -d --no-deps --force-recreate destination-worker
```

For nginx co-host staging, include the co-host override:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  -f infra/docker/docker-compose.staging.cohost.yml \
  up -d --no-deps --force-recreate destination-worker
```

Then provision the X destination and explicitly bind it to the workspace user who authorized that X account. `--user-id` is mandatory; the helper intentionally does not query `workspace_membership` through the application role.

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  exec bot \
  python scripts/provision_staging_x_destination.py \
  --tenant-id YOUR_TENANT_UUID \
  --user-id YOUR_USER_UUID \
  --external-account-id staging-primary \
  --display-name "Staging X"
```

The database stores only the credential reference. The actual X token remains available only to the destination worker as `VIMI_DEST_X_PRIMARY_TOKEN`.

## 10. First end-to-end smoke test

Run the real product path through Telegram:

1. Start an AI Search task.
2. Confirm that the X user-interest profile sync is best-effort and does not block Scout when unavailable.
3. Confirm that Scout returns X candidates and that personalized ranking metadata appears when a fresh profile exists.
4. Select a candidate that you are authorized to reuse.
5. Confirm the rights/provenance gate when requested.
6. Wait for secure media acquisition and MediaProbe.
7. Confirm scene detection/ranking completes.
8. Confirm sampled-frame visual moderation runs when `VIMI_OPENAI_API_KEY` is configured; otherwise confirm the rest of the media path proceeds without that optional stage.
9. Confirm destination preflight and VariantPlanner complete.
10. Confirm the rendered/passthrough video preview arrives in Telegram.
11. Confirm the publish button is shown only for an allowed policy decision.
12. Press the X publish approval button.
13. Confirm X media upload finishes and exactly one post appears in the staging X account.
14. Confirm the Telegram result reports the final publication state.

For the first staging exercise, use media that you own or are explicitly authorized to republish.

## 11. Durability / failure drills

After one clean success, repeat with controlled failures:

- restart `media-worker` during media processing;
- restart `destination-worker` during publication;
- restart the whole compose stack;
- inspect that Temporal resumes durable work;
- verify a publication already in ambiguous `DISPATCHING/UNKNOWN` state is not blindly sent again;
- verify UNKNOWN retains the publication usage reservation until reconciliation resolves it;
- verify no duplicate X post is created.

Useful commands:

```bash
docker compose --env-file .env.staging -f infra/docker/docker-compose.staging.yml restart media-worker

docker compose --env-file .env.staging -f infra/docker/docker-compose.staging.yml restart destination-worker

docker compose --env-file .env.staging -f infra/docker/docker-compose.staging.yml restart
```

## 12. Updating staging

```bash
git checkout main
git pull --ff-only
sh scripts/deploy_staging.sh
```

Always inspect `db-provision` and `migrate` output after an update if deployment does not become healthy.

## 13. Backups before meaningful staging data

Before treating staging data as valuable, add automated PostgreSQL backups and off-VM retention. The current single-VM media volume is also not a substitute for object storage or backups.

## Current staging limitations

- Destination X account provisioning is an operator step until OAuth/account-management exists.
- Media storage is a single-node Docker volume; horizontally scaled workers require shared object storage.
- Temporal and PostgreSQL run on the same VM for staging convenience.
- No production-grade backup automation is included yet.
- The staging topology is for product validation, not public multi-tenant production traffic.

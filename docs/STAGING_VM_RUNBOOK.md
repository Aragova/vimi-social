# ViMi Social staging VM runbook

This runbook deploys the first end-to-end ViMi Social staging slice on one Linux VM.
It is intentionally a staging topology, not the final horizontally scaled production topology.

## What runs on the VM

- Caddy: public HTTPS ingress for the Telegram webhook.
- Telegram bot FastAPI process.
- Core Temporal worker.
- Media Temporal worker with ffmpeg/ffprobe and visual moderation.
- Destination Temporal worker for X publication/reconciliation.
- Internal API process.
- PostgreSQL 17.
- Temporal 1.27.2.
- Persistent PostgreSQL, media, and Caddy volumes.

Only ports 80/443 are published by the staging compose file. PostgreSQL and Temporal remain on the internal Docker network.

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
- `VIMI_OPENAI_API_KEY`: key used by sampled-frame visual moderation.
- `VIMI_DEST_X_PRIMARY_TOKEN`: user-context X credential allowed to upload media and create posts.

Database passwords are passed to PostgreSQL through environment variables and to psycopg through `PGPASSWORD`; they are not embedded in application DSNs.

Never commit `.env.staging`.

## 3. Verify DNS and firewall

The staging hostname must resolve to this VM before Caddy can obtain a public TLS certificate.
Allow inbound TCP 80 and TCP/UDP 443. Do not expose 5432 or 7233 publicly.

## 4. Validate configuration before startup

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  config --quiet
```

Build the Python runtime image:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  build
```

## 5. Start the staging stack

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  up -d
```

The one-shot `migrate` service must complete successfully before the application services start.

Check status:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  ps
```

Check migration output:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  logs migrate
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

The bot container already contains the helper script and staging environment.

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

To identify the new staging tenant while OAuth/account-management UI is not implemented yet:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  exec postgres \
  psql -U vimi_bootstrap -d vimi \
  -c "SELECT telegram_user_id, tenant_id, username, created_at FROM telegram_identity ORDER BY created_at DESC;"
```

Use the tenant UUID belonging to the staging Telegram account only.

## 9. Provision one staging X destination

Until customer OAuth/account-management lands, provision one destination account through the repository helper. The helper stores only the credential reference; the actual X token remains in `VIMI_DEST_X_PRIMARY_TOKEN`.

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  exec bot \
  python scripts/provision_staging_x_destination.py \
  --tenant-id YOUR_TENANT_UUID \
  --external-account-id staging-primary \
  --display-name "Staging X"
```

## 10. First end-to-end smoke test

Run the real product path through Telegram:

1. Start an AI Search task.
2. Confirm that Scout returns an X candidate.
3. Select a candidate that you are authorized to reuse.
4. Confirm the rights/provenance gate when requested.
5. Wait for secure media acquisition and MediaProbe.
6. Confirm scene detection/ranking completes.
7. Confirm sampled-frame visual moderation runs when `VIMI_OPENAI_API_KEY` is configured.
8. Confirm destination preflight and VariantPlanner complete.
9. Confirm the rendered/passthrough video preview arrives in Telegram.
10. Confirm the publish button is shown only for an allowed policy decision.
11. Press the X publish approval button.
12. Confirm X media upload finishes and exactly one post appears in the staging X account.
13. Confirm the Telegram result reports the final publication state.

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

docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  up -d --build
```

Always inspect migration logs after an update.

## 13. Backups before meaningful staging data

Before treating staging data as valuable, add automated PostgreSQL backups and off-VM retention. The current single-VM media volume is also not a substitute for object storage or backups.

## Current staging limitations

- Destination X account provisioning is an operator step until OAuth/account-management exists.
- Media storage is a single-node Docker volume; horizontally scaled workers require shared object storage.
- Temporal and PostgreSQL run on the same VM for staging convenience.
- No production-grade backup automation is included yet.
- The staging topology is for product validation, not public multi-tenant production traffic.

# ViMi Social staging beside an existing nginx deployment

Use this mode only when the staging stack must share a Linux VM with an existing application whose host nginx already owns public ports 80/443.

The normal standalone staging topology in `docs/STAGING_VM_RUNBOOK.md` remains the preferred deployment on a dedicated VM.

## Safety boundary

Co-host mode keeps the existing host ingress in control:

- host nginx continues to own ports 80/443;
- staging Caddy is not started;
- the staging Telegram bot is published only on `127.0.0.1:${VIMI_STAGING_BOT_PORT:-18000}`;
- PostgreSQL and Temporal remain private Docker-network services with no host ports;
- existing host PostgreSQL/services are not reused or modified;
- the Docker Compose project remains named `vimi-staging`, so its networks and volumes are isolated from unrelated services.

Before deploying, verify the chosen loopback port is unused:

```bash
sudo ss -ltnp | grep ':18000 ' || true
```

No output means the default staging loopback port is free.

## Host capacity

A co-host VM has less isolation than a dedicated staging VM. Before starting the stack:

```bash
free -h
df -h
```

If RAM is constrained, add swap before the first image build and monitor the existing production services during staging startup. Swap is a safety buffer, not a replacement for adequate RAM.

## Deploy in co-host mode

Create `.env.staging` exactly as described in the normal staging runbook, then run:

```bash
VIMI_STAGING_COHOST=true sh scripts/deploy_staging.sh
```

To change the loopback port without editing Compose:

```bash
VIMI_STAGING_COHOST=true \
VIMI_STAGING_BOT_PORT=18000 \
sh scripts/deploy_staging.sh
```

The deployment helper uses both:

- `infra/docker/docker-compose.staging.yml`
- `infra/docker/docker-compose.staging.cohost.yml`

and intentionally does not start the `caddy` service.

## nginx route

Create a dedicated staging hostname, for example `staging.usevimi.ru`, and point its DNS record to the VM.

The host nginx server block should proxy only that hostname to the loopback staging bot. A minimal HTTP upstream section is:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name staging.usevimi.ru;

    location / {
        proxy_pass http://127.0.0.1:18000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Validate before reloading nginx:

```bash
sudo nginx -t
```

Only after validation succeeds:

```bash
sudo systemctl reload nginx
```

Use the host's existing certificate-management approach (for example Certbot) to enable HTTPS for the staging hostname. Do not disturb the existing production server blocks or certificates.

## Verify co-host isolation

Check that the staging bot is loopback-only:

```bash
sudo ss -ltnp | grep ':18000 '
```

Expected bind address starts with `127.0.0.1:18000`, not `0.0.0.0:18000`.

Check Docker services:

```bash
docker compose \
  --env-file .env.staging \
  -f infra/docker/docker-compose.staging.yml \
  -f infra/docker/docker-compose.staging.cohost.yml \
  ps
```

`caddy` should not be running in co-host mode.

Then continue with the normal runbook from public health verification and Telegram webhook registration.

# WIRE Operations Runbook

Everything here assumes the `deploy/docker-compose.yml` stack (Postgres +
Redis + API + workers) or an equivalent topology. Commands are run from
`deploy/` unless noted.

## Public deployment (VM + domain + TLS + dashboard)

To serve the platform to real users on `https://your-domain`, add the
production overlay (`docker-compose.prod.yml`), which puts **Caddy** in front
(automatic Let's Encrypt TLS), builds the **React dashboard**, and serves it
same-origin with the API.

**Prerequisites**
1. A Linux VM with Docker + Docker Compose, ports **80** and **443** open.
2. A domain's DNS **A record** pointing at the VM's public IP.
3. `../.env` filled in — at minimum:
   ```
   WIRE_DOMAIN=your-domain.com
   JWT_SECRET_KEY=<python -c "import secrets; print(secrets.token_urlsafe(48))">
   POSTGRES_PASSWORD=<strong random>
   WIRE_CORS_ORIGINS=https://your-domain.com
   WIRE_ENABLE_HSTS=1
   ```

**Deploy**
```bash
cd deploy
docker compose --env-file ../.env \
    -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Caddy issues the certificate on first request (may take ~30s). Then
`https://your-domain.com` serves the dashboard and `https://your-domain.com/api`
is the API. The API's own port is no longer published — only Caddy is exposed.

**Firewall (recommended):** allow only 22/80/443; the API (8000), Postgres,
and Redis stay on the internal Docker network.

**Update the dashboard/API after a code change:**
```bash
git pull
docker compose --env-file ../.env \
    -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
(`frontend-build` re-bakes `VITE_API_BASE_URL=https://$WIRE_DOMAIN/api` into the
bundle each build.)

## Start / stop / scale

```bash
docker compose --env-file ../.env up --build -d     # start (runs migrations first)
docker compose logs -f api worker                   # follow logs (structlog)
docker compose up --scale worker=3 -d               # more reconstruction throughput
docker compose down                                 # stop (volumes persist)
```

Required in `.env`: `JWT_SECRET_KEY` (generate:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`),
`POSTGRES_PASSWORD`. Set `WIRE_ENABLE_HSTS=1` only when TLS terminates in
front of the API.

**Topology rule:** run the API as a single process per `WIRE_REDIS_URL`-less
deployment. With multiple API replicas or `uvicorn --workers N`, Redis is
mandatory — without it each process enforces its own copy of the rate limits.

## Migrations

Compose runs `alembic upgrade head` automatically (the `migrate` one-shot
service) before the API starts. Manually:

```bash
docker compose run --rm migrate                            # upgrade to head
docker compose run --rm migrate alembic downgrade -1       # roll back one revision
```

Migrations are additive so far (new columns/tables, all nullable or defaulted);
downgrades are safe but drop the corresponding data (e.g. refresh tokens force
re-login).

## Rollback (bad deploy)

1. `docker compose down` (volumes/data survive).
2. Check out the previous known-good tag / image.
3. If the bad deploy included a migration, `alembic downgrade` to the revision
   the old code expects (`alembic history` inside the image lists them).
4. `docker compose up -d`, then verify `GET /api/status` and a login.

## Monitoring & alerting

Prometheus scrape targets: every API and worker process exposes
`GET /api/metrics` (workers: only if run with the API image serving; otherwise
rely on the API's counters for enqueue and the DB queries below).

Key series:

| Metric | Meaning |
| --- | --- |
| `wire_http_request_duration_seconds` (histogram) | API latency |
| `wire_pipeline_duration_seconds` (histogram) | reconstruction wall time |
| `wire_jobs_enqueued_total` / `wire_jobs_completed_total` / `wire_jobs_failed_total` | queue flow |
| `wire_jobs_stale_results_discarded_total` | zombie-worker writes prevented (should be ~0) |
| `wire_reconstructions_requested_total` | demand |

Suggested alert rules (PromQL sketches):

```yaml
# API p95 latency over 2s for 10m (excludes the SSE stream by construction)
histogram_quantile(0.95, rate(wire_http_request_duration_seconds_bucket[5m])) > 2

# Job failure ratio over 20% in the last hour
increase(wire_jobs_failed_total[1h])
  / clamp_min(increase(wire_jobs_enqueued_total[1h]), 1) > 0.2

# Queue is backing up: enqueued but nothing completing
increase(wire_jobs_enqueued_total[30m]) > 0
  and increase(wire_jobs_completed_total[30m]) == 0
```

Queue depth / stuck jobs (SQL, e.g. via a postgres_exporter custom query):

```sql
SELECT status, count(*) FROM reconstruction_jobs GROUP BY status;
-- jobs running with a stale heartbeat (candidates for auto-recovery):
SELECT id, attempts, heartbeat_at FROM reconstruction_jobs
 WHERE status = 'running'
   AND coalesce(heartbeat_at, started_at) < now() - interval '30 minutes';
```

Stale jobs requeue automatically (workers run `recover_stale` each loop; a
worker heartbeats every 60s while running, and a requeued job's original
worker cannot double-write — its claim token is invalidated).

## Backup & restore

Two stateful pieces: Postgres and the `wire-output` volume (reconstruction
artifacts; the DB references them by `projects.run_id`).

```bash
# Backup
docker compose exec db pg_dump -U wire wire | gzip > wire-db-$(date +%F).sql.gz
docker run --rm -v deploy_wire-output:/data -v "$PWD":/backup alpine \
  tar czf /backup/wire-output-$(date +%F).tar.gz -C /data .

# Restore (into a fresh stack)
gunzip -c wire-db-DATE.sql.gz | docker compose exec -T db psql -U wire wire
docker run --rm -v deploy_wire-output:/data -v "$PWD":/backup alpine \
  tar xzf /backup/wire-output-DATE.tar.gz -C /data
```

Restore order: database first, then the volume; artifacts without DB rows are
harmless, DB rows without artifacts 404 on file access until re-run.

## Incident quick reference

| Symptom | First checks |
| --- | --- |
| Reconstructions stuck `pending` | Is a worker running? `docker compose ps worker`; worker logs; `SELECT` queue depth above |
| Reconstructions failing | `SELECT error FROM reconstruction_jobs WHERE status='failed' ORDER BY id DESC LIMIT 5;` — compliance blocks (robots.txt) are permanent by design |
| 429s for legitimate users | Raise `WIRE_RATE_LIMIT_RECONSTRUCTIONS` / `WIRE_DAILY_RECONSTRUCTION_QUOTA`; confirm Redis is reachable (limiter fails open when it isn't — check logs for `rate_limit_redis_unavailable`) |
| Users logged out en masse | Was `JWT_SECRET_KEY` rotated/unset? Ephemeral keys invalidate all tokens on restart |
| Previews broken in dashboard | File tokens expire after 15 min (re-select the project); check `/files/` 401s in API logs |

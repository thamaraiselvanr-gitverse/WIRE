# Deployment

- `docker-compose.yml` — full stack: Postgres, Redis, one-shot Alembic
  migration, API, and reconstruction worker(s), sharing an output volume.
- `RUNBOOK.md` — operations guide: start/stop/scale, migrations, rollback,
  monitoring + alert rules, backup/restore, incident quick reference.

The container image builds from the repo-root `Dockerfile` (API and worker
share it; the worker just runs `python -m wire.worker`).

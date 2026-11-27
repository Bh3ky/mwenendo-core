# ADR-0017: Deploy to a single VM running Docker Compose

- **Status:** Accepted for the deployment shape. The provider is not final: it will be confirmed when the application goes live.
- **Date:** 2026-11-27
- **Roadmap milestone:** Milestone 8

## Context

The system is five processes: the web app, a Celery worker, Celery beat, PostgreSQL and Redis. Reservation expiry needs the worker and beat (ADR-0012), so a host that can only run a web process cannot run the whole system. We have a tested `docker-compose.yml` that starts all of them.

The goal is a live, demonstrable deployment that costs nothing or close to it, and that can be paused and restarted easily.

## Options considered

The facts about free tiers below come from third-party summaries and one search per platform. They change often and the sources disagree in places, so each should be checked on the provider's own page before relying on it.

1. **One Linux VM running the compose stack, with Caddy in front for HTTPS.**
   - Pros: every process runs exactly as it does locally, so the deployed system is the tested one. No per-service limits.
   - Cons: one machine, so no redundancy. Patching, backups and updates are ours.
   - Free option: Oracle Cloud's Always Free tier. Oracle's own resources page lists Arm (Ampere A1) compute up to 4 OCPUs and 24 GB in total, and up to two small AMD VMs. Third-party posts say the Arm allowance was cut to 2 OCPUs and 12 GB in 2026, which conflicts with the official page, so check it at sign-up. Oracle states that idle Always Free instances may be reclaimed (idle means 95th-percentile CPU under 20% over 7 days). Sign-up and capacity problems for Arm instances are widely reported.
2. **A managed platform split into services (for example Render).**
   - What the sources say: free web services sleep after 15 minutes without traffic and wake on the next request (about a minute). The free Postgres database expires after 30 days. The free Redis-compatible store is small (25 MB) and keeps nothing across restarts. Background workers are not free, so the worker and beat could not run, and expiry would depend on the sweep that nobody runs. Render's documentation says not to use free instances for production.
   - Verdict: wakes easily, but cannot run the whole system for free, and the database expiry is disqualifying.
3. **Free SaaS pieces combined** (a serverless Postgres such as Neon, a hosted Redis such as Upstash, and a web host).
   - What the sources say: Neon's free Postgres scales to zero after 5 minutes idle, with a monthly compute allowance (its limits are reported inconsistently). Upstash's current free plan lists 500,000 commands per month. Celery's Redis transport polls constantly, so that allowance would very likely be exhausted quickly (my inference, not measured).
   - Verdict: several accounts and moving parts, and a worker and beat still need somewhere to run.
4. **Newer platforms (Fly.io, Railway, Koyeb).** The sources conflict on whether free plans exist, and describe time-limited trials. Not relied on.
5. **A small paid VPS.** The same as option 1 without the free tier's risks, at a few dollars a month (not checked).

## Decision

- **Option 1: one VM running `docker-compose.prod.yml`, with Caddy terminating HTTPS.** The first candidate is an Oracle Cloud Always Free Arm VM. If sign-up or capacity fails, any small Linux VPS works with no changes to the files.
- **`docker-compose.prod.yml` differs from the development file:** only Caddy publishes ports (80 and 443). The database, Redis and the app are internal. Every service restarts by itself. Migrations run as a one-shot service before the app starts, which is safe because there is exactly one app container (ADR-0013 warned against it with several). Redis keeps an append-only file, so queued tasks survive a restart.
- **Caddy** obtains and renews a Let's Encrypt certificate by itself. It answers `/metrics` with 404, so metrics are not public (ADR-0015).
- **Settings:** `BEHIND_TLS_PROXY=True` makes Django trust `X-Forwarded-Proto` and mark the session and CSRF cookies secure. `CSRF_TRUSTED_ORIGINS` names the site's origin. Both are off by default, so local development over HTTP is unchanged.
- **Two Django deployment warnings are left on purpose.** `SECURE_SSL_REDIRECT` is Caddy's job (it redirects HTTP to HTTPS automatically). `SECURE_HSTS_SECONDS` is not set, because browsers remember HSTS for the whole period, and it should only be turned on once the domain is final.
- **The guide is `docs/DEPLOYMENT.md`.** It covers creating the VM, DNS, secrets, first start, updates, restarting after a pause and backups.

## Consequences

- **Good:**
  - The deployed system is the tested one, with all five processes and no feature lost.
  - Free, if the provider's terms hold, and pausing is stopping the VM.
  - After a pause, the periodic sweep expires whatever became overdue while it was off (ADR-0012), so no manual repair is needed.
- **Bad / trade-offs:**
  - **Nothing has been deployed yet.** The production compose file validates and its settings are tested, but the HTTPS certificate, the Arm build and the idle-reclamation behaviour are unverified until it is run for real.
  - **The image is built for the architecture it is built on.** CI builds only for x86. An Arm VM builds its own image, which should work (the base image is multi-architecture and the database driver ships Arm wheels), but is untested.
  - One machine means no redundancy and downtime during updates and reboots.
  - Idle reclamation: a quiet instance can be reclaimed by the provider. The project backs up its database and can be rebuilt from the repository, but the data is lost without a backup.
  - Operating the VM (security updates, disk space, backups, monitoring) is manual.
  - `/admin/` and `/api/docs` are public. There is no authentication on the API yet (see the architecture document), so a public deployment is a demonstration, not a service to hold real data.
- **Revisit when:**
  - We need redundancy or zero-downtime deploys, which means more than one instance, an external pooler (ADR-0016) and a managed database.
  - The provider changes its free terms.
  - The API gains authentication and the deployment starts to hold real data.

## References

- [Oracle: Always Free resources](https://docs.oracle.com/iaas/Content/FreeTier/resourceref.htm)
- [Render: free instances](https://render.com/docs/free)
- [Caddy: automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Docker: install Docker Engine on Ubuntu](https://docs.docker.com/engine/install/ubuntu/)
- [Django: deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- ADR-0012: Reservation expiry with a delayed task and a periodic sweep
- ADR-0013: Run in containers behind gunicorn, with static files from WhiteNoise
- ADR-0015: A Prometheus `/metrics` endpoint, with database-backed business gauges
- ADR-0016: Persistent database connections, no pool yet

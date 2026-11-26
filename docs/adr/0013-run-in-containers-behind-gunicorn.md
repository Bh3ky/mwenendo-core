# ADR-0013: Run in containers behind gunicorn, with static files from WhiteNoise

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 8

## Context

Until now the application has run from a terminal with `manage.py runserver`, which is a single-process development server and says so in its own documentation. The load tests (`docs/BENCHMARKS.md`) were run against it and had to be labelled a floor. To deploy, and to measure fairly, the application needs a production-style server and a repeatable way to start it together with its worker and scheduler.

Three things need deciding: the application server, how static files are served once `DEBUG` is off (the admin and the API docs need them), and how the processes are packaged and started.

## Options considered

For the application server:

1. **gunicorn** serving the existing WSGI application.
   - Pros: the standard, well-documented choice for Django, with a pre-fork model that gives true parallelism across cores, and it needs no change to the code.
   - Cons: synchronous workers, so each worker handles one request at a time.
2. **uvicorn or another ASGI server.**
   - Pros: supports async views and long-lived connections.
   - Cons: nothing in this project is async. Django's database access would still be synchronous, so it adds a layer without a benefit today.
3. **Keep `runserver`.**
   - Pros: nothing to change.
   - Cons: not meant for production, and it makes the benchmarks unrepresentative.

For static files:

1. **WhiteNoise** in the application.
   - Pros: one small dependency, no separate web server, and it works the same locally and in a container.
   - Cons: the Python process serves the files, which a CDN or a reverse proxy would do better at a larger scale.
2. **A separate reverse proxy (nginx) serving them.**
   - Pros: the usual large-scale setup.
   - Cons: another container and config to maintain for a handful of admin files.
3. **Treat the container as API-only,** and skip static files.
   - Pros: no dependency.
   - Cons: the admin and `/api/docs` look broken, and the admin is the easiest way to inspect data.

## Decision

- **gunicorn** with 4 workers by default (`WEB_CONCURRENCY` overrides it), configured in `gunicorn.conf.py`. The worker count is a starting point to be tuned with a load test. ASGI is revisited if the application gains async work.
- **WhiteNoise** serves static files, collected into `staticfiles/` at build time with `collectstatic`. It uses the plain compressed storage, not the manifest one, so tests and local development need no collected files.
- **One image, three roles.** The same image runs the web app, the Celery worker and Celery beat, each with its own command in `docker-compose.yml`. The image runs as a non-root user, installs dependencies from the lock file with `uv sync --locked --no-dev`, and installs them before copying the code so the dependency layer is cached.
- **A compose profile.** `app`, `worker` and `beat` are in the `app` profile. A plain `docker compose up -d` still starts only PostgreSQL and Redis, which keeps the everyday terminal workflow working.
- **Configuration from the environment.** The containers read `.env` and override only what must differ inside Docker (`POSTGRES_HOST`, `REDIS_URL`, `DEBUG`). No secret is copied into the image: `.env` is in `.dockerignore`, and `collectstatic` gets throwaway values for the one build step that needs settings.
- **Migrations are a separate step,** `docker compose run --rm app python manage.py migrate`, not run on container start. Several app containers starting together would race each other.
- **CI builds the image** on every push, so a broken Dockerfile fails the build.

## Consequences

- **Good:**
  - One command starts the whole system, and the benchmark can be repeated against a real server.
  - The image is small in role (a Python base and the locked dependencies) and does not run as root.
  - Workers can be scaled by changing one number.
- **Bad / trade-offs:**
  - Synchronous workers: 4 workers means 4 requests in flight per container. A slow request ties one up.
  - WhiteNoise makes the Python process serve static files.
  - Migrations are a manual step, so a deploy that forgets it runs new code on an old schema.
  - `/health/` only shows that the process is alive, not that PostgreSQL or Redis can be reached. A readiness check is a later addition.
  - The worker and beat containers have no health check. A stuck worker would not be noticed by Docker.
  - No TLS or secure-cookie settings yet. They belong with the deployment decision, where the proxy in front is known.
- **Revisit when:**
  - Load tests show the worker count or the worker type is the limit (threads, or async views).
  - Static files become a measurable load, or a CDN is added.
  - The deployment target decides how migrations, health checks and TLS are handled.

## References

- [Django: deploying with gunicorn](https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/gunicorn/)
- [Gunicorn: design and worker types](https://docs.gunicorn.org/en/stable/design.html)
- [WhiteNoise with Django](https://whitenoise.readthedocs.io/en/stable/django.html)
- [Docker: Compose profiles](https://docs.docker.com/compose/how-tos/profiles/)
- [Django: deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
- ADR-0012: Reservation expiry with a delayed task and a periodic sweep

# ADR-0014: Structured JSON logging and a separate readiness check

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 8

## Context

The application and its worker printed plain-text lines in several formats: gunicorn's access log, Django's, Celery's and the odd stray `print`. Nobody reads logs by eye in production. A log aggregator searches them, and it can only filter on fields (the request, the status, the duration) if each line is structured data.

Separately, `/health/` returns "healthy" whenever the process is running, even if PostgreSQL is down. Orchestrators ask two different questions: should this instance be restarted (liveness), and should it be sent traffic (readiness).

## Options considered

For log format:

1. **A small JSON formatter on the standard library.**
   - Pros: no new dependency, about 30 lines, and easy to read end to end.
   - Cons: no processors, no automatic context binding, and we maintain it.
2. **`structlog` or `python-json-logger`.**
   - Pros: richer features and well tested.
   - Cons: a new dependency and a second logging model, for features we do not yet need.
3. **Plain text.**
   - Pros: nothing to change.
   - Cons: not searchable by field.

For readiness:

1. **A separate `/health/ready/` that checks dependencies; `/health/` stays a liveness check.**
2. **Make `/health/` check the database.**
   - Cons: a brief database outage would fail the container's health check and could get a working app restarted, which does not help.
3. **No readiness check.**
   - Cons: a load balancer cannot tell a broken instance from a healthy one.

## Decision

- **Option 1 for logs.** `core/logs.py` has a `JsonFormatter`. Every line is one JSON object with `timestamp`, `level`, `logger` and `message`, plus any fields passed with `extra={...}` as top-level keys. `LOGGING` sends everything, including Django's and Celery's loggers, through it. `LOG_LEVEL` sets the level, `INFO` by default.
- **A request middleware** logs one line per request (`method`, `path`, `status`, `duration_ms`) and gives the request an id, held in a context variable so every log line written during the request carries it. A client or proxy may supply `X-Request-ID`. It is trusted only if it is 1 to 64 plain characters (letters, digits, `.`, `_`, `-`), so a header cannot put newlines or huge text into the logs. The id is returned in the response header. Only the path is logged, never the query string.
- **Business events** are named log lines with fields: `reservation.created`, `.confirmed`, `.cancelled` and `.expired` (logged only after the transaction commits) and a `stock.allocation_refused` warning with the numbers requested and available.
- **Celery** no longer takes over the root logger (`CELERY_WORKER_HIJACK_ROOT_LOGGER = False`), so worker and beat lines are JSON too. Gunicorn's own access log is turned off, because the middleware already logs each request.
- **Readiness** is `/health/ready/`. It checks the database (`SELECT 1`) and Redis (`PING`), each with a one-second timeout, and reports both. **Only the database decides the status code** (200, or 503). Redis down is reported as `"error"` but the instance stays ready, because reservations still work without it and expiry falls back to the periodic sweep (ADR-0012). Taking every instance out of service for a Redis outage would turn a degradation into an outage.
- **The Docker health check stays on `/health/`** (liveness), so a database blip does not restart a working container.

## Consequences

- **Good:**
  - Logs can be filtered by request, status, duration or event in any aggregator, and one request's lines can be found together by id.
  - A caller can quote the `X-Request-ID` from a response when reporting a problem.
  - The business events give a record of what the system did, and they are the natural source for the metrics added next.
  - The orchestrator can tell "alive" from "ready".
- **Bad / trade-offs:**
  - A hand-written formatter has no automatic context binding beyond the request id. Task ids and other context have to be added by hand.
  - The request id is not yet passed into Celery tasks, so a task cannot be traced back to the request that caused it.
  - Every request writes a line, which is cheap here and would need sampling at high volume.
  - Readiness opens a Redis connection on every call.
  - Gunicorn's start-up and error messages are still plain text, because they are written before the application loads.
  - Local tests prove the format and the fields. They cannot show that a real log aggregator parses the lines as expected.
- **Revisit when:**
  - We need richer context (`structlog`), or traces across the request, the task and the worker.
  - Log volume makes per-request lines too expensive.
  - A deployment target needs its own health-check path or format.

## References

- [Python: logging cookbook, structured logging](https://docs.python.org/3/howto/logging-cookbook.html#implementing-structured-logging)
- [Django: logging](https://docs.djangoproject.com/en/5.2/topics/logging/)
- [Celery: logging options](https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger)
- [Kubernetes: liveness, readiness and startup probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/)
- ADR-0012: Reservation expiry with a delayed task and a periodic sweep
- ADR-0013: Run in containers behind gunicorn, with static files from WhiteNoise

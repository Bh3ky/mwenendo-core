# ADR-0016: Persistent database connections, no pool yet

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 8

## Context

Django's default (`CONN_MAX_AGE = 0`) opens a new PostgreSQL connection at the start of every request and closes it at the end. Opening one costs a network round trip and an authentication, and PostgreSQL starts a whole process for each. Under a real server that setup cost is paid on every request.

There is also a budget: PostgreSQL allows 100 connections by default, and every process that touches the database can hold one.

## Options considered

1. **Persistent connections:** `CONN_MAX_AGE = 60` and `CONN_HEALTH_CHECKS = True`. Each worker keeps its connection between requests and reuses it.
   - Pros: a few lines, no new dependency. The health check drops a connection that died instead of failing a request.
   - Cons: every worker holds a connection even when idle, and a connection that outlives a database restart is only noticed on the next request (which the health check handles).
2. **A psycopg connection pool** (`OPTIONS: {"pool": True}`, with `psycopg[pool]`).
   - Pros: connections are shared by the threads of a process, which helps threaded and async servers.
   - Cons: our gunicorn workers each handle one request at a time, so a pool per process adds little over option 1. It also cannot be combined with `CONN_MAX_AGE`: Django raises `ImproperlyConfigured` if both are set, and treats that as by design.
3. **An external pooler (PgBouncer).**
   - Pros: one place that caps connections across many app instances.
   - Cons: another container to run and monitor, and it changes some PostgreSQL behaviour (session state). Worth it at many instances, not at one.
4. **The default (`CONN_MAX_AGE = 0`).**
   - Pros: nothing to change, and no idle connections.
   - Cons: the cost described above.

## Decision

- **Option 1.** `CONN_MAX_AGE` defaults to 60 seconds and `CONN_HEALTH_CHECKS` is on. `DB_CONN_MAX_AGE` overrides the age, so `0` turns persistence off, which the benchmark uses for its comparison.
- **No pool for now.** It is the next step only if measurement shows a need, and it would replace `CONN_MAX_AGE`, not add to it.
- **The Celery worker runs with `--concurrency=2`.** Expiry tasks are tiny, and each worker process can hold a connection, so the default of one process per CPU core would hold several more for no benefit.

### The connection budget

| Process | Connections it can hold |
|---|---|
| gunicorn workers (`WEB_CONCURRENCY`, default 4) | 4 |
| Celery worker (`--concurrency=2`) | 2 |
| Celery beat | 0 (it does not query the database) |
| A shell, `psql`, a migration | a few |
| **Total** | **about 6 to 10, against a limit of 100** |

Each additional app container adds another 4, so the limit is reached at roughly 20 app containers. That is the point at which an external pooler becomes worth considering.

## Consequences

- **Good:**
  - Requests no longer pay for connection setup.
  - A connection that died (a database restart, a network blip) is replaced before it fails a request.
  - The connection count is known and small.
- **Bad / trade-offs:**
  - Idle workers hold connections, which matters only near the limit.
  - A long `CONN_MAX_AGE` delays picking up a database-side change such as a failover. 60 seconds is a compromise.
  - The effect on speed is measured, not assumed, and the measurement is one machine with the load generator on it. See `docs/BENCHMARKS.md`.
- **Revisit when:**
  - The number of app containers approaches the connection limit (an external pooler).
  - We move to threaded or async serving (a psycopg pool, with `CONN_MAX_AGE` back at 0).
  - A deployment target dictates its own pooling.

## References

- [Django: persistent connections](https://docs.djangoproject.com/en/5.2/ref/databases/#persistent-database-connections)
- [Django: connection pooling](https://docs.djangoproject.com/en/5.2/ref/databases/#connection-pool)
- [Django ticket #35685: pool and `CONN_MAX_AGE`](https://code.djangoproject.com/ticket/35685)
- [PostgreSQL: connections and authentication](https://www.postgresql.org/docs/current/runtime-config-connection.html)
- ADR-0013: Run in containers behind gunicorn, with static files from WhiteNoise

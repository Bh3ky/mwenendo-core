# ADR-0001: Use PostgreSQL as the database

- **Status:** Accepted
- **Date:** 2026-11-17
- **Roadmap milestone:** Milestone 1

## Context

Mwenendo Core allocates limited inventory under concurrent demand. Its central invariant is:

`allocated_quantity <= total_quantity`

This must hold however many reservation requests compete for the same stock. Holding it needs a database that provides:

- **Real transactions** across multiple simultaneous connections.
- **Row-level locking** (`SELECT ... FOR UPDATE`), so competing requests for the same inventory row are serialised without blocking unrelated rows.
- **Database-enforced constraints** (e.g. `CHECK`), so the invariant is protected even if application code has a bug.

The project started on Django's default SQLite database. It is also a learning project whose later milestones (concurrency control, load testing) must run against the same database engine that production would use.

## Options considered

1. **SQLite**
   - Pros: no server, zero setup, ships with Python.
   - Cons: a file-based database with a single writer; a write locks the whole database, not individual rows. Django's `select_for_update()` has no effect on SQLite, so a concurrency test could pass without proving anything. Dev and production would also differ.

2. **PostgreSQL**
   - Pros: row-level locking, MVCC, `CHECK` constraints, partial indexes, `SKIP LOCKED` (useful for queue-like work), and strong Django support. Widely used in production and offered by most hosts and CI systems.
   - Cons: a separate server to run, configure and secure; credentials to manage; a driver (`psycopg`) to install.

3. **MySQL / MariaDB**
   - Pros: InnoDB also supports row-level locks and transactions, and is widely hosted.
   - Cons: a weaker constraint story for this project (e.g. `CHECK` support came later and has differed between versions and forks), fewer Django-specific features than PostgreSQL, and less direct relevance to the concurrency patterns this project intends to teach.

## Decision

Use **PostgreSQL 17**, run locally through Docker Compose, accessed from Django through `psycopg` (v3).

Connection settings come from environment variables (`POSTGRES_*` in `.env`), following twelve-factor configuration. The published port is bound to `127.0.0.1` so the development database is not reachable from the network.

## Consequences

- **Good:**
  - Row-level locking and `CHECK` constraints are available for the allocation invariant.
  - Concurrency tests will exercise real database behaviour.
  - Development, CI and production can use the same engine.
- **Bad / trade-offs:**
  - Developers must run a container and keep `.env` credentials in sync with the data volume.
  - Credentials are read only when the volume is first initialised, so changing the password later needs a deliberate step, not an edit.
  - Tests and CI need a Postgres service.
  - Postgres has a connection limit (default `max_connections=100`), so connection management matters under load (see Milestone 8).
  - Major version upgrades require a data migration, so the image tag is pinned to a major version.
- **Revisit when:**
  - The chosen deployment target cannot provide managed PostgreSQL at a reasonable cost.
  - Write contention on hot rows exceeds what a single instance can serve, which would prompt looking at pooling, partitioning or a different allocation strategy, not necessarily a different database.

## References

- [PostgreSQL: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [Django: `select_for_update()`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update), which notes it has no effect on backends that don't support it, such as SQLite
- [Django: Databases, PostgreSQL notes](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes)
- [The Twelve-Factor App: Config](https://12factor.net/config)

# Mwenendo Core - Roadmap

- Milestone 1 - Foundations and environment
    - [x]  Create the Django project and configure settings.
    - [x]  Understand Django apps and separation of concerns.
    - [x]  Move settings to environment variables (`.env` and `.env.example`).
    - [x]  Run PostgreSQL via Docker Compose and switch Django to it.
    - [x]  Add pytest-django and a first test (the health check).
    - [x]  Add ruff and a GitHub Actions workflow (lint and tests against Postgres).
    - [x]  Write ADR-0001: why PostgreSQL.
    - [x]  Split into apps: `core` (shared and health), `inventory` and `reservations`.

    > *Outcome:* A reproducible development environment, with CI running on every push.
    >
- Milestone 2 - Database modelling and integrity
    - [x]  Design Product and Inventory models.
    - [x]  Introduce database constraints.
    - [x]  Understand migrations and indexes.
    - [x]  Implement basic stock management.
    - [x]  Test each constraint using Factory Boy.
    - [x]  Write ADR: stock model (mutable counter vs append-only ledger).
    - [x]  Write ADR: enforcing `allocated <= total` with a database `CheckConstraint` vs code only.

    > *Outcome:* A database that rejects invalid inventory states.
    >
- Milestone 3 - Reservation API
    - [x]  Introduce Django Ninja.
    - [x]  Create Pydantic request and response schemas.
    - [x]  Implement reservation creation and retrieval.
    - [x]  Introduce HTTP status codes and API error handling.
    - [x]  Test each endpoint and error path as it is built.

    > *Outcome:* A functioning, tested REST API.
    >
- Milestone 4 - Transaction and concurrency control

    [core engineering milestone]

    - [x]  Understand ACID transactions.
    - [x]  Learn PostgreSQL row-level locking.
    - [x]  Implement `transaction.atomic()`.
    - [x]  Introduce `select_for_update()`.
    - [x]  Simulate competing reservation requests with a threaded concurrency test (`TransactionTestCase`).
    - [x]  Write ADR: pessimistic locking (`select_for_update`) vs optimistic locking.

    > *Outcome:* A reservation engine that protects inventory under concurrent requests.
    >
- Milestone 5 - Finite State Machine and Idempotency
    - [x]  Implement permitted state transitions.
    - [x]  Prevent invalid transitions.
    - [ ]  Introduce idempotency keys.
    - [ ]  Handle duplicate requests and repeated operations.
    - [ ]  Design and add an append-only stock movement ledger alongside the counters (with an ADR, revisiting ADR-0003).

    > *Outcome:* Predictable reservation lifecycle management.
    >
- Milestone 6 - Background processing
    - [ ]  Configure Celery and Redis.
    - [ ]  Implement reservation expiry.
    - [ ]  Add a periodic expiry sweep as a safety net alongside per-reservation tasks.
    - [ ]  Handle retries and task failures.
    - [ ]  Introduce transaction commit hooks (`transaction.on_commit`) and, optionally, an outbox pattern (with an ADR).

    > *Outcome:* Automated reservation lifecycle management.
    >
- Milestone 7 - Load testing and benchmarks
    - [ ]  Locust load scenarios.
    - [ ]  Measure throughput, p95/p99 latency and error rates.
    - [ ]  Write up the results as a benchmark report.

    > *Outcome:* Evidence that the system behaves correctly under load.
    >
- Milestone 8 - Production readiness and going live
    - [ ]  Choose the deployment target (with an ADR).
    - [ ]  Dockerise the application.
    - [ ]  Configure structured logging and monitoring, including a `/metrics` endpoint.
    - [ ]  Add database connection management.
    - [ ]  Document architecture and deployment.
    - [ ]  Produce performance benchmarks.
    - [ ]  Deploy the application live.

    > *Outcome:* A live, demonstrable backend engineering portfolio project.
    >

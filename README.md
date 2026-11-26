# Mwenendo Core

**A high-concurrency, event-driven inventory allocation engine built with Python, Django and PostgreSQL.**

Mwenendo Core explores how backend systems can reliably allocate limited inventory under heavy concurrent demand without overselling or compromising transactional consistency.

Designed around real-world flash-sale and fulfillment scenarios, the project focuses on database concurrency control, reservation lifecycles, transactional integrity and asynchronous processing.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.12" />
  <img src="https://img.shields.io/badge/Django-5.2-092E20?style=flat-square&logo=django&logoColor=white" alt="Django 5.2" />
  <img src="https://img.shields.io/badge/Status-In%20Development-orange?style=flat-square" alt="In Development" />
  <img src="https://img.shields.io/github/last-commit/Bh3ky/mwenendo-core?style=flat-square&color=blue" alt="Last commit" />
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/Bh3ky/mwenendo-core?style=flat-square&logo=github" alt="GitHub stars" />
  <img src="https://img.shields.io/github/forks/Bh3ky/mwenendo-core?style=flat-square&logo=github" alt="GitHub forks" />
  <img src="https://img.shields.io/github/issues/Bh3ky/mwenendo-core?style=flat-square" alt="GitHub issues" />
</p>



## The Problem

Imagine a limited product launch with only 100 units available and thousands of customers attempting to purchase simultaneously.

When multiple requests attempt to read and update inventory at the same time, poorly designed systems can allocate the same units more than once.

This creates several engineering challenges:

- **Race conditions:** Concurrent requests compete to modify the same inventory records.
- **Overselling:** More units are allocated than physically available.
- **State inconsistencies:** Abandoned checkouts and failed operations leave reservations in an inconsistent state.
- **Duplicate operations:** Network retries can cause the same reservation operation to execute multiple times.

Mwenendo Core aims to address these challenges through database-enforced consistency, controlled reservation state transitions and asynchronous background processing.

## Engineering Objectives

The system is being designed around the following principles:

- **Transactional integrity:** Inventory changes must remain consistent through successful commits and failed transactions.
- **Concurrency control:** Competing reservation requests must not allocate more stock than is available.
- **Deterministic state management:** Reservations must follow explicitly defined lifecycle transitions.
- **Idempotency:** Repeated requests must not produce duplicate allocations or stock releases.
- **Asynchronous processing:** Background workers will handle reservation expiry and other non-critical operations.
- **Measurable performance:** Load testing will establish throughput, latency and reliability under increasing demand.

## Architecture & Technology

| Component | Technology | Responsibility |
|---|---|---|
| Backend framework | Django 5.2 | Application structure and business logic |
| API layer | Django Ninja | Typed REST API interfaces |
| Database | PostgreSQL 16+ | Persistent inventory and transactional consistency |
| Task queue | Celery | Background task execution |
| Message broker | Redis | Task queuing and coordination |
| Testing | pytest-django | Application and database testing |
| Test data | Factory Boy | Reproducible test data generation |
| Load testing | Locust | Concurrent request simulation |

> *Note: Django, Django Ninja, PostgreSQL, pytest, Factory Boy, Locust, Celery, Redis and CI are in place. The remaining roadmap items follow incrementally; see the [roadmap](docs/ROADMAP.md).*

## Core Design

### Inventory Allocation

Competing requests for the same inventory are coordinated by PostgreSQL's row-level locking. Allocation is a single conditional `UPDATE` that checks and writes in one statement, so two requests cannot both claim the last units. `SELECT FOR UPDATE` is the alternative for when a decision needs more than the counter. A threaded test covers both. See [ADR-0008](docs/adr/0008-conditional-update-for-concurrent-allocation.md).

The central invariant is:

`allocated_quantity <= total_quantity`

This invariant must hold regardless of the number of competing reservation requests.

### Reservation Lifecycle

Reservations will follow a controlled finite state machine.

Planned states:

- `PENDING`
- `HELD`
- `CONFIRMED`
- `EXPIRED`
- `CANCELLED`

Each transition will have explicit validation and corresponding inventory effects.

### Asynchronous Processing

Celery workers expire overdue reservations and give their stock back, using a delayed task per reservation and a periodic sweep as a safety net. See [ADR-0012](docs/adr/0012-reservation-expiry.md).

PostgreSQL will remain the authoritative source of inventory state.

## Development Roadmap

- [x] Django project foundation
- [x] Initial application and URL configuration
- [x] Basic landing page
- [x] Health-check endpoint
- [x] Environment configuration, PostgreSQL, testing and CI
- [x] Database modelling and inventory management
- [x] Reservation API
- [x] Transaction management and row-level locking
- [ ] Reservation state machine and idempotency
- [x] Celery and Redis integration
- [x] Locust load testing and performance benchmarking
- [ ] Dockerisation and production deployment

See the [full roadmap](docs/ROADMAP.md) for the detailed milestones.

## Getting Started

### Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- [Docker](https://docs.docker.com/get-docker/) with Docker Compose

### Installation

Clone the repository:

```bash
git clone https://github.com/Bh3ky/mwenendo-core.git
cd mwenendo-core
```

Create your environment file:

```bash
cp .env.example .env
```

Replace the `change-me` placeholders in `.env`. Generate a value for `SECRET_KEY` and for `POSTGRES_PASSWORD` with:

```bash
uv run python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Set the `POSTGRES_*` values before the first `docker compose up`. The database reads them only once, when it first creates its data volume, so changing them later does not change the existing password.

Start PostgreSQL and wait until its status is `healthy`:

```bash
docker compose up -d
docker compose ps
```

Install dependencies:

```bash
uv sync
```

Apply database migrations:

```bash
uv run python manage.py migrate
```

Start the development server:

```bash
uv run python manage.py runserver
```

The application will be available at:

- Landing page: `http://127.0.0.1:8000/`
- Health check: `http://127.0.0.1:8000/health/`

## Testing

Run the tests and linters (PostgreSQL must be running):

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Tests run against a temporary `test_` database that is created and dropped automatically. They never touch the development database. The same checks run in CI on every pull request.

Concurrency and load tests will be introduced as the core functionality develops. The testing strategy will eventually cover:

- Inventory allocation correctness.
- Transaction rollback behaviour.
- Concurrent reservation requests.
- Duplicate request handling.
- Reservation expiry and stock release.
- Throughput and latency under load.

## Project Philosophy

Mwenendo Core is an exploration of the engineering principles behind reliable, high-concurrency backend systems.

The emphasis is not simply on processing more requests, but on maintaining correctness when multiple operations compete for the same limited resources.

The project is being developed incrementally, with an emphasis on understanding database internals, documenting architectural decisions and validating system behaviour through testing and measurable performance benchmarks.

## License

Licensed under MIT.
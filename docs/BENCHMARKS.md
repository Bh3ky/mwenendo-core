# Benchmarks

Load tests for the reservation API, using the scenarios in
[loadtests/](../loadtests/README.md). They answer two questions: does the system
stay **correct** under concurrent load, and what does contention on one
inventory row **cost**?

Read the [limits](#limits-of-these-numbers) before quoting any figure.

## Setup

| | |
|---|---|
| Machine | Apple M1 Pro, 8 cores, 16 GB |
| Database | PostgreSQL 17 in Docker, a separate `mwenendo_bench` database |
| Server | `manage.py runserver --noreload`, one process, `DEBUG=False` |
| Load generator | Locust 2.47, on the same machine as the server and database |
| Load | 50 simulated users, 25 started per second, 30 seconds per scenario |
| User behaviour | 5 reads, 3 reservations (each with a fresh `Idempotency-Key`), 1 cancel, weighted per task, with a 0.05 to 0.2 s pause |

Scenarios:

- **Hot row:** every user works on one product (`HOT-0`, 1,000,000 units), so every
  write fights for the same inventory row.
- **Spread:** users spread over 50 products (100,000 units each), so writes rarely meet.
- **Sell-out:** every user works on one product with only 500 units, so most
  reservations are refused once stock runs out.

## Results

Response times in milliseconds, from Locust's percentile table.

| Scenario | Requests | Throughput | Failed |
|---|---|---|---|
| Hot row | 6,973 | 234 req/s | 15 (0.22%) |
| Spread | 7,331 | 247 req/s | 16 (0.22%) |
| Sell-out | 7,326 | 246 req/s | 21 (0.29%) |

Reserving (`POST /products/{sku}/reservations`):

| Scenario | p50 | p95 | p99 |
|---|---|---|---|
| Hot row | 120 | 350 | 570 |
| Spread | 89 | 190 | 260 |
| Sell-out | 95 | 270 | 430 |

Reading (`GET /products/{sku}/inventory`):

| Scenario | p50 | p95 | p99 |
|---|---|---|---|
| Hot row | 26 | 69 | 120 |
| Spread | 44 | 120 | 200 |
| Sell-out | 33 | 88 | 130 |

## Correctness after the runs

Speed does not count if the data is wrong, so every run was followed by
`reconcile_stock` and a check of the reservation invariant.

| Check | Result |
|---|---|
| `reconcile_stock` after each run | "All inventories reconcile" every time |
| Hot row: allocated vs sum of active reservations | 1,532 = 1,532 |
| Sell-out: 500 units, 1,246 reservations created, 747 cancelled | 499 allocated, 499 active, never above 500 |
| `allocated_quantity <= total_quantity` | held in every scenario |
| Server log over all three runs | 5,919 responses of 201, 1,190 of 409, no 5xx, no tracebacks |

## What the numbers say

1. **No oversell and no lost ledger rows under 50 concurrent users.** The sell-out
   run is the strongest evidence: 500 units, 50 users competing, and stock never
   went above its limit.
2. **Throughput is flat across scenarios (about 235 to 247 req/s).** Spreading
   the load over 50 products did not make it faster, so the ceiling here is the
   single-process server and the load generator sharing one machine, not the
   inventory row.
3. **Contention shows up in the tail.** Reserving at p95 is 350 ms on the hot
   row against 190 ms spread, and p99 is 570 against 260. Writers queue on one
   row lock, which is the cost ADR-0008 accepted.
4. **A small share of requests failed (0.2 to 0.3%)**, all as connection resets
   or dropped connections. The server log shows no application errors. This looks
   like the development server shedding load, but I did not confirm the cause.

## Limits of these numbers

- **One 30-second run per scenario.** There is no repeat, so no measure of
  run-to-run variation. Treat differences of a few percent as noise.
- **A single-process development server**, not a production server. These
  figures are a floor, not what the application can do behind gunicorn or
  similar.
- **Load generator, server and database share one machine**, so they compete
  for the same CPU.
- **The cost of the ledger was not measured.** It would need the same run
  against the code from before the ledger, and I did not do that. ADR-0011
  expects one extra insert per stock operation.
- **Short runs on a small dataset.** Nothing here says how the ledger table or
  the reservations table behave when large.
- The 50-user, 3-weights mix is a guess at traffic, not a measured workload.

## Reproducing

See [loadtests/README.md](../loadtests/README.md). Always use a separate benchmark
database: `seed_benchmark` refuses to run on any database whose name does not
contain `bench`.

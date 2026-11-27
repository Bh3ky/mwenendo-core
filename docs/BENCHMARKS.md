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

## Behind gunicorn, and what reusing database connections is worth

The first set of runs above used Django's development server. These were run later
against **gunicorn with 4 worker processes** (`DEBUG=False`), on the same laptop and the
same three scenarios, 50 users, 30 seconds each. The only thing that differs between the
two settings is Django's `CONN_MAX_AGE`: **60** keeps each worker's database connection
open between requests, and **0** opens a new connection for every request (ADR-0016). The
settings alternated (60, 0, 60, 0), and each setting was run twice. `reconcile_stock`
passed after every run, so no stock was lost or oversold in any of them.

Response times in milliseconds. "Failed" is the share of requests that got a 500.

| Scenario | Connections | Run | Requests/s | Failed | Reserve p50 | p95 | p99 |
|---|---|---|---|---|---|---|---|
| Hot row | kept open | 1 | 342 | 0% | 15 | 60 | 220 |
| Hot row | kept open | 2 | 358 | 0% | 14 | 34 | 72 |
| Hot row | new each request | 1 | 197 | 0% | 120 | 200 | 240 |
| Hot row | new each request | 2 | 210 | 0% | 110 | 190 | 320 |
| Spread | kept open | 1 | 352 | 0% | 12 | 47 | 140 |
| Spread | kept open | 2 | 363 | 0% | 12 | 27 | 61 |
| Spread | new each request | 1 | 202 | **21%** | 120 | 270 | 560 |
| Spread | new each request | 2 | 257 | **43%** | 77 | 160 | 230 |
| Sell-out | kept open | 1 | 360 | 0% | 12 | 35 | 74 |
| Sell-out | kept open | 2 | 352 | 0% | 12 | 40 | 130 |
| Sell-out | new each request | 1 | 209 | **17%** | 110 | 200 | 470 |
| Sell-out | new each request | 2 | 227 | **18%** | 92 | 140 | 360 |

Server errors (5xx) over a whole run, from the server's own log: **0 and 0** with
connections kept open (about 31,000 and 32,000 requests), against **2,544 and 4,713**
with a new connection per request (about 18,000 and 21,000 requests).

What this shows:

1. **Keeping connections open was clearly better here, and the result repeated.** In the
   hot-row scenario, where nothing failed in either setting, throughput was 342 and 358
   requests per second against 197 and 210, and the median reserve time was about
   14 ms against about 115 ms. Both pairs agree within about 5%, so the gap of roughly
   70% is far outside the run-to-run variation I could see.
2. **A new connection per request also produced errors under load,** in the spread and
   sell-out scenarios (17% to 43% of requests failed). The errors were TCP-level:
   "connection refused" and "server closed the connection unexpectedly". PostgreSQL's own
   log showed no matching error and it never came near its limit of 100 connections.
3. **I do not know why the errors happen, and I am not claiming to.** My guess is that on
   a Mac, "localhost" reaches the database through Docker Desktop's port forwarding, which
   may not cope with a few hundred brand-new connections per second. I did not test that.
   A Linux server connects without that layer, so the errors may not appear there, though
   the cost of opening a connection would still apply.
4. **Compared with the development-server runs above,** the hot row went from 234 to
   about 350 requests per second and the reserve p95 from 350 ms to between 34 and 60 ms.
   That compares two changes at once (a real server, and reused connections), because the
   development-server runs also opened a connection per request, so I cannot say how much
   each contributed.
5. **Correctness did not depend on any of this.** Every run, including the failing ones,
   ended with the ledger agreeing with the counters.

## Limits of these numbers

- **One 30-second run per scenario in the first set** (development server), so no
  measure of variation there. The gunicorn comparison was run twice per setting, which
  shows the direction repeats but is still a small sample.
- **The first set used a single-process development server**, so those figures are a
  floor. The gunicorn set is closer to a real server, but it is still one laptop.
- **Docker Desktop's network layer is in the path** to PostgreSQL on a Mac. It may be
  the cause of the connection errors above, and it would not exist on a Linux server.
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

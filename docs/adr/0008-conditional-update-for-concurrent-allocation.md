# ADR-0008: Guard concurrent allocation with a conditional UPDATE

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 4

## Context

Many requests can try to reserve the same product at once. The question each one asks is whether enough stock is unallocated, and the answer changes as other requests succeed. If the check and the write are separate steps, two requests can both pass the check and both write (a lost update).

We demonstrated this. A deliberately naive version (read the row, check in Python, add one, `save()`) was run by 30 threads against a stock of 10. It created 30 reservations while the counter said 1. The `allocated_quantity <= total_quantity` `CHECK` (ADR-0004) never fired, because lost updates keep the counter low and valid. A constraint alone does not protect this invariant.

The hot spot is a single counter on a single row (ADR-0003). The decision is where the check and the write happen, and how competing requests are made to wait for each other.

## Options considered

1. **Conditional `UPDATE`:** one statement, `UPDATE ... SET allocated = allocated + n WHERE id = X AND total >= allocated + n`. Zero rows updated means the request is rejected.
   - Pros: check and write are one atomic statement. The row lock is held only for the length of that statement. A losing request gets an immediate, clean answer.
   - Cons: only works while the decision can be expressed in SQL on that row. It relies on PostgreSQL's behaviour in `READ COMMITTED` (see Consequences).
2. **Pessimistic locking with `select_for_update()`:** lock the row, read it, decide in Python, write, commit.
   - Pros: the decision can use any Python logic and any number of reads, and it works across several rows.
   - Cons: the lock is held from the `SELECT` until commit, with application code running in between. That limits throughput on a hot row, and locking several rows can deadlock unless they are always locked in the same order.
3. **Optimistic locking:** a version column. Write with `WHERE version = N`, and retry when zero rows are updated.
   - Pros: no lock is held while thinking, which suits rare conflicts.
   - Cons: every conflict becomes a retry, and on a hot row most requests would conflict. It also adds a column and retry code.

## Decision

Use the **conditional `UPDATE`** (option 1) for allocation, as `allocate_stock` and `remove_stock` already do. The reservation insert shares its transaction (ADR-0007), so a failed insert rolls the counter back.

Evidence: `test_concurrent_reservations_never_oversell` runs 30 threads, released together by a barrier, against a stock of 10. Exactly 10 succeed, 20 are rejected with `InsufficientStock`, the counter is 10, and there are 10 reservation rows. The same harness breaks the naive version, so it can detect the bug.

## Consequences

- **Good:**
  - No lost updates and no oversell, with no retry logic.
  - The lock is held for one statement, the shortest practical time.
  - Losing requests fail fast with a message the client can act on (a 409).
- **Bad / trade-offs:**
  - The guarantee depends on PostgreSQL's default `READ COMMITTED` behaviour: an `UPDATE` that had to wait for a concurrent update re-checks its `WHERE` against the newest committed row. Under `REPEATABLE READ` the same collision raises "could not serialize access due to concurrent update", and the code would need retries. The project does not set an isolation level, so it runs on the default.
  - A passing concurrent test is evidence, not proof, because races can hide. The test's value comes from the naive version failing in the same harness. A later load test (Milestone 7) will exercise it harder.
  - A failed `UPDATE` followed by a `SELECT` for the error message means the numbers in a 409 are a snapshot and may be slightly stale. The stored data is not affected.
  - Under heavy demand for one product, requests queue on one row lock. Milestone 7 will measure whether this matters.
- **Revisit when:**
  - A reservation must read more than the counter before deciding (per-customer limits, rules across several inventory rows, logic over other reservations). That is the point to move to `select_for_update()`, with a fixed lock order across rows.
  - The isolation level is changed from the default.
  - Load tests show contention on the counter row is a bottleneck.

## References

- [PostgreSQL: Transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html) (the Read Committed and Repeatable Read sections)
- [PostgreSQL: Explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [Django: `select_for_update()`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update)
- [Django: database transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- ADR-0003: Represent stock as counters on an Inventory row
- ADR-0004: Enforce `allocated_quantity <= total_quantity` in the database and in code
- ADR-0007: Reservations hold stock in the same transaction as the counter

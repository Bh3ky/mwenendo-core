# ADR-0011: An append-only stock ledger alongside the counters

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 5

## Context

Stock is two counters on an `Inventory` row (ADR-0003), and every operation overwrites them. That is fast and race-safe (ADR-0008), but the history is lost. If a number looks wrong we cannot say how it got there, and nothing proves that the counters are right. `add_stock` and `remove_stock` leave no record at all, and reservations only explain the allocated part.

ADR-0003 deferred a ledger to Milestone 5. This ADR adds one without replacing the counters.

## Options considered

1. **Counters plus an append-only ledger:** keep the counters for fast reads, and insert a ledger row for every change in the same transaction.
   - Pros: reads stay cheap, the history is complete, and the two can be checked against each other.
   - Cons: one extra insert per operation, and two representations of the same fact that must agree.
2. **Ledger as the only source of truth:** derive the counters by summing the ledger.
   - Pros: one source of truth, and no way for two numbers to drift.
   - Cons: every read aggregates, and the conditional `UPDATE` that guards allocation (ADR-0008) would have to be redesigned. A much larger change.
3. **No ledger.**
   - Pros: nothing to build.
   - Cons: no audit trail and no way to detect a change made outside the services.

## Decision

- **Option 1.** A `StockMovement` row has `inventory` (FK, `PROTECT`), `total_delta` and `allocated_delta` (signed), a `reason` (`opening_balance`, `stock_added`, `stock_removed`, `reserved`, `released`), an optional `reservation_public_id` and `created_at`. A `CHECK` forbids a movement where both deltas are zero.
- **Same transaction.** `add_stock`, `remove_stock`, `allocate_stock` and `release_stock` each wrap the counter update and the ledger insert in `transaction.atomic()`. If either fails, both roll back. A rejected operation writes nothing.
- **Reservation link is loose.** `reservation_public_id` is a plain UUID, not a foreign key, so the `inventory` app does not depend on `reservations` (ADR-0002). `reserve_stock` generates the reservation's UUID before allocating, so the ledger row can refer to it.
- **Append-only by convention and tests.** No code updates or deletes ledger rows, and `PROTECT` stops an inventory with history from being deleted. A database trigger that forbids updates is a stronger option, left for later.
- **Opening balance.** A data migration gives every existing inventory with stock one `opening_balance` row, so existing data reconciles from the start.
- **Reconciliation.** `inventory.reconciliation.find_discrepancies()` compares each inventory's counters with the sum of its deltas. The `reconcile_stock` management command prints any differences and exits with an error, so it can run from cron or CI.

## Consequences

- **Good:**
  - Every stock number can be explained, and every reservation and release can be traced.
  - Any change made outside the services (a direct `UPDATE`, the admin, a bug) shows up as a discrepancy. Tests prove it.
  - The concurrency tests now also check that the ledger agrees with the counters after a race, including that a request that lost an idempotency race rolled its ledger row back with its stock.
- **Bad / trade-offs:**
  - Each operation does one more insert, plus a savepoint when already inside a transaction. The add endpoint now runs 5 real statements, not 3. Milestone 7 (load testing) will measure the cost.
  - The ledger grows without bound. A real system would archive or partition it.
  - Append-only is not enforced by the database yet.
  - Anything that writes counters directly, such as the factories in tests, must also write an opening balance, or it will be reported as a discrepancy. The test factory does this by default.
  - The opening-balance migration is not idempotent. Reversing it (`migrate inventory 0004`) deliberately leaves the rows in place, so applying it again would insert a second opening row per inventory and double the ledger. It had already been applied when this was noticed, and applied migrations are not edited, so the protection is `reconcile_stock`, which reports the doubling. If the ledger has to be reset, the right fix is a new migration, not a re-run.
  - `find_discrepancies()` aggregates over every inventory, which is fine at this size and would need batching for a very large catalogue.
- **Revisit when:**
  - The ledger's write cost or size shows up in load tests.
  - Auditing needs stronger guarantees (a database trigger, or restricted database permissions).
  - We want a single source of truth (option 2).

## References

- [Django: `transaction.atomic()`](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django: writing custom management commands](https://docs.djangoproject.com/en/5.2/howto/custom-management-commands/)
- [Django: data migrations](https://docs.djangoproject.com/en/5.2/topics/migrations/#data-migrations)
- ADR-0002: Split into core, inventory and reservations apps
- ADR-0003: Represent stock as counters on an Inventory row
- ADR-0008: Guard concurrent allocation with a conditional UPDATE

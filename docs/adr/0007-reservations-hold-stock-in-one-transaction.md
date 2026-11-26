# ADR-0007: Reservations hold stock in the same transaction as the counter

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 3

## Context

Stock is stored as counters on an `Inventory` row (ADR-0003). A reservation is a record that a quantity of a product is held for someone. Creating one must insert the reservation row and increase `allocated_quantity`. If only one of the two happens, the data disagrees with itself. The model lives in the `reservations` app, and the counter belongs to `inventory` (ADR-0002).

## Options considered

1. **Counter plus reservation row in one transaction:** a conditional update on `allocated_quantity` and the insert inside `transaction.atomic()`.
   - Pros: reads stay cheap, both writes succeed or fail together, and it extends ADR-0003 and ADR-0004.
   - Cons: the invariant `allocated_quantity = sum of quantity over pending and confirmed reservations` must be kept and tested.
2. **No counter:** compute allocated stock as the sum over active reservations.
   - Pros: one source of truth.
   - Cons: every read aggregates, and it reverses ADR-0003.
3. **Counter and row updated as separate steps.**
   - Pros: simple code.
   - Cons: a crash between the steps leaves them inconsistent with no way back.

## Decision

- **Option 1.** A `reserve_stock` service in `reservations` opens `transaction.atomic()`, calls an `allocate_stock` service in `inventory` (a conditional `UPDATE` that raises `InsufficientStock` when `allocated + quantity > total`), then inserts the `Reservation` as `pending`. If the insert fails, the counter update rolls back. The `inventory` app owns the counter, and `reservations` calls its service.
- **Reservation fields now:** `inventory` (FK to `Inventory`, `PROTECT`), `quantity` (positive integer, `CHECK quantity > 0`), `status`, `created_at`, `reference` (a short text identifying the holder, since there is no authentication yet) and `public_id` (UUID, unique).
- **Reservation target:** a FK to `Inventory`, not `Product`, because a reservation is a claim against exactly the row whose counter it changes, and it stays correct if inventory later becomes per-warehouse.
- **States now:** `pending`, `confirmed`, `cancelled`. Transitions are not enforced yet (Milestone 5), and `expired` arrives with expiry (Milestone 6).
- **Fields deferred:** `expires_at` (Milestone 6) and `idempotency_key` (Milestone 5).
- **Public identifier:** a UUID (`public_id`), with the integer primary key kept internal. A UUID is hard to guess, but it is not access control, so authorisation is still needed once authentication exists.
- **Endpoints:** `POST /api/products/{sku}/reservations` returns 201 (409 on insufficient stock, 404 for an unknown SKU, 422 for a bad body), and `GET /api/reservations/{public_id}` returns the reservation, 404 for an unknown one, or 422 for a malformed ID. The quantity uses the same strict, bounded schema as the stock endpoints (ADR-0006).

## Consequences

- **Good:**
  - The counter and the reservation cannot drift apart through a partial failure. A test forces the insert to fail after the counter update and checks that the counter is restored.
  - The database `CHECK` constraints still guard the invariant (ADR-0004).
  - Retrieval does not expose guessable sequential IDs.
- **Bad / trade-offs:**
  - Two stores of the same fact (counter and rows) must be kept consistent and tested. A test checks that the counter equals the sum over reservations after several reserves.
  - Cancelling or expiring a reservation must reverse the counter change in the same transaction (Milestones 5 and 6).
  - A UUID is larger than an integer and harder to read in logs.
  - The conditional update is atomic per statement, but we have not yet tested this under concurrent requests. Milestone 4 does that and decides whether `select_for_update()` is needed.
- **Revisit when:**
  - Concurrency tests show the counter and the reservations can diverge.
  - Per-warehouse inventory is introduced.
  - Reservation volume makes the counter a contention hotspot.

## References

- [Django: `transaction.atomic()`](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [Django: `UUIDField`](https://docs.djangoproject.com/en/5.2/ref/models/fields/#uuidfield)
- [PostgreSQL: Transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- ADR-0002: Split into core, inventory and reservations apps
- ADR-0003: Represent stock as counters on an Inventory row
- ADR-0004: Enforce `allocated_quantity <= total_quantity` in the database and in code
- ADR-0006: Shape of the stock API

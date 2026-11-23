# ADR-0003: Represent stock as counters on an Inventory row

- **Status:** Accepted
- **Date:** 2026-11-18
- **Roadmap milestone:** Milestone 2

## Context

The project's central invariant is `allocated_quantity <= total_quantity`. The stock model decides how that invariant is stored, enforced and, later, protected under concurrent requests.

Two forces apply:

- The invariant must be enforceable by the database itself, not only by application code.
- Milestone 4 introduces row-level locking (`select_for_update()`), which needs a single, obvious row to lock for each product.

Later milestones (reservation lifecycle, idempotency, expiry) will also affect stock, but their requirements are not yet known.

## Options considered

1. **Counters:** one `Inventory` row per product with `total_quantity` and `allocated_quantity`. Allocation updates the numbers.
   - Pros: simple, instant reads, and the invariant is a plain `CHECK` constraint. The row to lock is obvious.
   - Cons: no history. If a bug changes a number, the cause cannot be reconstructed.

2. **Append-only ledger:** `StockMovement` rows (received, reserved, released, ...), with stock computed as a sum.
   - Pros: full audit trail, natural fit for idempotency, state can be rebuilt.
   - Cons: a `CHECK` constraint cannot enforce a rule over a sum of other rows, so the invariant would need triggers or a locked counter anyway. Reads are slower and the code is larger.

3. **Hybrid:** counters as the authoritative, constrained state, plus an append-only movement table for audit.
   - Pros: fast, safe and auditable.
   - Cons: every stock change is two writes that must succeed or fail together, which relies on transaction handling not yet built. The ledger's shape depends on reservation types and idempotency keys that do not exist yet, so it would be designed without enough information.

## Decision

Use **counters** (option 1): an `Inventory` row per product holding `total_quantity` and `allocated_quantity`, with the invariant enforced by database `CHECK` constraints (see ADR-0004).

The ledger is deliberately deferred, not rejected. Moving from counters to the hybrid is additive: a movement table is added and written inside the same transaction as the counter update, while the counters stay authoritative. It is added to the roadmap as a Milestone 5 item, to be designed once the reservation lifecycle and idempotency requirements are known.

## Consequences

- **Good:**
  - The invariant is a one-line database constraint.
  - There is one obvious row to lock per product in Milestone 4.
  - Each concept is learned before it is used.
- **Bad / trade-offs:**
  - No audit history in the meantime. A wrong counter cannot be explained or reconstructed.
  - Tests and logs must carry the weight of diagnosing allocation bugs until a ledger exists.
- **Revisit when:**
  - The reservation lifecycle (Milestone 5) is defined, since the movement types and their links to reservations can then be designed from real requirements.
  - Auditing or reconciliation becomes a requirement, or an allocation bug cannot be diagnosed from existing data.

## References

- [PostgreSQL: Check constraints](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-CHECK-CONSTRAINTS)
- [PostgreSQL: Explicit locking (row-level locks)](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS)
- ADR-0001: Use PostgreSQL as the database

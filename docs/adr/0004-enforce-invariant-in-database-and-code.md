# ADR-0004: Enforce `allocated_quantity <= total_quantity` in the database and in code

- **Status:** Accepted
- **Date:** 2026-11-23
- **Roadmap milestone:** Milestone 2

## Context

The project's central invariant is `allocated_quantity <= total_quantity` (see ADR-0003, which stores stock as counters on an `Inventory` row). The question is where that rule is enforced.

Writes to an inventory row can come from many places: application code, the Django admin, `manage.py shell`, `QuerySet.update()` and `bulk_update()` (which skip `save()` and any Python validation), raw SQL, future import scripts, and, from Milestone 4, concurrent requests that read the same row at the same moment. A rule that lives in only one of those paths is not a guarantee.

The rule compares two columns of the same row, so PostgreSQL can express it as a `CHECK` constraint.

## Options considered

1. **Code only:** validate in Python before saving.
   - Pros: clear, readable errors.
   - Cons: any write that bypasses that code can break the invariant. A test using `QuerySet.update()` demonstrates the gap, and concurrent requests make the same check-then-write race.

2. **Database only:** rely on a `CHECK` constraint and let `IntegrityError` propagate.
   - Pros: cannot be bypassed, whatever the source of the write.
   - Cons: the error is a raw database error that callers must interpret, and every caller would need to know the constraint's name.

3. **Both:** a `CHECK` constraint as the guarantee, plus Python checks that raise clear domain errors before the write.
   - Pros: correctness does not depend on callers behaving, and failures are still readable.
   - Cons: the rule exists in two places, which must be kept in sync, and the Python check is advisory (it can race).

## Decision

Use **both** (option 3):

- A database constraint, `inventory_allocated_lte_total`, declared on the `Inventory` model's `Meta.constraints`. It is the source of truth.
- Python-level checks in the stock-management functions, which raise a clear domain error for operations that would violate the rule. These exist to produce good messages, not to provide safety.

Safety never relies on the Python check. If the two ever disagree, the database wins.

## Consequences

- **Good:**
  - The invariant holds for every write path, including ones that skip Python validation.
  - Tests can prove it directly: inserts and `update()` calls that break the rule are rejected, and a failed write leaves the row unchanged.
  - The constraint name appears in the error, so tests and logs can say which rule fired.
- **Bad / trade-offs:**
  - Two places express the same rule, and both need tests.
  - A Python check followed by a write is a read-then-write, so two concurrent requests can both pass the check. The constraint still prevents a bad state, but one of them will then fail with an `IntegrityError`. Milestone 4 addresses the race itself with row locking.
  - Adding such a constraint to a table that already has rows makes PostgreSQL validate every existing row, which on a large production table can block writes. Check the data first, and consider adding it as `NOT VALID` and validating separately.
- **Revisit when:**
  - The invariant becomes more complex than a single-row condition (for example, one that depends on other rows), where a `CHECK` is no longer enough and a trigger or a locked counter is needed.

## References

- [PostgreSQL: Check constraints](https://www.postgresql.org/docs/current/ddl-constraints.html#DDL-CONSTRAINTS-CHECK-CONSTRAINTS)
- [Django: `CheckConstraint`](https://docs.djangoproject.com/en/5.2/ref/models/constraints/#checkconstraint)
- ADR-0003: Represent stock as counters on an Inventory row

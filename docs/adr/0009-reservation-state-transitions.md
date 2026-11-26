# ADR-0009: Reservation state transitions are a table enforced by a conditional UPDATE

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 5

## Context

A reservation has three states (ADR-0007): `pending`, `confirmed` and `cancelled`. We need to say which moves are allowed, reject the rest, and make cancelling give the stock back. Two requests can try to change the same reservation at once, for example two cancels. If both succeed, the stock is released twice and `allocated_quantity` stops matching the active reservations (ADR-0007), or goes negative.

## Options considered

1. **A transitions table in the service layer:** a dictionary of from-state to allowed to-states, and a conditional `UPDATE ... WHERE status IN (allowed from-states)` to apply a move.
   - Pros: no dependency. The rules are readable in one place, and the same conditional-update pattern as ADR-0008 makes the check and the write one statement.
   - Cons: the table is hand-written, and there is no built-in support for guards, hooks or audit logging.
2. **A state-machine library** (for example `django-fsm-2`, the maintained fork of the archived `django-fsm`).
   - Pros: declarative transitions, signals and admin integration.
   - Cons: a new dependency (RULES.md asks for a conscious choice). The common pattern changes the field in Python and saves, which is the read-modify-write race we already saw, so we would still need the conditional `UPDATE` underneath. With three states and two moves the library adds more than it removes.
3. **Checks in Python, then `save()`.**
   - Pros: simplest code.
   - Cons: two simultaneous cancels both read `pending`, both pass the check, and both release stock.

## Decision

- **Option 1.** `ALLOWED_TRANSITIONS` in `reservations/services.py` is the single source of truth: `pending` goes to `confirmed` or `cancelled`, `confirmed` goes to `cancelled`, `cancelled` is final.
- **A move is one conditional `UPDATE`** (`WHERE pk = X AND status IN (states that may move to the target)`). Zero rows updated means the move was illegal (raise `InvalidTransition`, a 409) or the row is gone (raise `DoesNotExist`, a 404).
- **Cancelling releases stock in the same transaction.** `cancel_reservation` opens `transaction.atomic()`, wins the status change first, then calls `release_stock` in `inventory`. Only the request that wins the status change reaches the release, so stock is released at most once. If the release fails, the status change rolls back.
- **Endpoints:** `POST /api/reservations/{public_id}/confirm` and `.../cancel`, returning the reservation (200), 409 for an illegal move, 404 for an unknown reservation, and 422 for a malformed ID.
- **Confirming keeps the stock allocated.** Only cancelling releases it.

Evidence: a threaded test sends ten simultaneous cancels for one reservation. Exactly one succeeds, nine are rejected, and `allocated_quantity` drops by the reservation's quantity once.

## Consequences

- **Good:**
  - The lifecycle rules are visible in one table, and illegal moves cannot happen even under concurrency.
  - No new dependency.
  - The counter invariant from ADR-0007 holds through cancellation.
- **Bad / trade-offs:**
  - There are no transition hooks, history or audit trail yet. A stock-movement ledger (Milestone 5) would give one.
  - Confirm and cancel are not idempotent: repeating one returns a 409, not the earlier result. Idempotency keys (the next piece of Milestone 5) deal with retried requests.
  - Expiry will be a fourth state and a new transition, and must release stock the same way (Milestone 6).
- **Revisit when:**
  - The number of states or guards grows enough that a declarative library saves real work.
  - Transitions need side effects such as notifications or an audit trail.

## References

- [Django: `QuerySet.update()`](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#update)
- [Django: `transaction.atomic()`](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- [PyPI: django-fsm-2](https://pypi.org/project/django-fsm-2)
- ADR-0007: Reservations hold stock in the same transaction as the counter
- ADR-0008: Guard concurrent allocation with a conditional UPDATE

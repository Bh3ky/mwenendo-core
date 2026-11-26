# ADR-0010: Idempotency keys on reservation creation

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 5

## Context

A client that times out cannot tell whether its `POST` created a reservation. If it retries, a plain endpoint creates a second reservation and holds the stock twice. Retries are normal (network errors, load balancers, background workers), so creation must be safe to repeat.

Confirm and cancel are already safe to repeat: the transitions table (ADR-0009) rejects a second cancel with a 409 and releases stock once. Only creation needs a way to recognise "this is the same request again".

## Options considered

1. **Key stored on the reservation:** an optional `Idempotency-Key` header. The key is saved on the `Reservation` row under a unique constraint.
   - Pros: no extra table. The database itself decides which of two simultaneous requests wins. Easy to test.
   - Cons: only covers the creation endpoint. A replay returns the reservation as it is now, not a snapshot of the original response.
2. **A separate idempotency table** that stores the key, a request fingerprint and the saved response, with an expiry.
   - Pros: works for any endpoint, replays return exactly the original response, and keys can expire.
   - Cons: a second table, a cleanup job, and a way to handle requests that are still in flight.
3. **Deduplicate on `reference`** (the client's own identifier).
   - Pros: no new header.
   - Cons: it conflates "same request" with "same reference", and a client may legitimately reserve twice for one reference.

## Decision

- **Option 1.** `Reservation.idempotency_key` is a string, empty when the client sent no key, with a conditional unique constraint (`reservation_idempotency_key_unique`, where the key is not empty).
- **Replay.** If the key already exists and the request matches (same inventory, quantity and reference), `reserve_stock` returns the existing reservation without allocating stock. The API answers `201` with the same body, as the original did.
- **Reuse with a different request** raises `IdempotencyKeyReused`, and the API returns **422**, as the IETF Idempotency-Key header draft suggests for a key reused with a different payload.
- **Simultaneous duplicates.** Two requests with the same key can both miss the lookup. The unique constraint lets only one insert succeed. The loser's `transaction.atomic()` block rolls back its stock allocation, and it then returns the winner's reservation. No lock is needed.
- **Key validation.** The header must be 1 to 255 characters, otherwise 422. A request with no header is not deduplicated.

## Consequences

- **Good:**
  - A retried `POST` cannot hold stock twice, including when retries overlap.
  - The guarantee comes from a database constraint and a rolled-back transaction, in line with ADR-0004 and ADR-0008.
  - A threaded test sends ten simultaneous requests with one key and checks that one reservation exists and the stock is held once.
- **Bad / trade-offs:**
  - A replay returns the reservation's current state, not the original response. If it was cancelled in between, the replay shows `cancelled`.
  - Keys never expire, so they are stored for the life of the reservation.
  - Keys are global. With no authentication, two clients who pick the same key would collide. Once authentication exists, keys should be scoped to the caller.
  - The race branch (catching `IntegrityError` and returning the winner) is hard to trigger on purpose. The concurrency test would pass through the earlier lookup in many runs, so it does not prove that branch alone.
- **Revisit when:**
  - Other endpoints need idempotency, or replays must return the exact original response (option 2).
  - Authentication is added (scope keys per caller).
  - Key storage needs an expiry.

## References

- [IETF draft: The Idempotency-Key HTTP Header Field](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)
- [Django: `UniqueConstraint` with a condition](https://docs.djangoproject.com/en/5.2/ref/models/constraints/#uniqueconstraint)
- [Django: `transaction.atomic()`](https://docs.djangoproject.com/en/5.2/topics/db/transactions/)
- ADR-0004: Enforce `allocated_quantity <= total_quantity` in the database and in code
- ADR-0007: Reservations hold stock in the same transaction as the counter
- ADR-0009: Reservation state transitions are a table enforced by a conditional UPDATE

# ADR-0012: Reservation expiry with a delayed task and a periodic sweep

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 6

## Context

A pending reservation holds stock until someone confirms or cancels it. If nobody does, the stock is held forever. Something has to expire overdue reservations and give their stock back.

Expiry competes with other actions. A client may confirm at the moment the deadline passes, a worker may run a task twice, and a task may run early, late or never (a crashed worker, a lost queue).

## Options considered

1. **Periodic sweep only:** a Celery beat task runs every minute and expires everything overdue.
   - Pros: simple, and it heals itself, because anything missed is caught on the next run.
   - Cons: expiry can be up to a minute late, and the sweep does work even when nothing is due.
2. **One delayed task per reservation**, scheduled when it is created.
   - Pros: precise.
   - Cons: if the broker loses the queue or is down at scheduling time, those reservations never expire.
3. **Both:** a delayed task for precision, and the sweep as a safety net.
   - Pros: precise in the normal case, and correct even when tasks are lost.
   - Cons: two code paths, which must be safe to run together.

## Decision

- **Option 3.** `reserve_stock` sets `expires_at` (now plus `RESERVATION_TTL_MINUTES`, 15 by default) and schedules `expire_reservation_task` with `transaction.on_commit`, so the task cannot fire before the reservation is committed. If scheduling fails (the broker is down), the error is logged and the reservation stands. The sweep, `expire_overdue_reservations`, runs every 60 seconds and handles anything missed.
- **A fourth state, `expired`,** reachable only from `pending` and final (`ALLOWED_TRANSITIONS`, ADR-0009). Confirmed reservations never expire.
- **The clock is part of the conditional update.** Expiring is `UPDATE ... WHERE status = 'pending' AND expires_at <= now`. A task that runs early, or twice, matches nothing. Of two competing expiries only one releases stock, as with cancel (ADR-0009).
- **Confirming respects the deadline.** Confirm only matches a reservation that has no deadline or is still inside it, so a client cannot confirm in the gap before the sweep gets to an overdue reservation. The API returns 409.
- **`expires_at` is nullable.** Null means "never expires", which is how reservations made before expiry existed behave. They are not backfilled, because expiring them all at once would release stock nobody asked to release.
- **The sweep is bounded and isolated.** It expires at most 500 per run, ordered by deadline, and a failing reservation is logged and skipped so it cannot block the rest.
- **Retries.** The expiry task retries on `OperationalError` with exponential backoff, at most 5 times. It is safe to repeat. Tasks are acknowledged late (`CELERY_TASK_ACKS_LATE`), so a task is not lost if a worker dies mid-run.
- **Tests run tasks inline** (Celery's eager mode), so the test suite and CI need no Redis. Redis and a real worker are only needed for a manual run.

## Consequences

- **Good:**
  - Stock cannot stay held indefinitely, even if the broker loses every queued task.
  - Expiry, cancel and confirm cannot double-release stock or both win, because each is one conditional `UPDATE`. A threaded test sends ten simultaneous expiries and checks that stock is released once.
  - A broker outage does not break reservation creation.
- **Bad / trade-offs:**
  - A reservation can sit overdue for up to a minute before the sweep, if its own task was lost. It cannot be confirmed in that window, but it still holds stock.
  - The sweep queries every minute even when nothing is due. An index on `(status, expires_at)` would help once the table is large, and none has been added yet.
  - The retry and late-acknowledgement settings are configured but not exercised by automated tests. Only a real worker can show them working.
  - On a duplicate idempotency-key race, the loser's rolled-back transaction does not run its `on_commit` callback, so no stray task is scheduled. This is reasoning from Django's behaviour, not a dedicated test.
  - Scheduling runs in the request thread after the commit. With the broker down, the request may wait on Celery's publish retries before it returns. This is expected from how Celery publishes and has not been measured.
  - There is no outbox. A crash between commit and `apply_async` loses the task, and the sweep recovers it.
- **Revisit when:**
  - The sweep becomes slow (add the index, or shorten the batch).
  - Expiry must be exact to the second (an outbox, or a different scheduler).
  - Reservations need extending ("hold for longer"), which would change `expires_at` and need its own transition rules.

## References

- [Celery: Task retry options](https://docs.celeryq.dev/en/stable/userguide/tasks.html#retrying)
- [Celery: Periodic tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)
- [Celery with Django](https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html)
- [Django: `transaction.on_commit()`](https://docs.djangoproject.com/en/5.2/topics/db/transactions/#performing-actions-after-commit)
- ADR-0009: Reservation state transitions are a table enforced by a conditional UPDATE
- ADR-0010: Idempotency keys on reservation creation

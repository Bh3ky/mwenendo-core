# Manual test: reservation expiry

Automated tests run Celery tasks inline, so they cannot show a real worker, Redis
and the beat scheduler working together. This walks through that by hand. It uses
your development database, which is fine here: it adds a few reservations and
nothing destructive happens.

You need four terminals in the project folder.

## 0. Setup

1. Start Redis: `docker compose up -d redis`, then `docker compose ps` should show
   `redis` as healthy.
2. In `.env`, add a short deadline so you don't wait 15 minutes:
   `RESERVATION_TTL_MINUTES=1` and `REDIS_URL=redis://localhost:6379/0`.
3. `uv run python manage.py migrate` (applies `reservations.0003_expiry`).

## 1. Start the processes

| Terminal | Command |
|---|---|
| A | `uv run python manage.py runserver` |
| B | `uv run celery -A config worker -l info` |
| C | `uv run celery -A config beat -l info` |
| D | for the curl commands below |

Terminal B should list `reservations.tasks.expire_reservation_task` and
`reservations.tasks.expire_overdue_reservations` under `[tasks]`. If it does not,
Celery did not find the tasks.

## 2. The normal path: the delayed task expires it

```bash
curl -s -X POST http://127.0.0.1:8000/api/products/DEMO-1/reservations \
  -H "Content-Type: application/json" \
  -d '{"quantity": 1, "reference": "manual-test"}'
curl -s http://127.0.0.1:8000/api/products/DEMO-1/inventory
```

Expect: `201`, a `status` of `pending`, an `expires_at` about one minute ahead, and
`allocated_quantity` up by 1. Terminal B shows a task received with an ETA.
After about a minute and a second, terminal B shows
`expire_reservation_task ... succeeded ... True`. Then:

```bash
curl -s http://127.0.0.1:8000/api/reservations/<id-from-above>
curl -s http://127.0.0.1:8000/api/products/DEMO-1/inventory
```

Expect `status: expired`, and `allocated_quantity` back where it started.

## 3. Confirmed reservations don't expire

Reserve again, confirm it straight away
(`curl -s -X POST http://127.0.0.1:8000/api/reservations/<id>/confirm`), and wait
past the deadline. It should stay `confirmed`, and the stock stays allocated.

## 4. Confirming after the deadline is refused

Stop the worker and beat (Ctrl+C in terminals B and C), so nothing can expire
anything. Reserve, wait until `expires_at` has passed, then try to confirm:

```bash
curl -s -X POST http://127.0.0.1:8000/api/reservations/<id>/confirm
```

Expect `409` with a message that the reservation has expired. A GET still shows
`pending` and the stock is still allocated, because nothing has processed it yet.

Now restart the worker and beat. The task that was waiting in the queue runs and the
reservation becomes `expired`, with its stock released.

## 5. The safety net: a task that was never scheduled

This is the case the sweep exists for. Leave the worker and beat running.

```bash
docker compose stop redis
curl -s -X POST http://127.0.0.1:8000/api/products/DEMO-1/reservations \
  -H "Content-Type: application/json" \
  -d '{"quantity": 1, "reference": "redis-down"}'
docker compose start redis
```

Expect `201`, even though Redis was down. The request may take a few seconds to
return, because scheduling happens in the request and Celery retries publishing
before giving up. Note how long it took. Terminal A should log an error saying it
could not schedule expiry.

This reservation has no delayed task. Once its deadline passes, beat sends the
sweep within a minute, and terminal B should log `expire_overdue_reservations`
succeeding with a result of 1, and the reservation becomes `expired`. Workers and
beat reconnect on their own when Redis returns, but if they do not, restart them.

## 6. Check the books

```bash
uv run python manage.py reconcile_stock
```

Expect "All inventories reconcile." The expiries wrote ledger rows too.

## Afterwards

Remove `RESERVATION_TTL_MINUTES=1` from `.env` (the default is 15 minutes) and stop
the processes.

# Load testing

Locust scenarios for the reservation API. **Always run these against a separate
benchmark database.** The scenarios create thousands of reservations, and the
seeding command refuses to run unless the database name contains `bench`.

## One-off setup

1. Create the benchmark database inside the running Postgres container:

   ```bash
   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE mwenendo_bench"'
   ```

2. Point Django at it for every command below. `POSTGRES_DB` set in the shell
   overrides the value in `.env`:

   ```bash
   export POSTGRES_DB=mwenendo_bench
   uv run python manage.py migrate
   ```

## A run

Seed the stock, start the server, then start Locust in another terminal:

```bash
# terminal 1
export POSTGRES_DB=mwenendo_bench
uv run python manage.py seed_benchmark --count 1 --stock 5000
uv run python manage.py runserver --noreload

# terminal 2
SKU_COUNT=1 uv run locust -f loadtests/locustfile.py --headless \
  --host http://127.0.0.1:8000 -u 50 -r 10 -t 60s --csv loadtests/results/hot
```

- `SKU_COUNT=1` is the hot-row case: every user fights for one inventory row.
- `SKU_COUNT=50` (with `--count 50` when seeding) spreads the load.
- `-u` is the number of simulated users, `-r` how many start per second.

## Comparing against gunicorn

`run_all.sh` runs all three scenarios against a real gunicorn on the benchmark
database, then checks correctness and prints a summary table. Give each run a
`LABEL`, which becomes the prefix of its own products so runs do not disturb each
other:

```bash
LABEL=conn60 DB_CONN_MAX_AGE=60 loadtests/run_all.sh   # persistent connections
LABEL=conn0  DB_CONN_MAX_AGE=0  loadtests/run_all.sh   # a new connection per request
```

To run the whole comparison (60, 0, 60, 0, about 15 minutes) use `PREFIX=g loadtests/compare.sh`. A run is
reported invalid, and its numbers must not be used, if the server returned any 5xx or the books
did not reconcile. The script migrates the benchmark database itself, and rejects labels that are
not plain letters and digits.

It refuses to run unless `POSTGRES_DB` contains `bench` (the default is
`mwenendo_bench`). Output and CSV files go to `loadtests/results/`, which git ignores.
To put earlier runs side by side:
`uv run python loadtests/summarise.py loadtests/results/conn60-hot loadtests/results/conn0-hot`.

## After every run: check correctness, not only speed

```bash
export POSTGRES_DB=mwenendo_bench
uv run python manage.py reconcile_stock
```

It must print "All inventories reconcile." A fast run that oversells or loses a
ledger row is a failed run.

## What the numbers mean

The Django development server is a single process and is not a production
server, so these figures are a floor, not a ceiling. Report them as such.

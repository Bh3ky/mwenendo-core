#!/usr/bin/env bash
# Run the three load scenarios against gunicorn, on the benchmark database.
#
#   LABEL=conn60 DB_CONN_MAX_AGE=60 loadtests/run_all.sh
#   LABEL=conn0  DB_CONN_MAX_AGE=0  loadtests/run_all.sh
#
# Each LABEL gets its own products, so runs do not disturb each other and the
# benchmark database never has to be reset.
set -euo pipefail

cd "$(dirname "$0")/.."

export POSTGRES_DB="${POSTGRES_DB:-mwenendo_bench}"
if [[ "$POSTGRES_DB" != *bench* ]]; then
  echo "Refusing to run: POSTGRES_DB is '$POSTGRES_DB', and it must contain 'bench'." >&2
  exit 1
fi

LABEL="${LABEL:?Set LABEL, for example LABEL=conn60}"
# The label becomes part of every product's SKU and of file names, so keep it plain.
if [[ ! "$LABEL" =~ ^[A-Za-z0-9]+$ ]]; then
  echo "Refusing to run: LABEL '$LABEL' must be letters and digits only (no spaces)." >&2
  exit 1
fi
DURATION="${DURATION:-30s}"
USERS="${USERS:-50}"
PORT="${PORT:-8001}"
export DB_CONN_MAX_AGE="${DB_CONN_MAX_AGE:-60}"
export DEBUG=False ALLOWED_HOSTS=127.0.0.1,localhost

mkdir -p loadtests/results

# The benchmark database is separate from the development one, so nothing migrates
# it for you. A stale schema makes every request fail with a 500, which looks fast
# and wrong. This only ever touches the database whose name contains 'bench'.
echo "Applying migrations to $POSTGRES_DB..."
uv run python manage.py migrate --noinput | tail -1

echo "Seeding products for '$LABEL' in $POSTGRES_DB..."
uv run python manage.py seed_benchmark --prefix "${LABEL}HOT" --count 1 --stock 1000000
uv run python manage.py seed_benchmark --prefix "${LABEL}SPREAD" --count 50 --stock 100000
uv run python manage.py seed_benchmark --prefix "${LABEL}SELL" --count 1 --stock 500

echo "Starting gunicorn (DB_CONN_MAX_AGE=$DB_CONN_MAX_AGE, workers=${WEB_CONCURRENCY:-4})..."
uv run gunicorn -c gunicorn.conf.py --bind "127.0.0.1:$PORT" config.wsgi \
  > "loadtests/results/$LABEL-gunicorn.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

for _ in $(seq 30); do
  curl -sf "http://127.0.0.1:$PORT/health/" > /dev/null && break
  sleep 1
done
if ! curl -sf "http://127.0.0.1:$PORT/health/" > /dev/null; then
  echo "Server did not start. The end of its log:" >&2
  tail -n 15 "loadtests/results/$LABEL-gunicorn.log" >&2
  exit 1
fi

run() {  # run <scenario> <prefix> <sku count>
  echo "Running $1 for $DURATION with $USERS users..."
  SKU_PREFIX="$2" SKU_COUNT="$3" uv run locust -f loadtests/locustfile.py --headless \
    --host "http://127.0.0.1:$PORT" -u "$USERS" -r 25 -t "$DURATION" \
    --csv "loadtests/results/$LABEL-$1" --only-summary \
    > "loadtests/results/$LABEL-$1.txt" 2>&1 || true
  # Locust exits non-zero when any request failed. Do not stop here: the failures
  # are counted in the summary, and the checks below decide whether the run is valid.
}

run hot "${LABEL}HOT" 1
run spread "${LABEL}SPREAD" 50
run sellout "${LABEL}SELL" 1

echo "Checking correctness..."
uv run python manage.py reconcile_stock

# A run in which the server returned 5xx errors is not a valid measurement: errors
# are quick, so they make the numbers look better than they are.
SERVER_ERRORS=$(grep -c '"status": 5' "loadtests/results/$LABEL-gunicorn.log" || true)
echo "Server errors (5xx) in the gunicorn log: $SERVER_ERRORS"

echo
uv run python loadtests/summarise.py \
  "loadtests/results/$LABEL-hot" \
  "loadtests/results/$LABEL-spread" \
  "loadtests/results/$LABEL-sellout"

if [[ "$SERVER_ERRORS" -gt 0 ]]; then
  echo "INVALID RUN: the server returned $SERVER_ERRORS errors, so these numbers cannot be used." >&2
  exit 1
fi

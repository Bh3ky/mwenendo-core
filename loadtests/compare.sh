#!/usr/bin/env bash
# Compare persistent connections with a new connection per request, under gunicorn.
#
#   PREFIX=g loadtests/compare.sh              # rounds a and b: 60, 0, 60, 0
#   PREFIX=g ROUNDS=b loadtests/compare.sh     # only the second round
#
# The settings alternate, so a slow moment on the machine cannot land on one setting
# only. Each run gets its own label (g60a, g0a, g60b, g0b) and so its own products.
# A run that fails its checks (server errors, books that do not reconcile) is
# reported at the end and does not stop the others.
set -uo pipefail
cd "$(dirname "$0")/.."

PREFIX="${PREFIX:-g}"
ROUNDS="${ROUNDS:-a b}"
INVALID=()

for round in $ROUNDS; do
  for age in 60 0; do
    label="${PREFIX}${age}${round}"
    echo "=== $label: DB_CONN_MAX_AGE=$age ==="
    if ! LABEL="$label" DB_CONN_MAX_AGE="$age" loadtests/run_all.sh; then
      INVALID+=("$label")
    fi
  done
done

echo
if [[ ${#INVALID[@]} -gt 0 ]]; then
  echo "INVALID runs (their numbers must not be used): ${INVALID[*]}"
else
  echo "All runs were valid."
fi
exit 0

"""Print a compact table from the CSV files Locust writes with --csv.

Usage: python loadtests/summarise.py results/<label>-hot results/<label>-spread ...
Each argument is the --csv prefix of one run (without the _stats.csv suffix).
"""

import csv
import sys
from pathlib import Path

RESERVE = "POST /products/[sku]/reservations"
READ = "GET /products/[sku]/inventory"


def _rows(prefix: str) -> dict[str, dict[str, str]]:
    with open(f"{prefix}_stats.csv", newline="") as handle:
        return {row["Name"]: row for row in csv.DictReader(handle)}


def summarise(prefix: str) -> dict[str, str]:
    rows = _rows(prefix)
    total = rows["Aggregated"]
    reserve = rows[RESERVE]
    read = rows[READ]
    requests = int(total["Request Count"])
    failures = int(total["Failure Count"])
    return {
        "run": Path(prefix).name,
        "req/s": f"{float(total['Requests/s']):.0f}",
        "failed": f"{failures / requests:.2%}" if requests else "n/a",
        "reserve p50": f"{float(reserve['50%']):.0f}",
        "reserve p95": f"{float(reserve['95%']):.0f}",
        "reserve p99": f"{float(reserve['99%']):.0f}",
        "read p95": f"{float(read['95%']):.0f}",
    }


def main(prefixes: list[str]) -> None:
    results = [summarise(prefix) for prefix in prefixes]
    columns = list(results[0])
    widths = {c: max(len(c), *(len(r[c]) for r in results)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for result in results:
        print("  ".join(result[c].ljust(widths[c]) for c in columns))
    print("\nResponse times in milliseconds.")


if __name__ == "__main__":
    main(sys.argv[1:])

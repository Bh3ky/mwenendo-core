import csv

import summarise

COLUMNS = [
    "Type",
    "Name",
    "Request Count",
    "Failure Count",
    "Requests/s",
    "50%",
    "95%",
    "99%",
]


def _write(path, rows):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _row(name, count, failures, rps, p50, p95, p99):
    return {
        "Type": "",
        "Name": name,
        "Request Count": count,
        "Failure Count": failures,
        "Requests/s": rps,
        "50%": p50,
        "95%": p95,
        "99%": p99,
    }


def test_summarise_reads_a_locust_stats_file(tmp_path):
    prefix = str(tmp_path / "conn60-hot")
    _write(
        f"{prefix}_stats.csv",
        [
            _row(summarise.READ, 4000, 8, 130.2, 26, 69, 120),
            _row(summarise.RESERVE, 2300, 7, 77.5, 120, 350, 570),
            _row("Aggregated", 7000, 14, 234.4, 45, 270, 450),
        ],
    )

    result = summarise.summarise(prefix)

    assert result["run"] == "conn60-hot"
    assert result["req/s"] == "234"
    assert result["failed"] == "0.20%"
    assert (result["reserve p50"], result["reserve p95"], result["reserve p99"]) == (
        "120",
        "350",
        "570",
    )
    assert result["read p95"] == "69"

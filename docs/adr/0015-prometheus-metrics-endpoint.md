# ADR-0015: A Prometheus `/metrics` endpoint, with database-backed business gauges

- **Status:** Accepted
- **Date:** 2026-11-26
- **Roadmap milestone:** Milestone 8

## Context

Logs say what happened to one request. To see how the system behaves over time (request rate, error rate, how slow the slowest 1% are, how much stock is held) a dashboard or an alert needs numbers it can scrape and graph. Prometheus is the common standard for this.

Two things make it harder than it looks:

- **Gunicorn runs several worker processes.** Each has its own memory. A counter incremented in worker 1 is invisible to worker 3, so a scrape would show only whichever worker answered, and the numbers would jump around.
- **Some work happens in another container.** Reservation expiry runs in the Celery worker. Its counters can never appear in the web server's `/metrics`.

A second trap is labels. A label with a real URL path puts every SKU and every reservation UUID into its own time series, which grows without bound.

## Options considered

For the library:

1. **`prometheus-client` directly,** with a small middleware and view.
   - Pros: we choose every metric and label, and there is no hidden behaviour.
   - Cons: about 100 lines of our own code.
2. **`django-prometheus`.**
   - Pros: ready-made middleware and database and cache metrics.
   - Cons: another layer over the same client. We still need custom business metrics, and I could not confirm whether its request metrics label by route pattern or by raw path.

For several processes:

1. **Multiprocess mode:** each gunicorn worker writes its metrics to files in a shared directory, and `/metrics` adds them up.
   - Pros: the officially documented approach, and it keeps all workers.
   - Cons: needs a directory emptied at start, a `child_exit` hook, and an environment variable set before the library is imported. It covers the web processes only.
2. **A single worker.** No aggregation problem, but it gives up parallelism.
3. **A separate port or exporter per process.** More ports and scrape configuration.

For business state:

1. **Counters in memory.** Blind to other processes, and reset by every restart.
2. **Gauges read from the database when `/metrics` is scraped.**
   - Pros: they reflect the work of every process, and survive restarts.
   - Cons: a few aggregate queries per scrape.

## Decision

- **`prometheus-client` directly.** `core/metrics.py` defines the metrics, `core/middleware.py` counts and times requests, and `config/metrics.py` serves `/metrics`. The view lives in `config`, not `core`, because it reads the inventory and reservation models and `core` is shared by every app and must not depend on them.
- **Multiprocess mode for the web server.** The image's `CMD` sets `PROMETHEUS_MULTIPROC_DIR` for the gunicorn process only, not for the whole container: any other command run in the image (`manage.py`, a shell) would otherwise find the variable set and the directory missing, and would fail, or would write into gunicorn's live metrics directory. `gunicorn.conf.py` empties that directory in `on_starting` and calls `mark_process_dead` in `child_exit`. Without the variable (`runserver`, tests) the default in-memory registry is reported instead. The worker and beat containers, and one-off commands, are unaffected.
- **Metrics:**
  - `http_requests_total{method, route, status}` and `http_request_duration_seconds{method, route}` (a histogram),
  - `stock_allocation_refused_total`,
  - `reservations_by_status{status}` and `stock_units{kind}`, read from the database at scrape time. Every status is always present, including zeros.
- **Labels are bounded.** `route` is the URL pattern (`api/products/<sku>/inventory`), never the real path. A URL that matches no route is `unmatched`. An unusual HTTP method is `OTHER`. `/metrics` does not count itself.
- **Access.** If `METRICS_TOKEN` is set, a scrape needs `Authorization: Bearer <token>`, compared in constant time, otherwise 401. If unset it is open, which suits local use. Production should also restrict it at the proxy.
- **A database outage does not break the endpoint.** The database gauges are skipped (and the failure logged), and the request metrics are still served.

## Consequences

- **Good:**
  - Request rate, error rate and latency percentiles by route, without a high-cardinality label.
  - Business gauges that include the Celery worker's work, because they come from the database.
  - Bounded label values, however many SKUs and reservations exist.
- **Bad / trade-offs:**
  - **Counters from the Celery worker are not exposed.** Anything counted only inside a task is invisible. The database gauges cover the important cases, but there is no task duration or retry count.
  - **Multiprocess mode is operational code.** The directory must be emptied at start. A mistake there double-counts or loses counts, and unit tests cannot add up real workers, so this needs a manual check on the running containers.
  - Each scrape runs two aggregate queries. That is cheap now and would need caching at scale.
  - The `route` label depends on Django resolving the URL. Nothing is lost for our routes, but a middleware that answers early (WhiteNoise for static files, and Django's own 404 handling) is not counted, or is `unmatched`.
  - Histogram buckets are a guess (5 ms to 10 s) and should be tuned against real latencies.
  - `/metrics` is on the same port as the API. Without a token, anyone who can reach the app can read it.
- **Revisit when:**
  - We need worker-side metrics (a second exporter in the Celery container).
  - A scrape becomes slow (cache the database gauges).
  - We deploy behind a proxy that can serve `/metrics` on an internal port.

## References

- [prometheus/client_python: multiprocess mode](https://prometheus.github.io/client_python/multiprocess/)
- [Prometheus: instrumentation best practices, labels](https://prometheus.io/docs/practices/instrumentation/#do-not-overuse-labels)
- [Prometheus: histograms and summaries](https://prometheus.io/docs/practices/histograms/)
- [Django: `ResolverMatch.route`](https://docs.djangoproject.com/en/5.2/ref/urlresolvers/#django.urls.ResolverMatch.route)
- ADR-0012: Reservation expiry with a delayed task and a periodic sweep
- ADR-0013: Run in containers behind gunicorn, with static files from WhiteNoise
- ADR-0014: Structured JSON logging and a separate readiness check

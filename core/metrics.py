"""Prometheus metrics that are updated while requests are handled.

Metrics that describe the state of the data (reservations by status, stock
totals) are not here: they are read from the database when /metrics is scraped.
See config/metrics.py.
"""

from prometheus_client import Counter, Histogram

# Requests per route, method and status. The route is the URL *pattern*
# ("api/products/<sku>/inventory"), never the real path, so the number of
# distinct label values stays small however many SKUs exist.
HTTP_REQUESTS = Counter(
    "http_requests",
    "HTTP requests handled, by method, route pattern and status code.",
    ["method", "route", "status"],
)

HTTP_REQUEST_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Time spent handling an HTTP request, by method and route pattern.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)

STOCK_ALLOCATION_REFUSED = Counter(
    "stock_allocation_refused",
    "Reservations refused because there was not enough unallocated stock.",
)

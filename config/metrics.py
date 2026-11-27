"""The /metrics endpoint.

This lives in `config`, not `core`, because it reads the inventory and
reservations models. `core` is shared by every app and must not depend on them.
"""

import hmac
import logging
import os

from django.conf import settings
from django.db.models import Count, Sum
from django.http import HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import GaugeMetricFamily

from inventory.models import Inventory
from reservations.models import Reservation

logger = logging.getLogger(__name__)


class DatabaseCollector:
    """Gauges for the state of the data, read from the database at scrape time.

    Counters kept in memory only see the process that incremented them, and the
    Celery worker is a different process from the web server. The database sees
    the work of every process, and it survives restarts.
    """

    def describe(self):
        # Without this, the registry calls collect() when the collector is
        # registered, to learn its metric names. That would query the database at
        # import time, in every process, including during `migrate`.
        return []

    def collect(self):
        try:
            by_status = dict(
                Reservation.objects.values_list("status").annotate(count=Count("id"))
            )
            stock = Inventory.objects.aggregate(
                total=Sum("total_quantity"), allocated=Sum("allocated_quantity")
            )
        except Exception:
            # Without the database the request metrics are still worth serving.
            logger.warning("metrics.database_unreachable", exc_info=True)
            return

        reservations = GaugeMetricFamily(
            "reservations_by_status",
            "Reservations in each status.",
            labels=["status"],
        )
        for status in Reservation.Status.values:
            reservations.add_metric([status], by_status.get(status, 0))
        yield reservations

        units = GaugeMetricFamily(
            "stock_units",
            "Units of stock across all inventories.",
            labels=["kind"],
        )
        units.add_metric(["total"], stock["total"] or 0)
        units.add_metric(["allocated"], stock["allocated"] or 0)
        yield units


# In a single process (runserver, tests) the default registry is what we report.
REGISTRY.register(DatabaseCollector())


def _registry() -> CollectorRegistry:
    """Build what this scrape reports."""
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        # Several gunicorn workers: add up what each one wrote to disk, then add
        # the database gauges, which are computed here and not stored per worker.
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        registry.register(DatabaseCollector())
        return registry
    return REGISTRY


def _is_authorised(request) -> bool:
    token = settings.METRICS_TOKEN
    if not token:
        return True
    supplied = request.headers.get("Authorization", "")
    return hmac.compare_digest(supplied, f"Bearer {token}")


def metrics_view(request):
    if not _is_authorised(request):
        response = HttpResponse("Unauthorized", status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response
    return HttpResponse(generate_latest(_registry()), content_type=CONTENT_TYPE_LATEST)

import logging

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def home(request):
    context = {
        "project_name": "Mwenendo Core",
        "description": "Inventory allocation and reservation engine",
    }

    return render(request, "core/home.html", context)


def demo(request):
    """A one-file page that exercises the API from the browser."""
    return render(request, "core/demo.html")


def health_check(request):
    return JsonResponse({"status": "healthy"})


def _database_is_up() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True
    except Exception:
        logger.warning("readiness.database_unreachable", exc_info=True)
        return False


def _redis_is_up() -> bool:
    try:
        client = redis.Redis.from_url(
            settings.CELERY_BROKER_URL, socket_connect_timeout=1, socket_timeout=1
        )
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception:
        logger.warning("readiness.redis_unreachable", exc_info=True)
        return False


def readiness_check(request):
    """Can this instance take traffic? (`/health/` only says it is alive.)

    Only the database decides the status code. Without Redis the app can still
    serve and reserve stock: expiry scheduling falls back to the periodic sweep
    (ADR-0012). Redis is reported, but does not take the instance out of service.
    """
    database_ok = _database_is_up()
    redis_ok = _redis_is_up()

    body = {
        "status": "ready" if database_ok else "unavailable",
        "checks": {
            "database": "ok" if database_ok else "error",
            "redis": "ok" if redis_ok else "error",
        },
    }
    return JsonResponse(body, status=200 if database_ok else 503)

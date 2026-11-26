import logging
import re
import time
import uuid

from core.logs import request_id_var

logger = logging.getLogger("mwenendo.request")

# A request id from a client is only trusted if it is short and plain. Anything
# else could put newlines or huge text into the logs.
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestLoggingMiddleware:
    """Log one JSON line per request, and give every request an id.

    A client or proxy can supply the id in an `X-Request-ID` header. It is sent
    back in the response, so a caller can quote it when reporting a problem.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if _VALID_REQUEST_ID.match(supplied) else uuid.uuid4().hex

        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500  # what we report if an exception escapes
        try:
            response = self.get_response(request)
            status = response.status_code
            response["X-Request-ID"] = request_id
            return response
        finally:
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            request_id_var.reset(token)

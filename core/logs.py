"""Structured (JSON) logging.

Every log line is one JSON object. Fields passed with `extra={...}` become top
level keys, and the id of the request being handled is added automatically, so
the lines of one request can be found together.
"""

import contextvars
import json
import logging
from datetime import UTC, datetime

# Holds the current request's id. A context variable stays correct when several
# requests are handled at once, which a plain global would not.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)

# The attributes every LogRecord has. Anything else was added with `extra=`.
_STANDARD_ATTRIBUTES = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRIBUTES:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # default=str means an odd value (a UUID, a datetime) is written as text
        # and never makes logging itself raise.
        return json.dumps(payload, default=str)

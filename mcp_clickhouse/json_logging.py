"""Single-line JSON logging for log shippers (ClickHouse ingestion)."""

import json
import logging
import sys
from datetime import datetime, timezone

# Anything not on a bare LogRecord came from `extra=` and is worth emitting.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
    "color_message",  # uvicorn's ANSI-escaped duplicate of the message
}

# fastmcp configures its own RichHandler at import and stops propagation;
# uvicorn's loggers are reached by passing log_config=None (see main.py).
_HIJACKED_LOGGERS = ("fastmcp", "uvicorn", "uvicorn.error", "uvicorn.access")

# Fields we own. Nested or `extra=` values never overwrite these.
_CORE = frozenset({"ts", "level", "logger", "file"})


def _unescape(value: object) -> object:
    """Parse a value that is itself a serialized JSON object or array.

    Some libraries (fastmcp's StructuredLoggingMiddleware) hand `logging` a
    message that is already JSON, so re-encoding it as a string would leave the
    consumer to unescape by hand. Only objects and arrays are unwrapped: bare
    scalars like "null" or a message that happens to be a number stay strings.
    """
    if not isinstance(value, str) or value[:1] not in ("{", "["):
        return value
    try:
        parsed = json.loads(value)
    except ValueError:
        return value
    return parsed if isinstance(parsed, (dict, list)) else value


class JsonFormatter(logging.Formatter):
    """One JSON object per line, on stderr."""

    def format(self, record: logging.LogRecord) -> str:
        created = datetime.fromtimestamp(record.created, timezone.utc)
        payload = {
            "ts": f"{created:%Y-%m-%dT%H:%M:%S}.{record.msecs:03.0f}Z",
            "level": record.levelname,
            "logger": record.name,
            "file": f"{record.filename}:{record.lineno}",
        }

        message = record.getMessage()
        nested = _unescape(message)
        if isinstance(nested, dict):
            # An already-JSON message becomes real fields instead of an escaped
            # blob; its own values get one level of the same treatment. The
            # record's level and logger win over any the payload carries.
            payload.update({k: _unescape(v) for k, v in nested.items() if k not in _CORE})
        else:
            payload["message"] = message

        payload.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED | _CORE})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def setup_json_logging(level: int = logging.INFO) -> None:
    """Route every logger through one JSON handler on stderr. Idempotent."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)

    for name in _HIJACKED_LOGGERS:
        hijacked = logging.getLogger(name)
        hijacked.handlers.clear()
        hijacked.propagate = True

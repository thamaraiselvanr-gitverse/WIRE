import logging
import sys
from typing import Any

import structlog


def sse_event_broadcaster(logger: Any, log_method: Any, event_dict: Any) -> Any:
    try:
        # Import dynamically to avoid circular imports if run as a CLI
        from wire.api.main_routes import log_event_queues

        if log_event_queues:
            level = event_dict.get("level", "info").upper()
            event = event_dict.get("event", "")
            pieces = [f"[{level}] {event}"]
            for key, val in event_dict.items():
                if key not in ["event", "level", "timestamp", "logger"]:
                    pieces.append(f"{key}={val}")
            msg = " ".join(pieces)
            for queue in log_event_queues:
                # Per-queue guard: one slow consumer's full queue must drop
                # only its own event, not abort delivery to other clients.
                try:
                    queue.put_nowait(msg)
                except Exception:
                    pass
    except Exception:
        pass
    return event_dict


def setup_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            sse_event_broadcaster,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

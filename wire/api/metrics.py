"""Minimal in-process metrics with a Prometheus text exposition.

Dependency-free counters for the operations worth watching (reconstruction
requests, job outcomes). Exposed at ``/api/metrics`` for a Prometheus scrape.

Counters are per-process: in a multi-process deployment (API + N workers) each
process is a separate scrape target, which Prometheus aggregates. That's the
standard model and keeps this free of a metrics broker.
"""

import threading
from typing import Dict


class Counter:
    def __init__(self) -> None:
        self._value = 0
        self._lock = threading.Lock()

    def inc(self, amount: int = 1) -> None:
        with self._lock:
            self._value += amount

    @property
    def value(self) -> int:
        return self._value


_counters: Dict[str, Counter] = {}
_registry_lock = threading.Lock()


def counter(name: str) -> Counter:
    """Get-or-create a named counter."""
    with _registry_lock:
        c = _counters.get(name)
        if c is None:
            c = Counter()
            _counters[name] = c
        return c


def render_prometheus() -> str:
    """Render all counters in Prometheus text exposition format."""
    lines = []
    for name in sorted(_counters):
        metric = f"wire_{name}"
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {_counters[name].value}")
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Clear all counters (used between tests)."""
    with _registry_lock:
        _counters.clear()

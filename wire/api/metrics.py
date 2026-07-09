"""Minimal in-process metrics with a Prometheus text exposition.

Dependency-free counters for the operations worth watching (reconstruction
requests, job outcomes). Exposed at ``/api/metrics`` for a Prometheus scrape.

Counters are per-process: in a multi-process deployment (API + N workers) each
process is a separate scrape target, which Prometheus aggregates. That's the
standard model and keeps this free of a metrics broker.
"""

import threading
from typing import Dict, List, Tuple


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


class Histogram:
    """Cumulative-bucket histogram (Prometheus semantics), dependency-free.

    Powers latency visibility: p95/p99 come from ``histogram_quantile`` over
    the ``_bucket`` series at query time; the process only tracks counts.
    ``observe`` increments every bucket whose bound is >= the value, so the
    stored counts are already cumulative as the exposition format requires.
    """

    # Spans quick API calls through multi-minute reconstructions.
    DEFAULT_BUCKETS: Tuple[float, ...] = (
        0.05,
        0.1,
        0.25,
        0.5,
        1,
        2.5,
        5,
        10,
        30,
        60,
        120,
        300,
        600,
    )

    def __init__(self, buckets: Tuple[float, ...] = DEFAULT_BUCKETS) -> None:
        self.buckets = tuple(sorted(buckets))
        self._counts = [0] * len(self.buckets)
        self._sum = 0.0
        self._count = 0
        self._lock = threading.Lock()

    def observe(self, value: float) -> None:
        with self._lock:
            self._sum += value
            self._count += 1
            for i, upper in enumerate(self.buckets):
                if value <= upper:
                    self._counts[i] += 1

    @property
    def count(self) -> int:
        return self._count

    def render(self, metric: str) -> List[str]:
        with self._lock:
            lines = [f"# TYPE {metric} histogram"]
            for upper, cumulative in zip(self.buckets, self._counts):
                lines.append(f'{metric}_bucket{{le="{upper}"}} {cumulative}')
            lines.append(f'{metric}_bucket{{le="+Inf"}} {self._count}')
            lines.append(f"{metric}_sum {self._sum}")
            lines.append(f"{metric}_count {self._count}")
            return lines


_counters: Dict[str, Counter] = {}
_histograms: Dict[str, Histogram] = {}
_registry_lock = threading.Lock()


def counter(name: str) -> Counter:
    """Get-or-create a named counter."""
    with _registry_lock:
        c = _counters.get(name)
        if c is None:
            c = Counter()
            _counters[name] = c
        return c


def histogram(name: str) -> Histogram:
    """Get-or-create a named histogram."""
    with _registry_lock:
        h = _histograms.get(name)
        if h is None:
            h = Histogram()
            _histograms[name] = h
        return h


def render_prometheus() -> str:
    """Render all counters and histograms in Prometheus text exposition."""
    lines = []
    for name in sorted(_counters):
        metric = f"wire_{name}"
        lines.append(f"# TYPE {metric} counter")
        lines.append(f"{metric} {_counters[name].value}")
    for name in sorted(_histograms):
        lines.extend(_histograms[name].render(f"wire_{name}"))
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Clear all counters and histograms (used between tests)."""
    with _registry_lock:
        _counters.clear()
        _histograms.clear()

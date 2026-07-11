from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager


class MetricsCollector:
    def __init__(self) -> None:
        self.stage_timings: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.stage_timings[name] = time.perf_counter() - started

from __future__ import annotations

import io
import sys
from threading import Lock


class LiveProgress:
    def __init__(self, enabled: bool = True, stream: io.TextIOBase | None = None) -> None:
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self._interactive = enabled and hasattr(self.stream, "isatty") and self.stream.isatty()
        self._lock = Lock()
        self._states: dict[str, str] = {}
        self._last_width = 0

    def update(self, partition: str, stage: str) -> None:
        with self._lock:
            previous = self._states.get(partition)
            self._states[partition] = stage
            if self._interactive:
                self._render_locked()
            elif previous != stage and self.enabled:
                print(f"{partition}: {stage}", file=self.stream, flush=True)

    def fail(self, partition: str, stage: str, message: str) -> None:
        with self._lock:
            self._states[partition] = f"{stage} failed"
            if self._interactive:
                self._clear_locked()
            if self.enabled:
                print(f"{partition}: {stage} failed: {message}", file=self.stream, flush=True)

    def stage(self, partition: str) -> str:
        with self._lock:
            return self._states.get(partition, "build")

    def close(self) -> None:
        with self._lock:
            if self._interactive:
                self._clear_locked()

    def _render_locked(self) -> None:
        status = " | ".join(f"{partition}:{stage}" for partition, stage in sorted(self._states.items()))
        line = f"\r{status}"
        padding = " " * max(0, self._last_width - len(status))
        self.stream.write(line + padding)
        self.stream.flush()
        self._last_width = len(status)

    def _clear_locked(self) -> None:
        if self._last_width:
            self.stream.write("\r" + (" " * self._last_width) + "\r")
            self.stream.flush()
            self._last_width = 0

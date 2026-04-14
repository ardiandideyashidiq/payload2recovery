from __future__ import annotations

import io
import sys
import time
from dataclasses import dataclass
from threading import Lock

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)


@dataclass(slots=True)
class _ProgressState:
    stage: str = "build"
    stage_started_at: float = 0.0
    processed_bytes: int = 0
    total_bytes: int = 0
    output_bytes: int = 0
    last_logged_bucket: int = -1


@dataclass(slots=True)
class _ZipProgressState:
    current_file: str = ""
    files_done: int = 0
    total_files: int = 0
    bytes_done: int = 0
    total_bytes: int = 0
    store_entry: bool = False
    started_at: float = 0.0
    last_logged_bucket: int = -1


class LiveProgress:
    def __init__(self, enabled: bool = True, stream: io.TextIOBase | None = None) -> None:
        self.stream = stream or sys.stderr
        self.enabled = enabled
        self._interactive = enabled and hasattr(self.stream, "isatty") and self.stream.isatty()
        self._lock = Lock()
        self._states: dict[str, _ProgressState] = {}
        self._partition_tasks: dict[str, TaskID] = {}
        self._zip_state: _ZipProgressState | None = None
        self._zip_task: TaskID | None = None
        self._console: Console | None = None
        self._progress: Progress | None = None

    def update(
        self,
        partition: str,
        stage: str,
        *,
        processed_bytes: int | None = None,
        total_bytes: int | None = None,
        output_bytes: int | None = None,
    ) -> None:
        with self._lock:
            now = time.monotonic()
            state = self._states.get(partition)
            previous_stage = state.stage if state is not None else None
            if state is None:
                state = _ProgressState(stage=stage, stage_started_at=now)
                self._states[partition] = state
            elif previous_stage != stage:
                state.stage = stage
                state.stage_started_at = now
                state.processed_bytes = 0
                state.total_bytes = 0
                state.output_bytes = 0
                state.last_logged_bucket = -1

            if processed_bytes is not None:
                state.processed_bytes = processed_bytes
            if total_bytes is not None:
                state.total_bytes = total_bytes
            if output_bytes is not None:
                state.output_bytes = output_bytes

            if self._interactive:
                self._render_partition_locked(partition, state, now)
            elif self.enabled and self._should_log_progress(previous_stage, state):
                print(self._format_plain_line(partition, state, now), file=self.stream, flush=True)

    def fail(self, partition: str, stage: str, message: str) -> None:
        with self._lock:
            now = time.monotonic()
            state = self._states.get(partition)
            if state is None:
                state = _ProgressState(stage=f"{stage} failed", stage_started_at=now)
                self._states[partition] = state
            else:
                state.stage = f"{stage} failed"
                state.stage_started_at = now
            if self._interactive:
                self._ensure_progress_locked()
                task_id = self._partition_tasks.get(partition)
                if task_id is not None and self._progress is not None:
                    self._progress.update(
                        task_id,
                        state="failed",
                        speed="-",
                        filename=self._filename_for_stage(partition, "failed"),
                        total=1,
                        completed=1,
                        refresh=True,
                    )
                    self._progress.stop_task(task_id)
            if self.enabled:
                print(f"{partition}: {stage} failed: {message}", file=self.stream, flush=True)

    def stage(self, partition: str) -> str:
        with self._lock:
            state = self._states.get(partition)
            return state.stage if state is not None else "build"

    def update_package(
        self,
        current_file: str,
        files_done: int,
        total_files: int,
        bytes_done: int,
        total_bytes: int,
        *,
        store_entry: bool,
    ) -> None:
        with self._lock:
            now = time.monotonic()
            if self._zip_state is None:
                self._zip_state = _ZipProgressState(started_at=now)
            self._zip_state.current_file = current_file
            self._zip_state.files_done = files_done
            self._zip_state.total_files = total_files
            self._zip_state.bytes_done = bytes_done
            self._zip_state.total_bytes = total_bytes
            self._zip_state.store_entry = store_entry
            if self._interactive:
                self._render_zip_locked(now)
            elif self.enabled and self._should_log_zip_progress(self._zip_state):
                print(self._format_zip_line(self._zip_state, now), file=self.stream, flush=True)

    def close(self) -> None:
        with self._lock:
            if self._interactive and self._progress is not None:
                self._progress.stop()
                self._progress = None
                self._console = None

    def _render_partition_locked(
        self, partition: str, state: _ProgressState, now: float
    ) -> None:
        self._ensure_progress_locked()
        assert self._progress is not None
        task_id = self._partition_tasks.get(partition)
        if task_id is None:
            task_id = self._progress.add_task(
                partition,
                service=partition,
                state=self._display_stage(state.stage),
                speed="-",
                filename=self._filename_for_stage(partition, state.stage),
                total=None,
            )
            self._partition_tasks[partition] = task_id
        total, completed = self._task_progress_for_state(state)
        self._progress.update(
            task_id,
            total=total,
            completed=completed,
            state=self._display_stage(state.stage),
            speed=self._speed_for_state(state, now),
            filename=self._filename_for_stage(partition, state.stage),
            refresh=True,
        )
        if state.stage == "done":
            self._progress.stop_task(task_id)

    def _render_zip_locked(self, now: float) -> None:
        self._ensure_progress_locked()
        assert self._progress is not None
        assert self._zip_state is not None
        if self._zip_task is None:
            self._zip_task = self._progress.add_task(
                "zip",
                service="zip",
                state=self._zip_mode(self._zip_state),
                speed="-",
                filename=self._zip_state.current_file or "-",
                total=self._zip_state.total_bytes or 1,
            )
        self._progress.update(
            self._zip_task,
            total=self._zip_state.total_bytes or 1,
            completed=self._zip_state.bytes_done,
            state=self._zip_mode(self._zip_state),
            speed=f"{self._zip_state.files_done}/{max(1, self._zip_state.total_files)} files",
            filename=self._zip_state.current_file or "-",
            refresh=True,
        )
        if self._zip_state.total_bytes > 0 and self._zip_state.bytes_done >= self._zip_state.total_bytes:
            self._progress.stop_task(self._zip_task)

    def _ensure_progress_locked(self) -> None:
        if self._progress is not None:
            return
        self._console = Console(
            file=self.stream,
            force_terminal=True,
            color_system=None,
            width=120,
            soft_wrap=False,
        )
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold]{task.fields[service]}[/bold]"),
            TextColumn("{task.fields[state]}"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("{task.fields[speed]}"),
            TimeElapsedColumn(),
            TextColumn("{task.fields[filename]}"),
            console=self._console,
            auto_refresh=False,
            transient=False,
        )
        self._progress.start()

    def _should_log_progress(self, previous_stage: str | None, state: _ProgressState) -> bool:
        if previous_stage != state.stage:
            return True
        if state.stage != "brotli" or state.total_bytes <= 0:
            return False
        bucket = min(10, int((state.processed_bytes / state.total_bytes) * 10))
        if bucket > state.last_logged_bucket:
            state.last_logged_bucket = bucket
            return True
        return False

    def _should_log_zip_progress(self, state: _ZipProgressState) -> bool:
        if state.total_bytes <= 0:
            return state.files_done == 0 or state.files_done == state.total_files
        bucket = min(10, int((state.bytes_done / state.total_bytes) * 10))
        if bucket > state.last_logged_bucket:
            state.last_logged_bucket = bucket
            return True
        if state.files_done == state.total_files and bucket == state.last_logged_bucket:
            return True
        return False

    def _format_plain_line(self, partition: str, state: _ProgressState, now: float) -> str:
        return f"{partition}: {self._format_status(state, now)}"

    def _format_status(self, state: _ProgressState, now: float) -> str:
        elapsed = max(0.0, now - state.stage_started_at)
        if state.stage == "waiting-brotli":
            return f"waiting  {self._format_elapsed(elapsed)}"
        if state.stage == "brotli":
            return self._format_brotli_status(state, elapsed)
        if state.stage == "done":
            return "done"
        return f"{state.stage} {self._format_elapsed(elapsed)}"

    def _format_zip_line(self, state: _ZipProgressState, now: float) -> str:
        elapsed = max(0.0, now - state.started_at)
        mode = "store" if state.store_entry else "deflate"
        total_files = max(1, state.total_files)
        current = state.current_file or "-"
        return (
            f"zip {state.files_done}/{total_files} files "
            f"{self._format_mib(state.bytes_done)}/{self._format_mib(state.total_bytes)} "
            f"{mode} {current} {self._format_elapsed(elapsed)}"
        )

    def _format_brotli_status(self, state: _ProgressState, elapsed: float) -> str:
        if state.total_bytes <= 0:
            return f"brotli {self._format_elapsed(elapsed)}"
        percent = min(100.0, (state.processed_bytes / state.total_bytes) * 100)
        speed = state.processed_bytes / max(elapsed, 0.001)
        return (
            f"brotli {percent:>3.0f}% "
            f"{self._format_mib(state.processed_bytes)}/{self._format_mib(state.total_bytes)} "
            f"{self._format_mib(speed)}/s {self._format_elapsed(elapsed)}"
        )

    def _task_progress_for_state(self, state: _ProgressState) -> tuple[float | None, float]:
        if state.stage == "brotli" and state.total_bytes > 0:
            return float(state.total_bytes), float(state.processed_bytes)
        if state.stage == "done":
            total = float(max(1, state.total_bytes or state.processed_bytes or 1))
            return total, total
        if state.stage.endswith("failed"):
            return 1.0, 1.0
        return None, 0.0

    def _speed_for_state(self, state: _ProgressState, now: float) -> str:
        if state.stage != "brotli" or state.total_bytes <= 0:
            return "-"
        elapsed = max(0.001, now - state.stage_started_at)
        speed = state.processed_bytes / elapsed
        return f"{self._format_mib(speed)}/s"

    @staticmethod
    def _display_stage(stage: str) -> str:
        if stage == "waiting-brotli":
            return "waiting"
        return stage

    @staticmethod
    def _filename_for_stage(partition: str, stage: str) -> str:
        if stage == "sparse":
            return f"{partition}.img"
        if stage == "dat":
            return f"{partition}.transfer.list"
        if stage in {"waiting-brotli", "brotli", "done"}:
            return f"{partition}.new.dat.br"
        if stage.endswith("failed"):
            return partition
        return partition

    @staticmethod
    def _zip_mode(state: _ZipProgressState) -> str:
        return "store" if state.store_entry else "deflate"

    @staticmethod
    def _format_mib(value: float) -> str:
        return f"{value / (1024 * 1024):.0f}MiB"

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        whole = int(seconds)
        minutes, secs = divmod(whole, 60)
        return f"{minutes:02d}:{secs:02d}"

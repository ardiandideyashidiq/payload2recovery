from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator


LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt=DATE_FORMAT)


@contextmanager
def stage_timer(label: str, logger: logging.Logger) -> Iterator[None]:
    started = time.perf_counter()
    logger.info("%s...", label)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - started
        logger.info("%s finished in %.2fs", label, elapsed)

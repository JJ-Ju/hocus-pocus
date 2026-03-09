"""Logging helpers."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .paths import server_log_path


def configure_logging(log_level: str) -> logging.Logger:
    logger = logging.getLogger("hocuspocus")
    if logger.handlers:
        logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        return logger

    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(threadName)s %(name)s %(message)s"
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(level)

    file_handler = RotatingFileHandler(
        server_log_path(),
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger

"""Loguru + Rich logging configuration."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from loguru import logger
from rich.console import Console

if TYPE_CHECKING:
    from loguru import Logger

console = Console()
_configured = False


def configure_logging(*, level: str = "INFO", json: bool = False) -> None:
    """Configure the global Loguru logger.

    Idempotent: repeated calls reconfigure the single sink rather than stacking.
    """
    global _configured
    logger.remove()
    if json:
        logger.add(sys.stderr, level=level, serialize=True, backtrace=False, diagnose=False)
    else:
        logger.add(
            sys.stderr,
            level=level,
            backtrace=False,
            diagnose=False,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
        )
    _configured = True


def get_logger() -> Logger:
    """Return the configured Loguru logger, configuring it on first use."""
    if not _configured:
        configure_logging()
    return logger

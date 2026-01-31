"""
Structured logging for CloneBox using structlog.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import structlog


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_file: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """
    Configure structured logging for CloneBox.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: If True, output JSON format (good for log aggregation)
        log_file: Optional file path for log output
        console_output: If True, also output to console
    """

    # Shared processors for all outputs
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        # JSON output for production/aggregation
        renderer = structlog.processors.JSONRenderer()
    else:
        # Human-readable output for development
        renderer = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.plain_traceback,
        )

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging
    handlers = []

    if console_output:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=renderer,
                foreign_pre_chain=shared_processors,
            )
        )
        handlers.append(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                processor=structlog.processors.JSONRenderer(),  # Always JSON for files
                foreign_pre_chain=shared_processors,
            )
        )
        handlers.append(file_handler)

    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        handlers=handlers,
    )


def get_logger(name: str = "clonebox") -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


# Context managers for operation tracking
from contextlib import contextmanager


@contextmanager
def log_operation(logger: structlog.stdlib.BoundLogger, operation: str, **kwargs):
    """
    Context manager for logging operation start/end.

    Usage:
        with log_operation(log, "create_vm", vm_name="my-vm"):
            # do stuff
    """
    log = logger.bind(operation=operation, **kwargs)
    start_time = datetime.now()
    log.info(f"{operation}.started")

    try:
        yield log
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        log.info(f"{operation}.completed", duration_ms=round(duration_ms, 2))
    except Exception as e:
        duration_ms = (datetime.now() - start_time).total_seconds() * 1000
        log.error(
            f"{operation}.failed",
            error=str(e),
            error_type=type(e).__name__,
            duration_ms=round(duration_ms, 2),
        )
        raise

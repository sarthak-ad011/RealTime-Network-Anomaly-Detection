"""Centralized loguru configuration.

Import this module early in any entry point (train.py, app.py) to enable
file-based logging alongside the default stderr output.

Usage:
    import src.log_config  # noqa: F401  — side-effect import
"""
import sys
from pathlib import Path

from loguru import logger

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Remove the default stderr handler so we can re-add it with a consistent format
logger.remove()

# Console handler (stderr) — coloured, human-friendly
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>",
    colorize=True,
)

# File handler — structured, rotated, retained
logger.add(
    LOG_DIR / "app.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{function}:{line} — {message}",
    rotation="10 MB",
    retention="30 days",
    compression="gz",
    enqueue=True,  # thread-safe
)

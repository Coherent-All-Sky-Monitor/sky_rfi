"""
Utility functions for Sky RFI Monitor.
Includes logging and common helpers.
"""

import datetime
from typing import Optional


def log(source: str, message: str):
    """
    Log a message with timestamp and source.

    Args:
        source: The source/module of the log message
        message: The log message
    """
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] [{source}] {message}")


def format_timestamp(ts: Optional[float] = None) -> str:
    """
    Format a Unix timestamp as a readable string.

    Args:
        ts: Unix timestamp (defaults to current time)

    Returns:
        Formatted datetime string
    """
    if ts is None:
        dt = datetime.datetime.now()
    else:
        dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

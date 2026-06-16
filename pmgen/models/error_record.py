"""Error record model for Toshiba eService error history."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorRecord:
    """A single error history entry from a Toshiba device.

    Attributes:
        code: Error code (e.g. "E712", "EB50").
        counter: Device counter value at time of error.
        date: Error date as YYYY-MM-DD.
        time: Error time as HH:MM:SS.
    """

    code: str
    counter: str
    date: str
    time: str

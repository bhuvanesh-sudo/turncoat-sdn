"""Task-level availability metrics."""

from __future__ import annotations

from collections.abc import Mapping


def score_availability(record: Mapping[str, object]) -> dict[str, float | int]:
    """Calculate task availability from offered and completed task counts."""
    offered = record.get("offered")
    completed = record.get("completed")

    if not isinstance(offered, int) or isinstance(offered, bool) or offered < 0:
        raise ValueError("offered must be a non-negative integer")
    if (
        not isinstance(completed, int)
        or isinstance(completed, bool)
        or not 0 <= completed <= offered
    ):
        raise ValueError("completed must be an integer between 0 and offered")

    return {
        "offered": offered,
        "completed": completed,
        "uncompleted": offered - completed,
        "availability": completed / offered if offered else 0.0,
    }

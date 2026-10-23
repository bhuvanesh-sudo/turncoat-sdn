"""Shared fixtures for the event-format tests.

``sample_run.jsonl`` is a short, valid recording in the shape of the plan's
example: srv3 turns on-off at 120 s, is named at 135.9 s and isolated at
136 s. ``broken_run.jsonl`` has one distinct problem on each line from 2 on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SAMPLE = HERE / "sample_run.jsonl"
BROKEN = HERE / "broken_run.jsonl"


@pytest.fixture
def sample_events():
    """A fresh copy of the sample recording's events, safe to mutate."""
    return [json.loads(line) for line in SAMPLE.read_text("utf-8").splitlines()]


@pytest.fixture
def sample_path():
    return SAMPLE


@pytest.fixture
def broken_path():
    return BROKEN

"""Make ``turncoat_mininet`` importable from a clone, installed or not.

None of these tests needs Mininet, Open vSwitch, os-ken or root, apart from
``test_live_mininet.py``, which is marked ``live`` and skips itself without
them. Agents and controllers run as real HTTP servers on 127.0.0.1.
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


@pytest.fixture
def free_port():
    """Return a function that finds a free TCP port on 127.0.0.1."""

    def find() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    return find

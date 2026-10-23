"""Exit codes shared by every ``turncoat`` command.

This module must not import os-ken, Ryu or Mininet.
"""

from __future__ import annotations

#: The command did what was asked.
EXIT_OK = 0
#: The command ran, but the answer is "no": a recording is invalid or cannot be scored.
EXIT_FAILED = 1
#: A file could not be read or written.
EXIT_UNREADABLE = 2

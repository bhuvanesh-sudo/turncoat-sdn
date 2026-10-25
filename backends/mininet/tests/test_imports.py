"""The backend stays importable everywhere; only building a network needs Mininet.

The core package's own guard (``tests/test_package.py``) checks that nothing
under ``src/turncoat_sdn`` pulls in the SDN stack. This is its twin for the
backend: every ``turncoat_mininet`` module imports in a fresh interpreter
without Mininet or os-ken, so the tests and the loopback run work on any
machine.
"""

from __future__ import annotations

import pkgutil
import subprocess
import sys
from pathlib import Path

import turncoat_mininet

BACKEND_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = ("mininet", "os_ken", "ryu")


def test_every_backend_module_imports_without_the_sdn_stack():
    names = [turncoat_mininet.__name__] + [
        f"turncoat_mininet.{m.name}" for m in pkgutil.iter_modules(turncoat_mininet.__path__)
    ]
    assert "turncoat_mininet.topology" in names
    script = (
        "import importlib, sys\n"
        f"sys.path.insert(0, {str(BACKEND_ROOT)!r})\n"
        f"for name in {names!r}:\n"
        "    importlib.import_module(name)\n"
        f"print(','.join(sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN!r})))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == ""


def test_the_core_package_never_imports_the_backend():
    script = (
        "import importlib, pkgutil, sys, turncoat_sdn\n"
        "for m in pkgutil.walk_packages(turncoat_sdn.__path__, prefix='turncoat_sdn.'):\n"
        "    importlib.import_module(m.name)\n"
        "print('turncoat_mininet' in sys.modules)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"

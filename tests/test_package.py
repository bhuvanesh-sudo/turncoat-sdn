"""Scaffold tests: the package installs, imports cleanly and stays free of the SDN stack.

These guard the v0.1 promise that the core runs on a plain machine with no
os-ken, Ryu or Mininet. They keep passing as teammates fill in each
subpackage, and fail loudly if a ported module drags the SDN stack back in.
"""

from __future__ import annotations

import importlib
import importlib.resources
import pkgutil
import subprocess
import sys

import pytest

import turncoat_sdn

SUBPACKAGES = ("sim", "attacks", "strategies", "trust", "events", "scoring", "stats")
FORBIDDEN_TOP_LEVEL = ("os_ken", "ryu", "mininet")


def test_version_is_a_non_empty_string():
    assert isinstance(turncoat_sdn.__version__, str)
    assert turncoat_sdn.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_planned_subpackage_imports(name):
    module = importlib.import_module(f"turncoat_sdn.{name}")
    assert module.__doc__, f"turncoat_sdn.{name} needs a module docstring"


def _all_core_modules():
    """Every module under turncoat_sdn, including ones added after v0.1."""
    names = [turncoat_sdn.__name__]
    for info in pkgutil.walk_packages(turncoat_sdn.__path__, prefix="turncoat_sdn."):
        names.append(info.name)
    return names


def test_core_does_not_import_sdn_stack():
    """Import every core module in a fresh interpreter and check sys.modules.

    A fresh process is used so that nothing another test imported can hide or
    cause a failure here.
    """
    modules = _all_core_modules()
    script = (
        "import importlib, sys\n"
        f"for name in {modules!r}:\n"
        "    importlib.import_module(name)\n"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {FORBIDDEN_TOP_LEVEL!r})\n"
        "print(','.join(bad))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked = result.stdout.strip()
    assert leaked == "", f"core package imported SDN-stack modules: {leaked}"


def test_package_is_typed():
    files = importlib.resources.files(turncoat_sdn)
    assert files.joinpath("py.typed").is_file()

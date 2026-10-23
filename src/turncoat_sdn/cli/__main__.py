"""Allow ``python -m turncoat_sdn.cli``, the same as the ``turncoat`` command."""

from __future__ import annotations

from turncoat_sdn.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

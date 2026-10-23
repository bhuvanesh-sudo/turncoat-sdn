# Installing turncoat-sdn

**Owner:** bv · **Written in:** v0.1 · **Mininet section:** v1.0

## What you are installing

The core package: the simulator, the strategies and trust model, the
`events.jsonl` format with its validator, and the scorers. The attack library,
statistics and the full `turncoat` command arrive in later releases. It is
pure Python and depends only on NumPy and SciPy.

The core never needs os-ken, Ryu, Mininet, root access or a virtual switch. It
runs the same on Windows, macOS and Linux. An optional live testbed under
`backends/mininet/` arrives in v1.0 and has its own requirements (see
[Optional: the live Mininet testbed](#optional-the-live-mininet-testbed)).

## Requirements

- Python **3.11 or newer** (CI tests 3.11 to 3.14)
- Git
- About 250 MB of disk for a virtual environment with the development tools

Check your Python version:

```bash
python --version        # Windows
python3 --version       # macOS and Linux
```

## Install from source

turncoat-sdn is not on PyPI yet, so install it from a clone. Use a virtual
environment so it cannot clash with anything else on your machine.

**macOS and Linux**

```bash
git clone https://github.com/bhuvanesh-sudo/turncoat-sdn.git
cd turncoat-sdn
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/bhuvanesh-sudo/turncoat-sdn.git
cd turncoat-sdn
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

`-e` installs in editable mode, so changes to the source take effect without
reinstalling.

## Check that it works

```bash
turncoat --version
python -c "import turncoat_sdn.sim as s; print(s.SCENARIOS)"
```

The first prints the version and the second prints
`('clean', 'sybil', 'drop', 'both')`. To record a simulated run, validate it
and score it, follow the [quick start in the README](README.md#quick-start-v02).

## Install for development

Contributors also need the test and lint tools:

```bash
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

These are the same commands CI runs. The test suite takes a few seconds and
needs no network access. One test imports every core module in a fresh
interpreter and fails if any of them pulls in os-ken, Ryu or Mininet.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ERROR: Package 'turncoat-sdn' requires a different Python` | Your Python is older than 3.11. Install a newer one and recreate the virtual environment with it. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that PowerShell window, then activate again. This changes nothing beyond the current window. |
| `turncoat: command not found` | The virtual environment is not active. Activate it again, or run `python -m turncoat_sdn.cli` instead. |
| `pip` builds NumPy or SciPy from source and fails | Your Python is too new for the published wheels, or pip is old. Upgrade pip first; if that does not help, use Python 3.12 or 3.13. |
| `ModuleNotFoundError: No module named 'turncoat_sdn'` in tests | Install with `pip install -e ".[dev]"` from the repository root, not just `pip install pytest`. |

## Optional: the live Mininet testbed

Lands in v1.0. The live backend runs the same strategies and attacks against a
real OpenFlow 1.3 network under Mininet, and writes the same `events.jsonl`
recording, so the same scorers grade it. It needs Linux, root access, Open
vSwitch, Mininet and os-ken, which is why it is installed separately from the
core. This section will describe that setup once the backend is ported.

## Uninstall

```bash
python -m pip uninstall turncoat-sdn
```

Or delete the `.venv` folder to remove the environment and everything in it.

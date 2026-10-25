# Installing turncoat-sdn

**Owner:** bv · **Written in:** v0.1 · **Mininet section:** v1.0

## What you are installing

The core package: the simulator, the strategies and trust model, the
`events.jsonl` format with its validator, the scorers, the attack library and
the `turncoat run`, `validate`, `score`, `replicate`, `compare` and `plot`
commands, bootstrap confidence intervals and paired tests. It is pure Python
and depends only on NumPy and SciPy.

The core never needs os-ken, Ryu, Mininet, root access or a virtual switch. It
runs the same on Windows, macOS and Linux. The optional live testbed under
`backends/mininet/` (v1.0) has its own requirements (see
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
`('clean', 'sybil', 'drop', 'both', 'grayhole', 'onoff', 'spoof')`. To record a
simulated run, validate it and score it, follow the
[quick start in the README](README.md#quick-start-v04).

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

The live backend, `backends/mininet/`, runs the same strategies, trust model
and attacks over a real emulated network. Every server is a Mininet host
running an HTTP agent, every IoT device a host sending real tasks, and the
links carry real delays and bandwidth limits. It writes the same
`events.jsonl` recording, so `turncoat validate` and `turncoat score` grade it
unchanged. How it works is in
[backends/mininet/README.md](backends/mininet/README.md).

You do not need any of this to use the benchmark. The core package never
imports the backend, and `pytest` passes without it.

### What it needs

| Need | Why |
|---|---|
| Linux with root (`sudo`) | Mininet creates network namespaces and virtual links |
| Ubuntu 24.04 or newer, or another distribution with Python 3.11+ as `python3` | Mininet's Python bindings install into the system Python, and the core needs 3.11 or newer. Ubuntu 22.04 ships 3.10, which is too old |
| Mininet and Open vSwitch | The emulated network and its switches |
| os-ken (optional) | Only if you want an OpenFlow controller on the switches (`--of-controller`). By default the switches forward on their own and no controller is needed |

On **Windows**, use WSL 2 with Ubuntu 24.04 (`wsl --install -d Ubuntu-24.04`
in an administrator PowerShell, then reboot), and follow the Linux steps
inside it. The final-year project ran its live testbed this way. If
`openvswitch-switch` fails to start there, the WSL kernel lacks the Open
vSwitch module; use a Linux virtual machine instead. On **macOS**, use a
Linux virtual machine.

### Install it

Install the system packages and start Open vSwitch (these need your
password):

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3-venv iputils-ping
sudo service openvswitch-switch start
sudo mn --test pingall          # Mininet's own self-test; ends with "0% dropped"
```

Then create the virtual environment **with access to the system packages**,
so the venv's Python can import the Mininet that apt installed, and install
the core and the backend into it:

```bash
cd turncoat-sdn
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]" -e backends/mininet
.venv/bin/python -c "import mininet.net, turncoat_mininet; print('ok')"
```

If you already have a `.venv` made without `--system-site-packages`, delete
it and make it again; the last command prints `ok` only when both import.

### Check the live code paths first, without root

The loopback network runs the same agents, clients and controller as local
processes on 127.0.0.1, with no emulated links. It needs no Mininet and no
root, works on any OS, and takes about 45 seconds:

```bash
python -m turncoat_mininet.run --network loopback --scenario sybil --onset 10 --duration 30 -o loopback.jsonl
turncoat validate loopback.jsonl
turncoat score loopback.jsonl
```

If the backend is not installed (`pip install -e backends/mininet`), put it
on the path first: `PYTHONPATH=backends/mininet` on Linux and macOS,
`$env:PYTHONPATH="backends/mininet"` in PowerShell.

### Run on Mininet

Clean up anything a crashed run left behind, then run. A Sybil turns 20
seconds in, against `zt_sdn`, on 4 servers and 12 IoT devices for 60 seconds:

```bash
sudo mn -c
sudo .venv/bin/python -m turncoat_mininet.run --scenario sybil --onset 20 --duration 60 -o live.jsonl
sudo chown -R "$USER" live.jsonl logs
.venv/bin/turncoat validate live.jsonl
.venv/bin/turncoat score live.jsonl
```

The run builds the network, pings a sample of host pairs to check it is
wired, starts the agents and clients, runs for `--duration` seconds and tears
everything down. It prints a JSON summary of tasks offered, completed and
failed, and per-server counts. Agent and client logs go to `logs/`.
`--scenario`, `--attack`, `--onset`, `--strategy`, `--seed`, `--servers` and
`--clients` work as they do for `turncoat run`; the client attack (`spoof`)
is simulator-only for now. `python -m turncoat_mininet.run --help` lists
everything.

To run the live test on the testbed (it skips itself anywhere else):

```bash
sudo .venv/bin/python -m pytest -m live backends/mininet/tests
```

### Troubleshooting the testbed

| Symptom | Fix |
|---|---|
| `error: the Mininet network needs root` | Run the command with `sudo`, using the venv's Python by path: `sudo .venv/bin/python -m turncoat_mininet.run ...` |
| `error: Mininet is not importable from this Python` | The venv was made without `--system-site-packages`, or Mininet is not installed. Recreate the venv as above |
| `Exception: Error creating interface pair` or `File exists` | A previous run left links behind. Run `sudo mn -c` and try again |
| `ovs-vsctl: unix:/var/run/openvswitch/db.sock: database connection failed` | Open vSwitch is not running: `sudo service openvswitch-switch start` |
| `agents not answering by the start` | Read `logs/srv1_agent.log`. Usually the backend is not importable as root; install it into the venv with `pip install -e backends/mininet` |
| `client(s) not ready by the start` or `processes took ... longer than --warmup` | The machine took longer than `--warmup` (8 s) to start every process. Raise it, for example `--warmup 20` for 8 servers and 40 clients. The run refuses to start late, because the agents' attack onsets and the recording's clock would disagree |
| `reachability loss` warning, then failed tasks | The emulated network is not forwarding. Check `sudo ovs-vsctl show` lists `s0` to `sN`, then run `sudo mn -c` and retry |
| `Permission denied` reading `live.jsonl` | It was written as root. `sudo chown -R "$USER" live.jsonl logs` |

## Uninstall

```bash
python -m pip uninstall turncoat-sdn
```

Or delete the `.venv` folder to remove the environment and everything in it.

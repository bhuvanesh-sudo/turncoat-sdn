"""Golden file: a fixed seed gives fixed scores, end to end.

Each case runs ``turncoat run`` and then ``turncoat score --json`` at full
length, exactly as a user would, and compares the JSON with
``golden_scores.json``. A change anywhere in the chain (simulator, trust model,
strategy, recording, scorers) that moves a published number fails here.

If this fails, find out which change moved the numbers. Regenerate the file
only when the change is meant to move them, say so in the commit message, and
get the change reviewed:

    python tests/cli/test_golden.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN_PATH = Path(__file__).parent / "golden_scores.json"
SEED = 1000

#: Every strategy against both attackers, and zt_sdn against each scenario.
CASES = [(strategy, "both") for strategy in ("random", "round_robin", "least_conn", "no_trust")]
CASES += [("zt_sdn", scenario) for scenario in ("clean", "sybil", "drop", "both")]


def _case_id(case):
    return f"{case[0]}-{case[1]}"


def _scores(call, tmp_path, strategy, scenario):
    path = tmp_path / f"{strategy}-{scenario}.jsonl"
    code, _ = call(
        "run", "--strategy", strategy, "--scenario", scenario, "--seed", str(SEED),
        "-o", str(path), "-q",
    )  # fmt: skip
    assert code == 0
    code, out = call("score", str(path), "--json")
    assert code == 0
    return json.loads(out)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_scores_match_the_golden_file(turncoat, tmp_path, case):
    golden = json.loads(GOLDEN_PATH.read_text("utf-8"))
    assert _scores(turncoat, tmp_path, *case) == golden[_case_id(case)]


def test_golden_file_covers_every_case():
    golden = json.loads(GOLDEN_PATH.read_text("utf-8"))
    assert set(golden) == {_case_id(c) for c in CASES}


def _regenerate() -> None:  # pragma: no cover
    import contextlib
    import io
    import tempfile

    from turncoat_sdn.cli import main

    def call(*args):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(list(args))
        return code, buffer.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        golden = {_case_id(c): _scores(call, Path(tmp), *c) for c in CASES}
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", "utf-8")
    print(f"wrote {GOLDEN_PATH} ({len(golden)} cases)")


if __name__ == "__main__":  # pragma: no cover
    _regenerate()

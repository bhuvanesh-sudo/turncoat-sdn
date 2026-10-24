"""Tests for the reproducible strategy benchmark runner."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from turncoat_sdn.scoring.strategy_benchmark import (
    read_recording,
    run_benchmark,
)


def test_read_recording_loads_jsonl_objects(tmp_path: Path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"type":"header","seed":1}\n{"type":"route","task":1,"chosen":"srv1"}\n',
        encoding="utf-8",
    )

    assert read_recording(path) == [
        {"type": "header", "seed": 1},
        {"type": "route", "task": 1, "chosen": "srv1"},
    ]


def test_read_recording_rejects_invalid_json(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type":"header"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="line 2"):
        read_recording(path)


def test_benchmark_runs_every_matching_seed_and_writes_reports(
    tmp_path: Path,
):
    def fake_run(command, check):
        assert check is True
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(
            '{"type":"header","seed":1}\n{"type":"route","task":1,"chosen":"srv1"}\n',
            encoding="utf-8",
        )

    with (
        patch(
            "turncoat_sdn.scoring.strategy_benchmark.subprocess.run",
            side_effect=fake_run,
        ) as run_command,
        patch(
            "turncoat_sdn.scoring.strategy_benchmark.score_run",
            return_value=[],
        ),
    ):
        summaries = run_benchmark(
            strategies=("random", "zt_sdn"),
            scenarios=("clean",),
            seeds=(7, 8),
            duration=5,
            output_dir=tmp_path,
        )

    assert run_command.call_count == 4
    commands = [call.args[0] for call in run_command.call_args_list]
    assert {
        (cmd[cmd.index("--strategy") + 1], cmd[cmd.index("--seed") + 1]) for cmd in commands
    } == {
        ("random", "7"),
        ("random", "8"),
        ("zt_sdn", "7"),
        ("zt_sdn", "8"),
    }

    json_path = tmp_path / "strategy-benchmark.json"
    csv_path = tmp_path / "strategy-benchmark.csv"
    assert json_path.exists()
    assert csv_path.exists()
    report = json.loads(json_path.read_text(encoding="utf-8"))
    assert [item["name"] for item in report] == ["random", "zt_sdn"]
    assert [item.runs for item in summaries] == [2, 2]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"strategies": ()}, "At least one strategy"),
        ({"scenarios": ()}, "At least one scenario"),
        ({"seeds": ()}, "At least one seed"),
        ({"duration": 0}, "Duration must be positive"),
        ({"strategies": ("not-a-strategy",)}, "Unknown strategies"),
        ({"scenarios": ("not-a-scenario",)}, "Unknown scenarios"),
    ],
)
def test_benchmark_rejects_invalid_configuration(kwargs, message, tmp_path):
    options = {
        "strategies": ("random",),
        "scenarios": ("clean",),
        "seeds": (1,),
        "duration": 5,
        "output_dir": tmp_path,
    }
    options.update(kwargs)

    with pytest.raises(ValueError, match=message):
        run_benchmark(**options)

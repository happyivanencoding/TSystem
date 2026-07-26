from __future__ import annotations

from pathlib import Path

import tp_pipelines.common as pipeline_common
import tp_pipelines.run_backtest as run_backtest


def test_pipeline_calls_canonical_backtest_module(monkeypatch, tmp_path: Path) -> None:
    calls: list[tuple[str, list[str]]] = []

    def fake_run_python_module(module: str, args: list[str]) -> dict[str, object]:
        calls.append((module, args))
        return {"command": [module, *args], "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(run_backtest, "run_python_module", fake_run_python_module)
    monkeypatch.setattr(pipeline_common, "PIPELINE_MANIFESTS_DIR", tmp_path)
    args = run_backtest.build_parser().parse_args(["--inspect-only", "--run-type", "inspect"])

    manifest_path = run_backtest.run_backtest_step(args)

    assert calls == [("tp_backtest.cli", ["inspect", "--profile", "default"])]
    assert manifest_path.parent == tmp_path / "run_backtest"

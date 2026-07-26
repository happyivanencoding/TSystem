from __future__ import annotations

import json
from pathlib import Path
import sys
from types import ModuleType

import pandas as pd
import pytest

from tp_experiments.artifacts import experiment_plots_enabled
from tp_research.registry import HypothesisRegistry, run_definition


def _write_definition(root: Path, module: str = "tp_research.workflows.fake") -> Path:
    root.mkdir(parents=True)
    path = root / "configured-smoke.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "hypothesis_id": "configured-smoke",
                "name": "Configured smoke",
                "statement": "The configured runner is auditable.",
                "status": "research",
                "runner": {
                    "module": module,
                    "callable": "main",
                    "required_options": ["--market"],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_registry_loads_and_validates_definition(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    _write_definition(root)

    definition = HypothesisRegistry(root).load("configured-smoke")

    assert definition.hypothesis_id == "configured-smoke"
    assert definition.to_spec().trial_family == "configured-smoke"


def test_registry_rejects_non_research_package_entrypoint(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    _write_definition(root, module="outside.workflow")

    with pytest.raises(ValueError, match="tp_research.workflows"):
        HypothesisRegistry(root).load("configured-smoke")


def test_runner_requires_declared_options(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    _write_definition(root)
    definition = HypothesisRegistry(root).load("configured-smoke")

    with pytest.raises(ValueError, match="--market"):
        run_definition(definition, root=tmp_path / "runs")


def test_runner_applies_effective_default_artifact_policy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "registry"
    _write_definition(registry_root)
    definition = HypothesisRegistry(registry_root).load("configured-smoke")

    def fake_main(argv: list[str]) -> int:
        output_dir = Path(argv[argv.index("--output-dir") + 1])
        output_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "Date": ["2026-06-30"],
                "Weight": [1.0],
                "ISIN": ["FR0000000001"],
                "Name": ["Example"],
            }
        ).to_parquet(output_dir / "sec_list.parquet", index=False)
        if experiment_plots_enabled():
            (output_dir / "plot.html").write_text("plot", encoding="utf-8")
        return 0

    fake_module = ModuleType("tp_research.workflows.fake")
    fake_module.main = fake_main  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

    run_card = run_definition(
        definition,
        arguments=["--market", "smoke"],
        root=tmp_path / "runs",
    )

    payload = json.loads(run_card.read_text(encoding="utf-8"))
    holdings = pd.read_parquet(run_card.parent / "results" / "sec_list.parquet")
    assert list(holdings.columns) == ["Date", "Weight", "ISIN"]
    assert not (run_card.parent / "results" / "plot.html").exists()
    assert payload["parameters"]["artifact_policy"] == {
        "save_plots": False,
        "holdings_mode": "minimal",
    }
    assert payload["metrics"]["holdings_files_compacted"] == 1


def test_repository_registry_is_valid() -> None:
    definitions = HypothesisRegistry().list()

    assert len(definitions) >= 4
    assert {item.payload["status"] for item in definitions} <= {
        "draft",
        "research",
        "validated",
        "promoted",
        "rejected",
        "retired",
    }

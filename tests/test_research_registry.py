from __future__ import annotations

import json
from pathlib import Path

import pytest

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

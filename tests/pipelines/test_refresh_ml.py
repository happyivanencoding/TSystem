from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from importlib import import_module
from pathlib import Path


refresh_ml = import_module("tp_pipelines.refresh_ml")


def test_refresh_ml_inspect_uses_ml_cli(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeManifest:
        def __init__(self, step: str, parameters: dict[str, object]) -> None:
            self.step = step
            self.parameters = parameters
            self.inputs: dict[str, object] = {}
            self.outputs: dict[str, object] = {}
            self.details: dict[str, object] = {}
            self.validations: list[dict[str, object]] = []

        def add_validation(self, name: str, ok: bool, message: str = "", details: dict[str, object] | None = None) -> None:
            self.validations.append({"name": name, "ok": ok, "message": message, "details": details or {}})

        def write(self, status: str, *, error: BaseException | None = None) -> Path:
            self.status = status
            self.error = error
            return tmp_path / "refresh_ml_manifest.json"

    def fake_run(command, **kwargs):
        calls.append(list(command))
        payload = {"latest_scored_date": "2026-06-30", "is_current": True}
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(refresh_ml, "StepManifest", FakeManifest)
    monkeypatch.setattr(refresh_ml.subprocess, "run", fake_run)

    manifest_path = refresh_ml.run_refresh_ml(
        Namespace(
            date=None,
            from_date=None,
            to_date=None,
            universe=None,
            inspect_only=True,
            timeout_seconds=60,
            run_type="inspect",
        )
    )

    assert manifest_path.name == "refresh_ml_manifest.json"
    assert calls == [[sys.executable, "-m", "tp_models.ml.cli", "inspect", "--json"]]

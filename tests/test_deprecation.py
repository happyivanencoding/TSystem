from __future__ import annotations

import warnings

from tp_core.deprecation import warn_legacy_entrypoint


def test_legacy_entrypoint_warning_names_replacement() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_legacy_entrypoint("02_pipelines/run_all.py", "python -m tp_pipelines.run_all")

    assert len(caught) == 1
    assert caught[0].category is FutureWarning
    assert "python -m tp_pipelines.run_all" in str(caught[0].message)

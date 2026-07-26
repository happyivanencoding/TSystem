import json

import pandas as pd

from tp_research.workflows import run_stoxx600_lag6_relative_research as lag6
from tp_research.workflows import run_stoxx600_sparse_lag_extension_research as sparse


def test_lag6_registry_contains_every_level_transform_once():
    rows = []
    for spec in lag6.LEVEL_SPECS:
        for transform in lag6.TRANSFORMS:
            rows.append(
                {
                    "metric": lag6.relative_metric(
                        spec,
                        transform,
                        lag6.LAG,
                    ),
                    "raw_column": spec.raw_column,
                    "transform": transform,
                    "lag_observations": lag6.LAG,
                }
            )

    registry = lag6.build_registry(pd.DataFrame(rows))

    assert len(registry) == 62
    assert registry["metric"].nunique() == 62
    assert set(registry["transform"]) == {
        "directional_delta",
        "score_delta",
    }
    assert registry["lag_observations"].eq(6).all()
    assert registry["candidate_type"].eq("single").all()


def test_sparse_lag_registry_is_complete_and_lags_are_mutually_exclusive():
    screen = pd.DataFrame(
        {spec.metric: [1.0, 2.0] for spec in sparse.SIGNALS}
    )

    output, registry = sparse.build_candidate_registry(screen)

    assert len(registry) == 159
    assert registry["metric"].nunique() == 159
    assert registry["candidate_type"].value_counts().to_dict() == {
        "leave_one_out": 72,
        "core_sleeve_pair": 40,
        "core_plus_fixed_sleeve": 24,
        "single": 13,
        "core_pair": 7,
        "core_model": 3,
    }
    assert int(registry["deployable_architecture"].sum()) == 27

    raw_by_metric = {
        spec.metric: spec.raw_column for spec in sparse.SIGNALS
    }
    composites = registry.loc[~registry["candidate_type"].eq("single")]
    for components_text in composites["components"]:
        components = json.loads(components_text)
        raw_columns = [
            raw_by_metric[metric]
            for metric in components
            if metric in raw_by_metric
        ]
        assert len(raw_columns) == len(set(raw_columns))

    assert "stoxx600_sx_core_q3" in output
    assert "stoxx600_sx_core_q6" in output
    assert "stoxx600_sx_core_q12" in output


def test_sparse_synergy_is_incomplete_without_full_evidence_chain():
    screen = pd.DataFrame(
        {spec.metric: [1.0] for spec in sparse.SIGNALS}
    )
    _, registry = sparse.build_candidate_registry(screen)
    summary = pd.DataFrame(
        {
            "metric": [sparse.SIGNAL_BY_KEY["revision"].metric],
            "side": ["Top"],
            "status": ["success"],
        }
    )
    gate = pd.DataFrame(
        {
            "metric": [sparse.SIGNAL_BY_KEY["revision"].metric],
            "pass_gate": [True],
        }
    )

    evidence = sparse.build_synergy_evidence(summary, gate, registry)

    assert len(evidence) == 24
    assert evidence["classification"].eq("incomplete").all()
    assert not evidence["evidence_complete"].any()

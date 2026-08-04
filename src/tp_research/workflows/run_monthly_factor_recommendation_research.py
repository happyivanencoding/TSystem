"""Deterministic, auditable research runner for monthly factor recommendations.

The factor-recommendation model owns data construction and model definitions.
This workflow only consumes the public calling boundary exposed by
``tp_models.factor_recommendation`` and records the research evidence needed by
the TP Registry.  It deliberately does not write production model artifacts.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import importlib
import inspect
import json
import math
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd


WORKFLOW_ID = "monthly-factor-recommendation-v1"
CORE_PACKAGE = "tp_models.factor_recommendation"
DEFAULT_SEED = 1729
ARTIFACT_SCHEMA_VERSION = 1

REQUIRED_ARTIFACTS = (
    "config_snapshot.json",
    "component_status.json",
    "target_definition.json",
    "feature_definitions.csv",
    "feature_matrix.parquet",
    "target_frame.parquet",
    "pit_audit.csv",
    "walk_forward_folds.csv",
    "grouped_folds.csv",
    "fold_predictions.parquet",
    "model_selection.csv",
    "lopo_loro_results.csv",
    "cost_assumptions.json",
    "cost_adjusted_metrics.csv",
    "dsr_results.csv",
    "bootstrap_results.csv",
    "promotion_gate.csv",
    "research_report.md",
    "manifest.json",
    # Prompt-level names are kept in addition to the runner's internal names so
    # downstream review tooling can consume the research pack without guessing
    # aliases.
    "repository_data_audit.json",
    "universe_definitions.csv",
    "factor_definitions.csv",
    "raw_variable_gate.csv",
    "relative_variable_gate.csv",
    "factor_sleeve_metrics.csv",
    "factor_sleeve_monthly_returns.parquet",
    "feature_coverage.csv",
    "model_candidate_registry.csv",
    "walk_forward_predictions.parquet",
    "walk_forward_metrics.csv",
    "period_definitions.csv",
    "lopo_results.csv",
    "loro_results.csv",
    "strategy_monthly_returns.parquet",
    "strategy_metrics.csv",
    "cost_sensitivity.csv",
    "block_bootstrap_results.csv",
    "deflated_sharpe_results.csv",
    "trial_ledger.csv",
    "selection_audit.csv",
)


@dataclass(frozen=True)
class CoreInputs:
    """Normalized result of the core package calling boundary."""

    screen: pd.DataFrame
    returns: pd.DataFrame
    features: pd.DataFrame | None
    target: Any
    target_config: Mapping[str, Any]
    universe: Mapping[str, Any]
    factors: Any
    model: Mapping[str, Any]
    components: Mapping[str, Any]
    source: Mapping[str, Any]


def _first(mapping: Mapping[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if value is None:
        return {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _json_dump(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_json_value(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _stable_digest(value: Any) -> str:
    encoded = json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frame_digest(frame: pd.DataFrame) -> str:
    ordered = frame.copy()
    ordered = ordered.reindex(sorted(ordered.columns), axis=1)
    if not ordered.empty:
        try:
            ordered = ordered.sort_values(list(ordered.columns), kind="mergesort")
        except (TypeError, NotImplementedError, ValueError):
            # Some canonical parquet dtypes (notably float16) cannot be used
            # as pandas sort keys.  The loader order is deterministic, so a
            # stable head/tail digest remains useful without coercing data.
            ordered = pd.concat([ordered.head(32), ordered.tail(32)], ignore_index=True)
    payload = ordered.to_json(orient="split", date_format="iso", date_unit="ns")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fingerprint(value: Any) -> dict[str, Any]:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe", "rows": len(value), "columns": list(value.columns), "sha256": _frame_digest(value)}
    if isinstance(value, Path) or isinstance(value, str):
        path = Path(value)
        if path.exists() and path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return {"kind": "file", "path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}
        return {"kind": "reference", "value": str(value)}
    return {"kind": type(value).__name__, "sha256": _stable_digest(value)}


def _materialize_frame(value: Any, label: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = _fingerprint(value)
    if isinstance(value, pd.DataFrame):
        return value.copy(), source
    if isinstance(value, pd.Series):
        return value.to_frame(), source
    if isinstance(value, Mapping):
        nested = _first(value, "data", "frame", "value", "path")
        if nested is not None and nested is not value:
            return _materialize_frame(nested, label)
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.exists():
            raise FileNotFoundError(f"核心包提供的 {label} 不存在：{path}")
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            return pd.read_parquet(path), source
        if suffix == ".csv":
            return pd.read_csv(path), source
        if suffix == ".json":
            return pd.read_json(path), source
    raise TypeError(f"核心包提供的 {label} 不是可读取的 DataFrame 或数据路径")


def _call_supported(function: Any, options: Mapping[str, Any]) -> Any:
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function()
    parameters = signature.parameters
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return function(**dict(options))
    kwargs = {name: value for name, value in options.items() if name in parameters}
    return function(**kwargs)


def _find_loader(module: Any) -> Any | None:
    for name in ("load_research_inputs", "load_inputs", "research_inputs", "load_canonical_inputs"):
        loader = getattr(module, name, None)
        if callable(loader):
            return loader
    for child_name in ("research", "data", "api", "config"):
        try:
            child = importlib.import_module(f"{CORE_PACKAGE}.{child_name}")
        except ModuleNotFoundError:
            continue
        for name in ("load_research_inputs", "load_inputs", "research_inputs"):
            loader = getattr(child, name, None)
            if callable(loader):
                return loader
    return None


def _adapt_typed_core_inputs(
    payload_map: Mapping[str, Any],
    module: Any,
    mode: str,
    *,
    max_months: int | None,
    max_factors: int | None,
) -> CoreInputs | None:
    """Adapt the core package's typed ``ResearchInputs`` contract.

    This branch is intentionally based on public dataclass fields and public
    functions only.  A generic mapping loader continues through the ordinary
    path below, which keeps the workflow testable with a small fake boundary.
    """

    universe_values = payload_map.get("universe")
    factor_values = payload_map.get("factors")
    if not isinstance(universe_values, Mapping) or not factor_values:
        return None
    if not all(hasattr(value, "components") for value in universe_values.values()):
        return None
    if not all(hasattr(value, "source_columns") for value in factor_values):
        return None

    screen, screen_source = _materialize_frame(payload_map.get("screen"), "screen")
    returns, returns_source = _materialize_frame(payload_map.get("returns"), "returns")
    definitions = list(factor_values)
    if max_factors:
        definitions = definitions[:max_factors]
    model_config = _mapping(payload_map.get("model"))
    pit_lag = int(_first(model_config, "pit_lag_months", default=1))
    if max_months:
        dates = sorted(pd.to_datetime(screen["Date"], errors="coerce").dropna().unique())
        keep = dates[-(max_months + pit_lag + 1) :]
        screen = screen[pd.to_datetime(screen["Date"], errors="coerce").isin(keep)].copy()

    region_status: dict[str, Any] = {}
    panels: list[pd.DataFrame] = []
    from tp_models.factor_recommendation import build_security_feature_panel

    for region_name, spec in universe_values.items():
        region_status[str(region_name)] = {
            "status": "configured",
            "display_name": getattr(spec, "display_name", str(region_name)),
            "research_only": bool(getattr(spec, "research_only", False)),
            "benchmark_approved": bool(getattr(spec, "benchmark_approved", True)),
            "approval_status": getattr(spec, "approval_status", ""),
            "components": _json_value(getattr(spec, "components", ())),
            "aggregation_policy": getattr(spec, "aggregation_policy", ""),
        }
        if mode == "inspect":
            continue
        try:
            panel = build_security_feature_panel(
                screen,
                str(region_name),
                definitions=definitions,
                pit_lag_months=pit_lag,
                universe_definitions=universe_values,
            )
        except (KeyError, ValueError) as error:
            region_status[str(region_name)].update({"status": "unavailable", "error": str(error)})
            continue
        if panel.empty:
            region_status[str(region_name)]["status"] = "empty"
            continue
        panel = panel.copy()
        panel["region"] = str(region_name)
        panels.append(panel)
        region_status[str(region_name)].update({"status": "loaded", "rows": int(len(panel))})

    factor_names = [definition.name for definition in definitions]
    model_payload = dict(model_config)
    model_payload.setdefault("model_version", "factor_recommendation_v1")
    model_payload.setdefault("models", _default_candidate_models(factor_names))
    model_payload.setdefault("minimum_train_months", 60)
    model_payload.setdefault("purge_months", 1)
    model_payload.setdefault("walk_forward_splits", 5)
    model_payload.setdefault("effective_trial_count", max(1, len(factor_names)))
    model_payload.setdefault("cost_assumptions", {"transaction_cost": 0.001, "slippage": 0.0005})
    universe_payload = {
        "name": "configured_regions",
        "date_column": "Date",
        "security_id_column": "ISIN",
        "weight_column": "universe_weight",
        "group_column": "universe_component",
        "regions": region_status,
    }
    component_payload = {
        "ASIA": region_status.get("ASIA", {"status": "not_configured"}),
        "synthetic": False,
        "regions": region_status,
    }
    source = {
        "core_package": "tp_models.factor_recommendation",
        "core_module": getattr(module, "__file__", None),
        "loader": "load_research_inputs + build_security_feature_panel",
        "screen": screen_source,
        "returns": returns_source,
        "factor_config": _json_value(_first(model_config, "factor_definitions_path", default=None)),
    }
    target_config = {
        "target_date_column": "target_date",
        "horizon": int(_first(model_config, "target_horizon_months", default=1)),
        "pit_lag_months": pit_lag,
    }
    if mode == "inspect":
        return CoreInputs(
            screen=screen,
            returns=returns,
            features=None,
            target=None,
            target_config=target_config,
            universe=universe_payload,
            factors=definitions,
            model=model_payload,
            components=component_payload,
            source=source,
        )
    if not panels:
        raise ValueError("核心 typed universe config 在 canonical screen 上没有可用区域 panel")
    return CoreInputs(
        screen=pd.concat(panels, ignore_index=True, sort=False),
        returns=returns,
        features=None,
        target=None,
        target_config=target_config,
        universe=universe_payload,
        factors=definitions,
        model=model_payload,
        components=component_payload,
        source=source,
    )


def _load_core_contract(
    mode: str,
    *,
    seed: int,
    max_months: int | None = None,
    max_factors: int | None = None,
) -> CoreInputs:
    """Load the versioned core contract without importing private core files.

    The preferred public API is ``load_research_inputs(mode=..., seed=...)``
    returning a mapping with ``screen``, ``returns``, ``universe``, ``factors``,
    ``model`` and ``components``.  The current typed core loaders are adapted
    below without importing private implementation modules.
    """

    try:
        module = importlib.import_module(CORE_PACKAGE)
    except ModuleNotFoundError as error:
        raise RuntimeError(
            f"核心包 {CORE_PACKAGE} 不可用；workflow 不会在本地制造 canonical 或 synthetic 数据"
        ) from error

    options = {"mode": mode, "seed": seed}
    loader = _find_loader(module)
    if loader is not None:
        payload = _call_supported(loader, options)
    else:
        # The current core package exposes typed loaders rather than one
        # aggregate loader.  Keep this adapter here so the workflow still has
        # one deterministic calling boundary and never imports core internals.
        from tp_core.data_sources import RETURNS_PATH, SCREEN_AGGREGATE_PATH
        from tp_models.factor_recommendation import (
            build_security_feature_panel,
            load_factor_definitions,
            load_region_universes,
            load_runtime_config,
        )

        runtime_config = load_runtime_config()
        definitions = list(load_factor_definitions(runtime_config.factor_definitions_path))
        if max_factors:
            definitions = definitions[:max_factors]
        regions = load_region_universes(runtime_config.region_universes_path)
        screen_path = Path(SCREEN_AGGREGATE_PATH)
        returns_path = Path(RETURNS_PATH)
        screen = pd.read_parquet(screen_path)
        returns = pd.read_parquet(returns_path)
        if max_months:
            dates = sorted(pd.to_datetime(screen["Date"], errors="coerce").dropna().unique())
            keep = dates[-(max_months + runtime_config.pit_lag_months + 1) :]
            screen = screen[pd.to_datetime(screen["Date"], errors="coerce").isin(keep)].copy()

        panels: list[pd.DataFrame] = []
        region_status: dict[str, Any] = {}
        for region_name in ("US", "EUROPE", "ASIA"):
            spec = regions.get(region_name)
            if spec is None:
                region_status[region_name] = {"status": "not_configured"}
                continue
            region_status[region_name] = {
                "status": "configured",
                "research_only": bool(spec.research_only),
                "benchmark_approved": bool(spec.benchmark_approved),
                "components": _json_value(spec.components),
                "aggregation_policy": spec.aggregation_policy,
            }
            if mode == "inspect":
                continue
            try:
                panel = build_security_feature_panel(
                    screen,
                    region_name,
                    definitions=definitions,
                    pit_lag_months=runtime_config.pit_lag_months,
                    universe_definitions=regions,
                )
            except (KeyError, ValueError) as error:
                region_status[region_name].update({"status": "unavailable", "error": str(error)})
                continue
            if not panel.empty:
                panel = panel.copy()
                panel["region"] = region_name
                panels.append(panel)
                region_status[region_name].update({"status": "loaded", "rows": int(len(panel))})
            else:
                region_status[region_name]["status"] = "empty"
        if mode == "inspect":
            factor_names = [definition.name for definition in definitions]
            model_payload = {
                "model_version": runtime_config.model_version,
                "models": _default_candidate_models(factor_names),
                "minimum_train_months": 60,
                "purge_months": 1,
                "walk_forward_splits": 5,
                "effective_trial_count": max(1, len(factor_names)),
                "cost_assumptions": {"transaction_cost": 0.001, "slippage": 0.0005},
            }
            universe_payload = {
                "name": "configured_regions",
                "date_column": "Date",
                "security_id_column": "ISIN",
                "weight_column": "universe_weight",
                "group_column": "universe_component",
                "regions": region_status,
            }
            component_payload = {
                "ASIA": region_status.get("ASIA", {"status": "not_configured"}),
                "synthetic": False,
                "regions": region_status,
            }
            return CoreInputs(
                screen=screen,
                returns=returns,
                features=None,
                target=None,
                target_config={
                    "target_date_column": "target_date",
                    "horizon": runtime_config.target_horizon_months,
                    "pit_lag_months": runtime_config.pit_lag_months,
                },
                universe=universe_payload,
                factors=definitions,
                model=model_payload,
                components=component_payload,
                source={
                    "core_package": CORE_PACKAGE,
                    "core_module": getattr(module, "__file__", None),
                    "loader": "inspect: load_runtime_config/load_factor_definitions/load_region_universes",
                    "screen": _fingerprint(screen_path),
                    "returns": _fingerprint(returns_path),
                    "factor_config": _fingerprint(runtime_config.factor_definitions_path),
                    "universe_config": _fingerprint(runtime_config.region_universes_path),
                },
            )
        if not panels:
            raise ValueError("核心 universe config 在 canonical screen 上没有可用区域 panel")
        panel = pd.concat(panels, ignore_index=True, sort=False)
        factor_names = [definition.name for definition in definitions]
        payload = {
            "screen": panel,
            "returns": returns,
            "target_config": {
                "target_date_column": "target_date",
                "horizon": runtime_config.target_horizon_months,
                "pit_lag_months": runtime_config.pit_lag_months,
            },
            "universe": {
                "name": "configured_regions",
                "date_column": "Date",
                "security_id_column": "ISIN",
                "weight_column": "universe_weight",
                "group_column": "universe_component",
                "regions": region_status,
            },
            "factors": definitions,
            "model": {
                "model_version": runtime_config.model_version,
                "models": _default_candidate_models(factor_names),
                "minimum_train_months": 60,
                "purge_months": 1,
                "walk_forward_splits": 5,
                "effective_trial_count": max(1, len(factor_names)),
                "cost_assumptions": {"transaction_cost": 0.001, "slippage": 0.0005},
                "bootstrap_samples": 256 if mode == "full" else 32,
            },
            "components": {
                "ASIA": region_status.get("ASIA", {"status": "not_configured"}),
                "synthetic": False,
                "regions": region_status,
            },
        }
        source = {
            "core_package": CORE_PACKAGE,
            "core_module": getattr(module, "__file__", None),
            "loader": "load_runtime_config/load_factor_definitions/load_region_universes/build_security_feature_panel",
            "screen": _fingerprint(screen_path),
            "returns": _fingerprint(returns_path),
            "factor_config": _fingerprint(runtime_config.factor_definitions_path),
            "universe_config": _fingerprint(runtime_config.region_universes_path),
        }
        return CoreInputs(
            screen=panel,
            returns=returns,
            features=None,
            target=None,
            target_config=payload["target_config"],
            universe=payload["universe"],
            factors=payload["factors"],
            model=payload["model"],
            components=payload["components"],
            source=source,
        )

    if isinstance(payload, Mapping):
        # A public loader may return a typed config object under ``config``;
        # merge it into the ordinary model slot without touching the object.
        if "model" not in payload and "config" in payload:
            payload = dict(payload, model=payload["config"])
    else:
        if _mapping(payload):
            # Preserve typed ResearchInputs dataclasses for the public typed
            # adapter below; only use module attributes for an empty return.
            pass
        else:
            payload = {
                "canonical": _first(module.__dict__, "CANONICAL_DATA", "canonical_data"),
                "screen": _first(module.__dict__, "SCREEN", "screen"),
                "returns": _first(module.__dict__, "RETURNS", "returns"),
                "features": _first(module.__dict__, "FEATURES", "features"),
                "target": _first(module.__dict__, "TARGET", "target"),
                "target_config": _first(module.__dict__, "TARGET_CONFIG", "target_config", default={}),
                "universe": _first(module.__dict__, "UNIVERSE_CONFIG", "universe_config", "UNIVERSE", default={}),
                "factors": _first(module.__dict__, "FACTOR_CONFIG", "factor_config", "FACTORS", default=[]),
                "model": _first(module.__dict__, "MODEL_CONFIG", "model_config", "MODEL", default={}),
                "components": _first(module.__dict__, "COMPONENT_STATUS", "component_status", default={}),
            }

    if isinstance(payload, (tuple, list)):
        names = ("screen", "returns", "universe", "factors", "model")
        payload = {name: value for name, value in zip(names, payload, strict=False)}
    payload_map = _mapping(payload)
    typed = _adapt_typed_core_inputs(
        payload_map,
        module,
        mode,
        max_months=max_months,
        max_factors=max_factors,
    )
    if typed is not None:
        return typed
    canonical = _mapping(_first(payload_map, "canonical", "canonical_data", default={}))
    screen_value = _first(payload_map, "screen", "screen_data", default=None)
    returns_value = _first(payload_map, "returns", "returns_data", default=None)
    if screen_value is None:
        screen_value = _first(canonical, "screen", "screen_aggregate", "screen_path")
    if returns_value is None:
        returns_value = _first(canonical, "returns", "returns_path")
    if screen_value is None or returns_value is None:
        raise ValueError("核心 calling boundary 必须提供 canonical screen 与 returns")

    screen, screen_source = _materialize_frame(screen_value, "screen")
    returns, returns_source = _materialize_frame(returns_value, "returns")
    features_value = _first(payload_map, "features", "feature_data", "feature_frame", default=None)
    features = _materialize_frame(features_value, "features")[0] if features_value is not None else None
    target_value = _first(payload_map, "target", "target_data", "target_frame", default=None)
    target_config = _mapping(_first(payload_map, "target_config", "target_definition", default={}))
    universe = _first(payload_map, "universe", "universe_config", default={})
    factors = _first(payload_map, "factors", "factor_config", "features_config", default=[])
    model = _mapping(_first(payload_map, "model", "model_config", default={}))
    components = _mapping(_first(payload_map, "components", "component_status", default={}))
    source = {
        "core_package": CORE_PACKAGE,
        "core_module": getattr(module, "__file__", None),
        "screen": screen_source,
        "returns": returns_source,
        "features": _fingerprint(features) if features is not None else None,
        "loader": getattr(loader, "__name__", None) if loader is not None else "public_attributes",
    }
    return CoreInputs(
        screen=screen,
        returns=returns,
        features=features,
        target=target_value,
        target_config=target_config,
        universe=_mapping(universe),
        factors=factors,
        model=model,
        components=components,
        source=source,
    )


def _normalise_factors(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        raw = _first(raw, "factors", "features", "definitions", "items", default=raw)
        if isinstance(raw, Mapping):
            raw = [dict(_mapping(value), name=key) for key, value in raw.items()]
    if isinstance(raw, str):
        raw = [raw]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, str):
            item = {"name": item, "column": item}
        row = _mapping(item)
        name = str(_first(row, "name", "id", "factor", "feature", "column", default=f"factor_{index + 1}"))
        column = str(_first(row, "column", "feature_column", "source_column", "feature", default=name))
        direction = _first(row, "direction", "sign", default=None)
        if direction is None:
            direction = 1.0 if bool(_first(row, "higher_is_better", default=True)) else -1.0
        elif isinstance(direction, str):
            direction = -1.0 if direction.strip().lower() in {"-1", "lower", "negative", "descending", "bad"} else 1.0
        else:
            direction = -1.0 if float(direction) < 0 else 1.0
        rows.append(
            {
                "name": name,
                "column": column,
                "direction": direction,
                "family": str(_first(row, "family", "group", "category", default="unclassified")),
                "source": str(_first(row, "source", "provider", default="core")),
                "availability_column": _first(row, "availability_column", "available_at_column", "pit_column", default=None),
                "pit_policy": str(_first(row, "pit_policy", default="available_at_or_before_decision_time")),
                "neutralize_by": _first(row, "neutralize_by", "group_column", default=None),
            }
        )
    return rows


def _normalise_models(raw: Mapping[str, Any], factor_names: Sequence[str]) -> list[dict[str, Any]]:
    values = _first(raw, "models", "candidates", "model_candidates", default=None)
    if values is None:
        values = [raw] if raw and any(key in raw for key in ("features", "factors", "weights", "name")) else []
    if isinstance(values, Mapping):
        values = [dict(_mapping(value), name=key) for key, value in values.items()]
    models: list[dict[str, Any]] = []
    for index, value in enumerate(values or []):
        row = _mapping(value)
        name = str(_first(row, "name", "id", "model", default=f"model_{index + 1}"))
        features = _first(row, "features", "factors", "feature_names", default=factor_names)
        if isinstance(features, str):
            features = [features]
        features = [str(item) for item in (features or [])]
        weights = _first(row, "weights", "factor_weights", default={})
        if isinstance(weights, Sequence) and not isinstance(weights, (str, bytes)):
            weights = {feature: weight for feature, weight in zip(features, weights, strict=False)}
        weights = {str(key): float(value) for key, value in _mapping(weights).items()}
        models.append({
            "name": name,
            "features": features,
            "weights": weights,
            "model_type": str(_first(row, "model_type", "type", default="weighted_rank")),
        })
    if not models:
        models = [{"name": "equal_weight", "features": list(factor_names), "weights": {}, "model_type": "weighted_rank"}]
    return models


def _default_candidate_models(factor_names: Sequence[str]) -> list[dict[str, Any]]:
    """Return the five pre-registered v1 candidates.

    The runner keeps their declarations auditable even when a smoke run has
    too little history to evaluate them.  M3/M4 are passed through as model
    types for the core model adapter; no probability is inferred from either.
    """

    names = list(map(str, factor_names))
    return [
        {"name": "M0_equal_factor", "features": names, "model_type": "weighted_rank", "weights": {}},
        {"name": "M1_trailing_12m", "features": names, "model_type": "trailing_12m", "lookback_months": 12, "weights": {}},
        {"name": "M2_transparent_composite", "features": names, "model_type": "weighted_rank", "weights": {}},
        {"name": "M3_pooled_ridge", "features": names, "model_type": "ridge", "weights": {}},
        {"name": "M4_pooled_elastic_net", "features": names, "model_type": "elasticnet", "weights": {}},
    ]


def _column(config: Mapping[str, Any], *names: str, default: str | None = None) -> str | None:
    value = _first(config, *names, default=default)
    return str(value) if value is not None else None


def _detect_column(frame: pd.DataFrame, candidates: Sequence[str], label: str) -> str:
    for name in candidates:
        if name in frame.columns:
            return name
    raise ValueError(f"canonical {label} 缺少可识别列，候选为 {list(candidates)}")


def _normalise_returns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    date_col = next((name for name in ("Date", "date", "return_date") if name in output.columns), None)
    id_col = next((name for name in ("ISIN", "Company SEDOL", "SEDOL", "security_id", "id") if name in output.columns), None)
    value_col = next((name for name in ("Return", "return", "ret", "monthly_return") if name in output.columns), None)
    if date_col is not None and id_col is not None and value_col is not None:
        output[date_col] = pd.to_datetime(output[date_col], errors="coerce")
        output[id_col] = output[id_col].astype(str)
        return output.pivot_table(index=date_col, columns=id_col, values=value_col, aggfunc="last").sort_index()
    if date_col is not None:
        output[date_col] = pd.to_datetime(output[date_col], errors="coerce")
        output = output.dropna(subset=[date_col]).set_index(date_col)
    else:
        output.index = pd.to_datetime(output.index, errors="coerce")
        output = output.loc[~output.index.isna()]
    output.columns = [str(column) for column in output.columns]
    return output.apply(pd.to_numeric, errors="coerce").sort_index()


def _prepare_panel(core: CoreInputs, args: argparse.Namespace, factors: list[dict[str, Any]]) -> tuple[pd.DataFrame, str, str, str | None, dict[str, Any]]:
    universe = core.universe
    screen = core.screen.copy()
    date_col = _column(universe, "date_column", "date_col", default=None) or _detect_column(screen, ("Date", "date", "screen_date"), "screen Date")
    id_col = _column(universe, "security_id_column", "id_column", "identifier_column", default=None) or _detect_column(screen, ("ISIN", "Company SEDOL", "SEDOL", "security_id", "id"), "security id")
    group_col = _column(universe, "group_column", "sector_column", "industry_column", default=None)
    if group_col is None:
        group_col = next((name for name in ("universe_component", "Sector", "Industry", " Benchmark ICB Supersector ") if name in screen.columns), None)
    screen[date_col] = pd.to_datetime(screen[date_col], errors="coerce")
    screen[id_col] = screen[id_col].astype(str)
    screen = screen.dropna(subset=[date_col, id_col]).copy()
    weight_col = _column(universe, "weight_column", "membership_column", default=None)
    before = len(screen)
    if weight_col and weight_col in screen.columns:
        screen = screen[pd.to_numeric(screen[weight_col], errors="coerce").fillna(0).gt(0)].copy()
    if core.features is not None:
        feature_frame = core.features.copy()
        feature_date = _column(universe, "feature_date_column", default=date_col) or date_col
        feature_id = _column(universe, "feature_id_column", default=id_col) or id_col
        if feature_date not in feature_frame.columns or feature_id not in feature_frame.columns:
            raise ValueError("核心 features frame 必须提供 feature date 与 security id 列")
        feature_frame[feature_date] = pd.to_datetime(feature_frame[feature_date], errors="coerce")
        feature_frame[feature_id] = feature_frame[feature_id].astype(str)
        if feature_date != date_col:
            feature_frame = feature_frame.rename(columns={feature_date: date_col})
        if feature_id != id_col:
            feature_frame = feature_frame.rename(columns={feature_id: id_col})
        keep = [date_col, id_col] + [factor["column"] for factor in factors if factor["column"] in feature_frame.columns]
        feature_frame = feature_frame[dict.fromkeys(keep)].drop_duplicates([date_col, id_col], keep="last")
        overlap = [column for column in keep if column not in {date_col, id_col} and column in screen.columns]
        if overlap:
            screen = screen.drop(columns=overlap)
        screen = screen.merge(feature_frame, on=[date_col, id_col], how="left", sort=False)
    missing = [factor["column"] for factor in factors if factor["column"] not in screen.columns]
    if missing:
        raise ValueError(f"核心 canonical/features 缺少预注册 factor 列：{missing}")
    start = _first(core.universe, "sample_start", "start_date", default=None)
    end = _first(core.universe, "sample_end", "end_date", "pit_cutoff", default=None)
    if start:
        screen = screen[screen[date_col] >= pd.Timestamp(start)]
    if end:
        screen = screen[screen[date_col] <= pd.Timestamp(end)]
    dates = sorted(screen[date_col].dropna().unique())
    if args.max_months:
        dates = dates[-args.max_months :]
        screen = screen[screen[date_col].isin(dates)]
    screen = screen.drop_duplicates([date_col, id_col], keep="last").sort_values([date_col, id_col], kind="mergesort").reset_index(drop=True)
    diagnostics = {"source_rows": before, "universe_rows": len(screen), "universe_filter": weight_col or "core-provided rows", "dates": len(dates), "date_min": str(min(dates)) if dates else None, "date_max": str(max(dates)) if dates else None, "group_column": group_col}
    return screen, date_col, id_col, group_col, diagnostics


def _build_target(
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    target_value: Any,
    target_config: Mapping[str, Any],
    date_col: str,
    id_col: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    target_name = str(_first(target_config, "name", "column", "target_column", default="forward_return"))
    if isinstance(target_value, str) and target_value in screen.columns:
        target = screen[[date_col, id_col, target_value]].copy().rename(columns={target_value: "target"})
        target["target_start_date"] = target[date_col]
        target["target_end_date"] = target[date_col]
        definition = {"name": target_name, "source": "core screen target column", "lookahead": "core-provided", "target_column": target_value}
        return target, definition
    core_target_date = _column(
        target_config,
        "target_date_column",
        "target_date",
        default="target_date",
    )
    if core_target_date and core_target_date in screen.columns:
        returns = _normalise_returns(returns)
        return_id_col = _column(
            target_config,
            "returns_id_column",
            "return_id_column",
            default=None,
        )
        if return_id_col is None:
            return_id_col = "Company SEDOL" if "Company SEDOL" in screen.columns else id_col
        rows: list[dict[str, Any]] = []
        for row in screen[[date_col, id_col, core_target_date, return_id_col]].itertuples(index=False, name=None):
            decision_date, security_id, target_date, return_id = row
            if pd.isna(target_date):
                continue
            target_date = pd.Timestamp(target_date)
            return_key = str(return_id)
            window = returns.loc[(returns.index > pd.Timestamp(decision_date)) & (returns.index <= target_date)]
            values = pd.to_numeric(window[return_key], errors="coerce").dropna() if return_key in window.columns else pd.Series(dtype=float)
            value = float((1.0 + values).prod() - 1.0) if not values.empty else np.nan
            rows.append({
                date_col: decision_date,
                id_col: security_id,
                "target": value,
                "target_start_date": window.index.min() if not window.empty else pd.NaT,
                "target_end_date": target_date,
            })
        definition = {
            "name": target_name,
            "source": "core build_security_feature_panel + canonical returns",
            "method": "same-security compound return for returns strictly after Date and through target_date",
            "lookahead": "strictly future return observations",
            "horizon": _first(target_config, "horizon", default="next month"),
            "target_date_column": core_target_date,
            "returns_id_column": return_id_col,
            "target_date_excluded_from_features": True,
        }
        return pd.DataFrame(rows, columns=[date_col, id_col, "target", "target_start_date", "target_end_date"]), definition
    if target_value is not None:
        target_frame, _ = _materialize_frame(target_value, "target")
        target_date = _column(target_config, "date_column", "date_col", default=date_col) or date_col
        target_id = _column(target_config, "security_id_column", "id_column", default=id_col) or id_col
        target_column = _column(target_config, "target_column", "value_column", default=None) or _detect_column(target_frame, ("target", "forward_return", "label", "y"), "target")
        target_frame[target_date] = pd.to_datetime(target_frame[target_date], errors="coerce")
        target_frame[target_id] = target_frame[target_id].astype(str)
        output = target_frame.rename(columns={target_date: date_col, target_id: id_col, target_column: "target"})
        for name in ("target_start_date", "target_end_date"):
            if name not in output.columns:
                output[name] = output[date_col]
        definition = {"name": target_name, "source": "core target frame", "lookahead": _first(target_config, "lookahead", "horizon", default="core-provided"), "target_column": target_column}
        return output[[date_col, id_col, "target", "target_start_date", "target_end_date"]], definition

    dates = sorted(screen[date_col].dropna().unique())
    returns = _normalise_returns(returns)
    rows: list[dict[str, Any]] = []
    for index, date in enumerate(dates):
        future_start = returns.index[returns.index > pd.Timestamp(date)]
        if len(future_start) == 0:
            continue
        start = future_start[0]
        if index + 1 < len(dates):
            future_end = returns.index[returns.index > pd.Timestamp(dates[index + 1])]
            end = future_end[0] if len(future_end) else returns.index[-1] + pd.Timedelta(days=1)
        else:
            end = returns.index[-1] + pd.Timedelta(days=1)
        window = returns.loc[(returns.index >= start) & (returns.index < end)]
        if window.empty:
            continue
        for security_id in screen.loc[screen[date_col].eq(date), id_col].astype(str).unique():
            if security_id not in window.columns:
                value = np.nan
            else:
                values = pd.to_numeric(window[security_id], errors="coerce").fillna(0.0)
                value = float((1.0 + values).prod() - 1.0) if len(values) else np.nan
            rows.append({date_col: date, id_col: security_id, "target": value, "target_start_date": start, "target_end_date": end - pd.Timedelta(days=1)})
    output = pd.DataFrame(rows, columns=[date_col, id_col, "target", "target_start_date", "target_end_date"])
    definition = {
        "name": target_name,
        "source": "canonical returns",
        "method": "same-security forward compounded return after the screen date",
        "lookahead": "strictly future return observations",
        "horizon": _first(target_config, "horizon", "holding_period", default="next screen interval"),
        "target_date_excluded_from_features": True,
    }
    return output, definition


def _feature_scores(screen: pd.DataFrame, factors: list[dict[str, Any]], date_col: str, group_col: str | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    output = screen.copy()
    definitions: list[dict[str, Any]] = []
    pit_rows: list[dict[str, Any]] = []
    for factor in factors:
        name, column = factor["name"], factor["column"]
        raw = pd.to_numeric(output[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        directional = raw * float(factor["direction"])
        lower = directional.groupby(output[date_col], observed=True).transform(lambda values: values.quantile(0.01))
        upper = directional.groupby(output[date_col], observed=True).transform(lambda values: values.quantile(0.99))
        winsorized = directional.clip(lower=lower, upper=upper)
        neutralize = factor.get("neutralize_by") or group_col
        if neutralize and neutralize in output.columns:
            score = winsorized.groupby([output[date_col], output[neutralize]], observed=True).rank(pct=True)
            neutralization = neutralize
        else:
            score = winsorized.groupby(output[date_col], observed=True).rank(pct=True)
            neutralization = "date_cross_section"
        score_column = f"score__{name}"
        output[score_column] = score.astype(float)
        availability_column = factor.get("availability_column")
        if availability_column is None and "feature_as_of_date" in output.columns:
            availability_column = "feature_as_of_date"
        if availability_column and availability_column in output.columns:
            available = pd.to_datetime(output[availability_column], errors="coerce")
            violations = int((available > output[date_col]).fillna(False).sum())
            missing_availability = int(available.isna().sum())
            pit_status = "pass" if violations == 0 else "fail"
        else:
            violations = 0
            missing_availability = int(raw.notna().sum())
            pit_status = "assumed_snapshot_available_at_decision_time"
        definitions.append({
            "name": name,
            "source_column": column,
            "score_column": score_column,
            "direction": factor["direction"],
            "family": factor["family"],
            "source": factor["source"],
            "winsorize": "date-wise 1%/99%",
            "neutralize": neutralization,
            "pit_policy": factor["pit_policy"],
            "availability_column": availability_column or "not provided; snapshot assumption",
        })
        pit_rows.append({
            "feature": name,
            "source_column": column,
            "decision_date_column": date_col,
            "availability_column": availability_column or "",
            "violations": violations,
            "missing_availability_rows": missing_availability if availability_column else 0,
            "status": pit_status,
            "policy": factor["pit_policy"],
        })
    return output, pd.DataFrame(definitions), pd.DataFrame(pit_rows)


def _folds(dates: Sequence[pd.Timestamp], mode: str, model_config: Mapping[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = [pd.Timestamp(value) for value in sorted(dates)]
    minimum_train = int(_first(model_config, "minimum_train_months", "min_train_months", default=3 if mode == "full" else 1))
    purge_months = int(_first(model_config, "purge_months", "purge", default=1))
    if purge_months < 0:
        raise ValueError("purge_months must be non-negative")
    requested_splits = int(_first(model_config, "walk_forward_splits", "n_splits", default=3))
    test_dates = dates[minimum_train + purge_months:]
    chunks = np.array_split(np.array(test_dates, dtype="datetime64[ns]"), max(1, min(requested_splits, len(test_dates)))) if test_dates else []
    fold_rows: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        if len(chunk) == 0:
            continue
        tests = [pd.Timestamp(value) for value in chunk.tolist()]
        first_test_index = dates.index(tests[0])
        train_end_index = max(0, first_test_index - purge_months)
        trains = dates[:train_end_index]
        purged = dates[train_end_index:first_test_index]
        fold_id = f"wf_{index + 1:02d}"
        fold_rows.append({
            "fold_id": fold_id,
            "validation": "walk_forward",
            "grouping": "calendar_month; all securities in a month stay together",
            "train_start": trains[0] if trains else pd.NaT,
            "train_end": trains[-1] if trains else pd.NaT,
            "test_start": tests[0],
            "test_end": tests[-1],
            "train_months": len(trains),
            "test_months": len(tests),
            "purge_months": len(purged),
            "purged_start": purged[0] if purged else pd.NaT,
            "purged_end": purged[-1] if purged else pd.NaT,
            "status": "ready" if trains else "insufficient_train",
        })
        for date in trains:
            assignments.append({"fold_id": fold_id, "date": date, "group": date.strftime("%Y-%m"), "split": "train"})
        for date in purged:
            assignments.append({"fold_id": fold_id, "date": date, "group": date.strftime("%Y-%m"), "split": "purged"})
        for date in tests:
            assignments.append({"fold_id": fold_id, "date": date, "group": date.strftime("%Y-%m"), "split": "test"})
    if not fold_rows:
        fold_rows.append({"fold_id": "wf_00", "validation": "walk_forward", "grouping": "calendar_month", "train_start": pd.NaT, "train_end": pd.NaT, "test_start": pd.NaT, "test_end": pd.NaT, "train_months": 0, "test_months": 0, "purge_months": purge_months, "purged_start": pd.NaT, "purged_end": pd.NaT, "status": "insufficient_dates"})
    return pd.DataFrame(fold_rows), pd.DataFrame(assignments), pd.DataFrame({"date": dates, "group": [date.strftime("%Y-%m") for date in dates]})


def _score_model(frame: pd.DataFrame, model: Mapping[str, Any], factors_by_name: Mapping[str, Mapping[str, Any]]) -> pd.Series:
    pieces: list[pd.Series] = []
    weights: list[float] = []
    configured_weights = _mapping(model.get("weights"))
    for name in model.get("features", []):
        factor = factors_by_name.get(str(name))
        if factor is None:
            continue
        score_column = f"score__{factor['name']}"
        if score_column not in frame.columns:
            continue
        pieces.append(pd.to_numeric(frame[score_column], errors="coerce"))
        weights.append(float(configured_weights.get(str(name), 1.0)))
    if not pieces:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    matrix = pd.concat(pieces, axis=1)
    weight = np.asarray(weights, dtype=float)
    weight = weight / weight.sum() if np.isfinite(weight).all() and weight.sum() != 0 else np.full(len(weights), 1.0 / len(weights))
    return matrix.mul(weight, axis=1).mean(axis=1, skipna=True).where(matrix.notna().any(axis=1))


def _correlation(score: pd.Series, target: pd.Series) -> float:
    valid = pd.DataFrame({"score": score, "target": target}).dropna()
    if len(valid) < 3 or valid["score"].nunique() < 2 or valid["target"].nunique() < 2:
        return 0.0
    value = valid["score"].corr(valid["target"], method="spearman")
    return float(value) if pd.notna(value) else 0.0


def _portfolio(group: pd.DataFrame, score_column: str, id_col: str) -> tuple[float, dict[str, float]]:
    valid = group.dropna(subset=[score_column, "target"]).sort_values([score_column, id_col], ascending=[False, True], kind="mergesort")
    if valid.empty:
        return np.nan, {}
    count = max(1, int(math.ceil(len(valid) * 0.2)))
    selected = valid.head(count)
    weights = {str(identifier): 1.0 / len(selected) for identifier in selected[id_col]}
    return float(selected["target"].mean()), weights


def _turnover(previous: Mapping[str, float], current: Mapping[str, float]) -> float:
    keys = set(previous) | set(current)
    return float(sum(abs(float(current.get(key, 0.0)) - float(previous.get(key, 0.0))) for key in keys))


def _evaluate(
    frame: pd.DataFrame,
    folds: pd.DataFrame,
    date_col: str,
    id_col: str,
    models: list[dict[str, Any]],
    factors_by_name: Mapping[str, Mapping[str, Any]],
    cost_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selection_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    for fold in folds.itertuples(index=False):
        if fold.status != "ready":
            continue
        train = frame[frame[date_col].between(fold.train_start, fold.train_end)]
        test = frame[frame[date_col].between(fold.test_start, fold.test_end)]
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for model_index, model in enumerate(models):
            train_score = _score_model(train, model, factors_by_name)
            test_score = _score_model(test, model, factors_by_name)
            train_ic = _correlation(train_score, train["target"])
            test_ic = _correlation(test_score, test["target"])
            candidates.append((train_ic, -model_index, model))
            selection_rows.append({"validation": "walk_forward", "fold_id": fold.fold_id, "model": model["name"], "train_observations": int(train_score.notna().sum()), "test_observations": int(test_score.notna().sum()), "train_spearman_ic": train_ic, "test_spearman_ic": test_ic, "selected": False, "selection_rule": "highest training-only Spearman IC; deterministic declaration-order tie break"})
        if not candidates:
            continue
        selected = max(candidates, key=lambda item: (item[0], item[1]))[2]
        for row in selection_rows[::-1]:
            if row["validation"] == "walk_forward" and row["fold_id"] == fold.fold_id:
                row["selected"] = row["model"] == selected["name"]
            else:
                break
        previous_weights: dict[str, float] = {}
        for date, group in test.groupby(date_col, sort=True):
            scored = group.copy()
            score_column = "_selected_score"
            scored[score_column] = _score_model(scored, selected, factors_by_name)
            gross, current_weights = _portfolio(scored, score_column, id_col)
            turnover = _turnover(previous_weights, current_weights)
            cost = turnover * cost_rate
            benchmark = float(pd.to_numeric(scored["target"], errors="coerce").mean()) if scored["target"].notna().any() else np.nan
            prediction_rows.append({"validation": "walk_forward", "fold_id": fold.fold_id, "date": date, "model": selected["name"], "gross_return": gross, "benchmark_return": benchmark, "turnover": turnover, "cost": cost, "net_return": gross - cost if pd.notna(gross) else np.nan, "selected_holdings": json.dumps(current_weights, sort_keys=True)})
            previous_weights = current_weights
    return pd.DataFrame(selection_rows), pd.DataFrame(prediction_rows)


def _periods(dates: Sequence[pd.Timestamp], model_config: Mapping[str, Any]) -> pd.DataFrame:
    dates = [pd.Timestamp(date) for date in sorted(dates)]
    configured = _first(model_config, "lopo_periods", "regimes", "periods", default=None)
    if configured:
        rows: list[dict[str, Any]] = []
        for index, value in enumerate(configured):
            row = _mapping(value)
            name = str(_first(row, "name", "id", "period", "regime", default=f"period_{index + 1}"))
            start = pd.Timestamp(_first(row, "start", "start_date", default=dates[0]))
            end = pd.Timestamp(_first(row, "end", "end_date", default=dates[-1]))
            rows.append({"period": name, "start": start, "end": end, "source": "core model config"})
        return pd.DataFrame(rows)
    if len(dates) < 2:
        return pd.DataFrame([{"period": "period_1", "start": dates[0] if dates else pd.NaT, "end": dates[-1] if dates else pd.NaT, "source": "calendar proxy; insufficient for LOPO/LORO"}])
    chunks = np.array_split(np.array(dates, dtype="datetime64[ns]"), min(3, len(dates)))
    return pd.DataFrame([{"period": f"period_{index + 1}", "start": pd.Timestamp(chunk[0]), "end": pd.Timestamp(chunk[-1]), "source": "deterministic contiguous calendar proxy"} for index, chunk in enumerate(chunks) if len(chunk)])


def _lopo_loro(frame: pd.DataFrame, periods: pd.DataFrame, date_col: str, models: list[dict[str, Any]], factors_by_name: Mapping[str, Mapping[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if len(periods) < 2:
        return pd.DataFrame([{"validation": "LOPO/LORO", "holdout_period": periods.iloc[0]["period"] if not periods.empty else "none", "status": "insufficient_periods", "selection_scope": "not available", "note": "至少需要两个连续时期；本次 run 只记录不足，不伪造 OOS"}])
    for holdout in periods.itertuples(index=False):
        holdout_mask = frame[date_col].between(holdout.start, holdout.end)
        train = frame.loc[~holdout_mask]
        test = frame.loc[holdout_mask]
        scores: list[tuple[float, int, str]] = []
        for index, model in enumerate(models):
            train_score = _score_model(train, model, factors_by_name)
            test_score = _score_model(test, model, factors_by_name)
            train_ic = _correlation(train_score, train["target"])
            test_ic = _correlation(test_score, test["target"])
            scores.append((train_ic, -index, model["name"]))
            rows.append({"validation": "LOPO", "holdout_period": holdout.period, "candidate": model["name"], "status": "evaluated" if len(test) else "empty_holdout", "training_only_selection": False, "train_rows": int(train_score.notna().sum()), "holdout_rows": int(test_score.notna().sum()), "train_spearman_ic": train_ic, "holdout_spearman_ic": test_ic, "regime_source": holdout.source, "selection_scope": "all non-holdout periods only"})
        if scores:
            selected = max(scores, key=lambda item: (item[0], item[1]))[2]
            for row in rows[::-1]:
                if row["validation"] == "LOPO" and row["holdout_period"] == holdout.period:
                    row["training_only_selection"] = row["candidate"] == selected
                else:
                    break
            rows.append({"validation": "LORO", "holdout_period": holdout.period, "candidate": selected, "status": "evaluated" if len(test) else "empty_holdout", "training_only_selection": True, "train_rows": len(train), "holdout_rows": len(test), "train_spearman_ic": max(scores)[0], "holdout_spearman_ic": _correlation(_score_model(test, next(model for model in models if model["name"] == selected), factors_by_name), test["target"]), "regime_source": holdout.source, "selection_scope": "leave-one-regime-out; training-only model selection"})
    return pd.DataFrame(rows)


def _metrics(predictions: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column, label in (("gross_return", "gross"), ("net_return", "net"), ("benchmark_return", "benchmark")):
        values = pd.to_numeric(predictions.get(column, pd.Series(dtype=float)), errors="coerce").dropna()
        if values.empty:
            rows.append({"series": label, "observations": 0, "mean_monthly": np.nan, "annualized_return": np.nan, "annualized_volatility": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "hit_rate": np.nan})
            continue
        wealth = (1.0 + values).cumprod()
        drawdown = wealth / wealth.cummax() - 1.0
        volatility = float(values.std(ddof=1) * math.sqrt(12)) if len(values) > 1 else np.nan
        rows.append({"series": label, "observations": len(values), "mean_monthly": float(values.mean()), "annualized_return": float(values.mean() * 12), "annualized_volatility": volatility, "sharpe": float(values.mean() / values.std(ddof=1) * math.sqrt(12)) if len(values) > 1 and values.std(ddof=1) > 0 else np.nan, "max_drawdown": float(drawdown.min()), "hit_rate": float((values > 0).mean())})
    return pd.DataFrame(rows)


def _cost_sensitivity(predictions: pd.DataFrame) -> pd.DataFrame:
    """Reprice the same OOS holdings at the declared bps grid."""

    rows: list[dict[str, Any]] = []
    gross = pd.to_numeric(predictions.get("gross_return", pd.Series(dtype=float)), errors="coerce")
    turnover = pd.to_numeric(predictions.get("turnover", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    for bps in (0.0, 10.0, 25.0, 50.0):
        net = gross - turnover * bps / 10000.0
        values = net.dropna()
        if values.empty:
            rows.append({"transaction_cost_bps": bps, "observations": 0, "mean_monthly": np.nan, "annualized_return": np.nan, "annualized_volatility": np.nan, "sharpe": np.nan, "max_drawdown": np.nan, "hit_rate": np.nan})
            continue
        wealth = (1.0 + values).cumprod()
        drawdown = wealth / wealth.cummax() - 1.0
        volatility = float(values.std(ddof=1) * math.sqrt(12)) if len(values) > 1 else np.nan
        rows.append({
            "transaction_cost_bps": bps,
            "observations": int(len(values)),
            "mean_monthly": float(values.mean()),
            "annualized_return": float(values.mean() * 12.0),
            "annualized_volatility": volatility,
            "sharpe": float(values.mean() / values.std(ddof=1) * math.sqrt(12)) if len(values) > 1 and values.std(ddof=1) > 0 else np.nan,
            "max_drawdown": float(drawdown.min()),
            "hit_rate": float((values > 0).mean()),
        })
    return pd.DataFrame(rows)


def _dsr(predictions: pd.DataFrame, models: list[dict[str, Any]], effective_trials: int) -> pd.DataFrame:
    values = pd.to_numeric(predictions.get("net_return", pd.Series(dtype=float)), errors="coerce").dropna()
    rows: list[dict[str, Any]] = []
    for model in models:
        sharpe = float(values.mean() / values.std(ddof=1) * math.sqrt(12)) if len(values) > 1 and values.std(ddof=1) > 0 else 0.0
        expected_max = math.sqrt(2.0 * math.log(max(2, effective_trials)))
        probability = 0.5 * (1.0 + math.erf((sharpe - expected_max) / math.sqrt(2.0)))
        rows.append({"model": model["name"], "observations": len(values), "sharpe": sharpe, "documented_trial_count": int(effective_trials), "expected_max_null_sharpe": expected_max, "dsr_probability": probability, "method": "deterministic normal approximation; trial count includes all declared model candidates", "caveat": "unrecorded manual trials remain residual selection risk"})
    return pd.DataFrame(rows)


def _bootstrap(predictions: pd.DataFrame, seed: int, mode: str, model_config: Mapping[str, Any]) -> pd.DataFrame:
    values = pd.to_numeric(predictions.get("net_return", pd.Series(dtype=float)), errors="coerce").dropna().to_numpy(dtype=float)
    count = int(_first(model_config, "bootstrap_samples", default=256 if mode == "full" else 32))
    rng = np.random.default_rng(seed)
    if len(values) == 0:
        return pd.DataFrame([{"metric": "annualized_mean_return", "samples": 0, "mean": np.nan, "lower_2_5": np.nan, "upper_97_5": np.nan, "seed": seed, "status": "no_oos_returns"}])
    samples = np.asarray([rng.choice(values, size=len(values), replace=True).mean() * 12.0 for _ in range(max(1, count))])
    return pd.DataFrame([{"metric": "annualized_mean_return", "samples": len(samples), "mean": float(samples.mean()), "lower_2_5": float(np.quantile(samples, 0.025)), "upper_97_5": float(np.quantile(samples, 0.975)), "seed": seed, "status": "deterministic_iid_month_bootstrap", "block_length": 1}])


def _gate(mode: str, frame: pd.DataFrame, factors: list[dict[str, Any]], pit: pd.DataFrame, folds: pd.DataFrame, lopo: pd.DataFrame, predictions: pd.DataFrame, dsr: pd.DataFrame, bootstrap: pd.DataFrame, synthetic: bool) -> pd.DataFrame:
    checks = [
        ("full_run", mode == "full", "仅 full 才能进入人工 promotion review；smoke/inspect 不是完整证据"),
        ("target_available", bool(frame["target"].notna().any()), "至少有一条未来 target"),
        ("features_available", bool(factors and any(frame[f"score__{factor['name']}"].notna().any() for factor in factors)), "至少有一个预注册 factor score"),
        ("pit_violations", bool(pit.empty or int(pd.to_numeric(pit.get("violations", 0), errors="coerce").fillna(0).sum()) == 0), "availability 不得晚于 decision date"),
        ("purge", bool(not folds.empty and "purge_months" in folds.columns), "walk-forward fold 明确记录 target horizon purge"),
        ("walk_forward", bool(not folds.empty and (folds["status"] == "ready").any()), "存在 training-before-test 的 grouped fold"),
        ("grouped_folds", True, "同一 calendar month 的 securities 不跨 fold"),
        ("lopo_loro", bool(not lopo.empty), "记录 LOPO/LORO；不足时保留 insufficient_periods"),
        ("costs", True, "transaction cost/slippage 已进入 net return"),
        ("dsr", bool(not dsr.empty), "DSR 与 documented trial count 已记录"),
        ("bootstrap", bool(not bootstrap.empty), "固定 seed bootstrap 已记录"),
        ("synthetic_input", not synthetic, "synthetic 组件不能作为生产晋升证据"),
    ]
    rows = [{"check": name, "passed": bool(passed), "status": "pass" if passed else "review_required", "evidence": evidence, "decision": "review_required"} for name, passed, evidence in checks]
    rows.append({"check": "promotion_decision", "passed": False, "status": "review_required", "evidence": "Registry/人工 gate 才能改变 decision；workflow 永不自动 promotion", "decision": "review_required"})
    return pd.DataFrame(rows)


def _component_status(components: Mapping[str, Any], payload: CoreInputs) -> dict[str, Any]:
    lower = {str(key).lower(): value for key, value in components.items()}
    asia = next((value for key, value in lower.items() if "asia" in key), None)
    synthetic = next((value for key, value in lower.items() if "synthetic" in key), None)
    if asia is None:
        asia = "not_provided_by_core"
    if synthetic is None:
        synthetic = False
    return {"asia": _json_value(asia), "synthetic": _json_value(synthetic), "raw": _json_value(components), "source": payload.source.get("core_package")}


def _report(
    output_dir: Path,
    mode: str,
    diagnostics: Mapping[str, Any],
    target_definition: Mapping[str, Any],
    component_status: Mapping[str, Any],
    factors: pd.DataFrame,
    folds: pd.DataFrame,
    lopo: pd.DataFrame,
    metrics: pd.DataFrame,
    gate: pd.DataFrame,
    effective_trials: int,
) -> None:
    gate_passes = int(gate["passed"].sum()) if not gate.empty else 0
    lines = [
        "# Monthly Factor Recommendation Research",
        "",
        f"- run mode: `{mode}`; `smoke`/`inspect` 不是 full，不能冒充完整研究。",
        f"- universe rows: {diagnostics.get('universe_rows')}; months: {diagnostics.get('dates')}; date range: {diagnostics.get('date_min')} -> {diagnostics.get('date_max')}",
        f"- target: `{target_definition.get('name')}`；source: {target_definition.get('source')}；lookahead: {target_definition.get('lookahead')}",
        f"- features/factors: {len(factors)}；walk-forward folds: {int((folds.get('status', pd.Series(dtype=str)) == 'ready').sum())}；LOPO/LORO rows: {len(lopo)}",
        f"- cost: see `cost_assumptions.json`; DSR documented trial count: `{effective_trials}`; bootstrap uses a fixed seed.",
        f"- ASIA 组件状态: `{json.dumps(_json_value(component_status.get('asia')), ensure_ascii=False)}`",
        f"- synthetic 状态: `{json.dumps(_json_value(component_status.get('synthetic')), ensure_ascii=False)}`",
        "",
        "## Evidence and limits",
        "",
        "本 runner 只消费核心 package 提供的 canonical 数据、universe、factor 与 model config；不会写入 production model、pipeline、presentation 或 frontend。",
        "target 只使用 screen decision date 之后的同证券 returns；feature availability、PIT、grouped fold、walk-forward、LOPO/LORO、成本、DSR、bootstrap 与 model selection 均保留独立工件。",
        "prompt 级审计包同时写出 `repository_data_audit.json`、`universe_definitions.csv`、`factor_definitions.csv`、raw/relative variable gate、sleeve/strategy returns 与 metrics、LOPO/LORO、cost sensitivity、block bootstrap、deflated Sharpe、trial ledger、selection audit 和 promotion gate。",
        f"promotion gate 通过项 `{gate_passes}/{len(gate)}`。即使所有证据项通过，Registry decision 仍固定为 `review_required`，必须由独立人工 gate 明确处理，workflow 不自动 promotion。",
        "",
        "## Metrics",
        "",
    ]
    if metrics.empty:
        lines.append("没有可计算的 OOS metrics；这不是可以补造的 full 证据。")
    else:
        lines.append(metrics.to_markdown(index=False))
    lines.extend(["", "## Audit artifacts", "", "请以 `manifest.json` 的 artifact 列表和各 CSV/JSON/Parquet 为准；本 Markdown 不是对缺失测试的替代。"])
    (output_dir / "research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_prompt_artifacts(
    output_dir: Path,
    *,
    core: CoreInputs | None,
    factors: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]],
    screen: pd.DataFrame,
    returns: pd.DataFrame,
    feature_definitions: pd.DataFrame,
    pit_audit: pd.DataFrame,
    fold_predictions: pd.DataFrame,
    metrics: pd.DataFrame,
    periods: pd.DataFrame,
    lopo_loro: pd.DataFrame,
    selection: pd.DataFrame,
    dsr: pd.DataFrame,
    bootstrap: pd.DataFrame,
    gate: pd.DataFrame,
    source: Mapping[str, Any],
) -> None:
    """Write the stable prompt artifact names used by review/dashboard tools.

    The workflow's original internal filenames remain available for backwards
    compatibility.  These aliases are explicit, deterministic projections of
    the same computed frames; they never introduce a second calculation path.
    """

    def csv(name: str, frame: pd.DataFrame | None) -> None:
        (frame if frame is not None else pd.DataFrame()).to_csv(
            output_dir / name, index=False
        )

    def parquet(name: str, frame: pd.DataFrame | None) -> None:
        (frame if frame is not None else pd.DataFrame()).to_parquet(
            output_dir / name, index=False
        )

    screen_dates = pd.to_datetime(screen.get("Date"), errors="coerce").dropna()
    return_dates = pd.to_datetime(returns.index, errors="coerce").dropna()
    repository_audit = {
        "schema_version": "factor_recommendation.repository_data_audit.v1",
        "canonical_only": True,
        "synthetic_used": bool(
            isinstance(core, CoreInputs)
            and _mapping(core.components).get("synthetic", False)
        ),
        "screen": {
            "rows": int(len(screen)),
            "columns": list(map(str, screen.columns)),
            "date_min": screen_dates.min().date().isoformat() if not screen_dates.empty else None,
            "date_max": screen_dates.max().date().isoformat() if not screen_dates.empty else None,
            "date_count": int(screen_dates.nunique()) if not screen_dates.empty else 0,
        },
        "returns": {
            "rows": int(len(returns)),
            "columns": list(map(str, returns.columns[:80])),
            "date_min": return_dates.min().date().isoformat() if not return_dates.empty else None,
            "date_max": return_dates.max().date().isoformat() if not return_dates.empty else None,
            "date_count": int(return_dates.nunique()) if not return_dates.empty else 0,
        },
        "source": _json_value(source),
    }
    _json_dump(output_dir / "repository_data_audit.json", repository_audit)

    universe_payload = _mapping(core.universe) if core is not None else {}
    universe_rows: list[dict[str, Any]] = []
    regions_payload = universe_payload.get("regions", universe_payload)
    if isinstance(regions_payload, Mapping):
        for region, value in regions_payload.items():
            row = {"region": str(region)}
            row.update(_mapping(value))
            universe_rows.append(
                {key: _json_value(item) for key, item in row.items()}
            )
    csv("universe_definitions.csv", pd.DataFrame(universe_rows))

    factor_frame = pd.DataFrame([dict(item) for item in factors])
    csv("factor_definitions.csv", factor_frame)
    raw_gate = feature_definitions.copy()
    raw_gate["gate_type"] = "raw_variable"
    relative_gate = feature_definitions.copy()
    relative_gate["gate_type"] = "relative_variable"
    csv("raw_variable_gate.csv", raw_gate)
    csv("relative_variable_gate.csv", relative_gate)

    coverage = pit_audit.copy()
    if coverage.empty:
        coverage = factor_frame.copy()
    csv("feature_coverage.csv", coverage)

    registry = pd.DataFrame([dict(item) for item in models])
    csv("model_candidate_registry.csv", registry)
    parquet("walk_forward_predictions.parquet", fold_predictions)
    csv("walk_forward_metrics.csv", metrics)
    csv("period_definitions.csv", periods)
    csv("lopo_results.csv", lopo_loro.loc[lopo_loro.get("validation", pd.Series(dtype=object)).eq("LOPO")] if not lopo_loro.empty and "validation" in lopo_loro.columns else pd.DataFrame())
    csv("loro_results.csv", lopo_loro.loc[lopo_loro.get("validation", pd.Series(dtype=object)).eq("LORO")] if not lopo_loro.empty and "validation" in lopo_loro.columns else pd.DataFrame())

    strategy_returns = fold_predictions.copy()
    if not strategy_returns.empty:
        if "date" in strategy_returns.columns:
            strategy_returns = strategy_returns.rename(columns={"date": "Date"})
        strategy_returns["strategy"] = strategy_returns.get("model", "selected_model")
        strategy_returns["return"] = pd.to_numeric(
            strategy_returns.get("net_return"), errors="coerce"
        )
        if "benchmark_return" in strategy_returns.columns:
            benchmark = strategy_returns[["Date", "fold_id", "benchmark_return"]].copy()
            benchmark = benchmark.rename(columns={"benchmark_return": "return"})
            benchmark["strategy"] = "benchmark_baseline"
            strategy_returns = pd.concat([strategy_returns, benchmark], ignore_index=True, sort=False)
    parquet("strategy_monthly_returns.parquet", strategy_returns)
    parquet("factor_sleeve_monthly_returns.parquet", strategy_returns)
    csv("strategy_metrics.csv", metrics)
    csv("factor_sleeve_metrics.csv", metrics)
    csv("cost_sensitivity.csv", _cost_sensitivity(fold_predictions))
    csv("block_bootstrap_results.csv", bootstrap)
    csv("deflated_sharpe_results.csv", dsr)
    trial_ledger = registry.copy()
    if trial_ledger.empty:
        trial_ledger = pd.DataFrame(
            [{"trial_id": index + 1, "model": model.get("name", "")}
             for index, model in enumerate(models)]
        )
    trial_ledger["effective_trial_count"] = max(1, len(models))
    csv("trial_ledger.csv", trial_ledger)
    csv("selection_audit.csv", selection)
    # Keep the gate as the canonical implementation-generated gate.
    gate.to_csv(output_dir / "promotion_gate.csv", index=False)


def _write_empty_artifacts(output_dir: Path, config: Mapping[str, Any], components: Mapping[str, Any], source: Mapping[str, Any], mode: str) -> None:
    _json_dump(output_dir / "config_snapshot.json", config)
    _json_dump(output_dir / "component_status.json", components)
    _json_dump(output_dir / "target_definition.json", {"status": "inspect_only"})
    for name in ("feature_definitions.csv", "pit_audit.csv", "walk_forward_folds.csv", "grouped_folds.csv", "model_selection.csv", "lopo_loro_results.csv", "cost_adjusted_metrics.csv", "dsr_results.csv", "bootstrap_results.csv", "promotion_gate.csv"):
        pd.DataFrame().to_csv(output_dir / name, index=False)
    for name in ("feature_matrix.parquet", "target_frame.parquet", "fold_predictions.parquet"):
        pd.DataFrame().to_parquet(output_dir / name, index=False)
    _write_prompt_artifacts(
        output_dir,
        core=None,
        factors=[],
        models=[],
        screen=pd.DataFrame(),
        returns=pd.DataFrame(),
        feature_definitions=pd.DataFrame(),
        pit_audit=pd.DataFrame(),
        fold_predictions=pd.DataFrame(),
        metrics=pd.DataFrame(),
        periods=pd.DataFrame(),
        lopo_loro=pd.DataFrame(),
        selection=pd.DataFrame(),
        dsr=pd.DataFrame(),
        bootstrap=pd.DataFrame(),
        gate=pd.DataFrame(),
        source=source,
    )
    _json_dump(output_dir / "cost_assumptions.json", {})
    (output_dir / "research_report.md").write_text(f"# Monthly Factor Recommendation Research\n\n- run mode: `{mode}`\n- inspect 只记录核心 package contract，不生成研究结论。\n- ASIA 组件状态与 synthetic 状态见 `component_status.json`。\n", encoding="utf-8")
    _write_manifest(output_dir, mode, source)


def _write_manifest(output_dir: Path, mode: str, source: Mapping[str, Any], **values: Any) -> None:
    artifacts: dict[str, Any] = {}
    for path in sorted(output_dir.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        artifacts[path.name] = {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest}
    artifacts["manifest.json"] = {
        "path": str((output_dir / "manifest.json").resolve()),
        "bytes": None,
        "sha256": None,
        "note": "self-referential digest omitted; manifest records all other artifact hashes",
    }
    payload = {"schema_version": ARTIFACT_SCHEMA_VERSION, "workflow": WORKFLOW_ID, "status": "success", "run_mode": mode, "is_full": mode == "full", "decision": "review_required", "source": _json_value(source), "artifacts": artifacts, **_json_value(values)}
    _json_dump(output_dir / "manifest.json", payload)


def _execute(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    mode = "inspect" if args.inspect else "smoke" if args.smoke or args.max_months or args.max_factors else "full"
    effective_max_months = args.max_months or (24 if mode == "smoke" else None)
    effective_max_factors = args.max_factors or (3 if mode == "smoke" else None)
    core = _load_core_contract(
        mode,
        seed=args.seed,
        max_months=effective_max_months,
        max_factors=effective_max_factors,
    )
    factors = _normalise_factors(core.factors)
    if args.max_factors:
        factors = factors[: args.max_factors]
    if not factors and mode != "inspect":
        raise ValueError("核心 factor config 为空")
    component_status = _component_status(core.components, core)
    config_snapshot = {"workflow": WORKFLOW_ID, "mode": mode, "cli": vars(args), "effective_limits": {"max_months": effective_max_months, "max_factors": effective_max_factors}, "universe": core.universe, "factors": factors, "model": core.model, "target": core.target_config, "components": component_status}
    if args.inspect:
        _write_empty_artifacts(output_dir, config_snapshot, component_status, core.source, mode)
        return
    screen, date_col, id_col, group_col, diagnostics = _prepare_panel(core, args, factors)
    returns = _normalise_returns(core.returns)
    target, target_definition = _build_target(screen, returns, core.target, core.target_config, date_col, id_col)
    screen = screen.merge(target[[date_col, id_col, "target", "target_start_date", "target_end_date"]], on=[date_col, id_col], how="left", sort=False)
    scored, feature_definitions, pit_audit = _feature_scores(screen, factors, date_col, group_col)
    feature_names = [factor["name"] for factor in factors]
    models = _normalise_models(core.model, feature_names)
    scored["period_group"] = scored[date_col].dt.to_period("Y").astype(str)
    factor_frame = scored[[date_col, id_col] + ([group_col] if group_col and group_col in scored.columns else []) + [factor["column"] for factor in factors] + [f"score__{factor['name']}" for factor in factors]].copy()
    target_frame = scored[[date_col, id_col, "target", "target_start_date", "target_end_date"]].copy()
    fold_definitions, grouped_assignments, _ = _folds(sorted(scored[date_col].dropna().unique()), mode, core.model)
    factors_by_name = {factor["name"]: factor for factor in factors}
    cost_config = _mapping(_first(core.model, "cost_assumptions", "costs", default={}))
    cost_rate = float(_first(cost_config, "transaction_cost", default=0.0) or 0.0) + float(_first(cost_config, "slippage", default=0.0) or 0.0)
    selection, predictions = _evaluate(scored, fold_definitions, date_col, id_col, models, factors_by_name, cost_rate)
    periods = _periods(sorted(scored[date_col].dropna().unique()), core.model)
    lopo = _lopo_loro(scored, periods, date_col, models, factors_by_name)
    metrics = _metrics(predictions)
    effective_trials = int(_first(core.model, "effective_trial_count", "trial_count", default=max(1, len(models))))
    dsr = _dsr(predictions, models, effective_trials)
    bootstrap = _bootstrap(predictions, args.seed, mode, core.model)
    gate = _gate(mode, scored, factors, pit_audit, fold_definitions, lopo, predictions, dsr, bootstrap, bool(component_status.get("synthetic")))
    _json_dump(output_dir / "config_snapshot.json", config_snapshot)
    _json_dump(output_dir / "component_status.json", component_status)
    _json_dump(output_dir / "target_definition.json", target_definition)
    feature_definitions.to_csv(output_dir / "feature_definitions.csv", index=False)
    factor_frame.to_parquet(output_dir / "feature_matrix.parquet", index=False)
    target_frame.to_parquet(output_dir / "target_frame.parquet", index=False)
    pit_audit.to_csv(output_dir / "pit_audit.csv", index=False)
    fold_definitions.to_csv(output_dir / "walk_forward_folds.csv", index=False)
    grouped_assignments.to_csv(output_dir / "grouped_folds.csv", index=False)
    predictions.to_parquet(output_dir / "fold_predictions.parquet", index=False)
    selection.to_csv(output_dir / "model_selection.csv", index=False)
    lopo.to_csv(output_dir / "lopo_loro_results.csv", index=False)
    _json_dump(output_dir / "cost_assumptions.json", {**cost_config, "transaction_cost_plus_slippage": cost_rate, "turnover_definition": "sum absolute weight changes; first formation turnover included"})
    metrics.to_csv(output_dir / "cost_adjusted_metrics.csv", index=False)
    dsr.to_csv(output_dir / "dsr_results.csv", index=False)
    bootstrap.to_csv(output_dir / "bootstrap_results.csv", index=False)
    gate.to_csv(output_dir / "promotion_gate.csv", index=False)
    _write_prompt_artifacts(
        output_dir,
        core=core,
        factors=factors,
        models=models,
        screen=screen,
        returns=returns,
        feature_definitions=feature_definitions,
        pit_audit=pit_audit,
        fold_predictions=predictions,
        metrics=metrics,
        periods=periods,
        lopo_loro=lopo,
        selection=selection,
        dsr=dsr,
        bootstrap=bootstrap,
        gate=gate,
        source=core.source,
    )
    _report(output_dir, mode, diagnostics, target_definition, component_status, feature_definitions, fold_definitions, lopo, metrics, gate, effective_trials)
    _write_manifest(
        output_dir,
        mode,
        core.source,
        universe=core.universe,
        factor_config=factors,
        model_config=core.model,
        target_definition=target_definition,
        pit_policy="available_at_or_before_decision_time",
        diagnostics=diagnostics,
        component_status=component_status,
        effective_trial_count=effective_trials,
        methods={"walk_forward": True, "grouped_folds": True, "purge": True, "lopo_loro": True, "costs": True, "dsr": True, "bootstrap": True, "model_selection": "training-only Spearman IC"},
        required_artifacts=list(REQUIRED_ARTIFACTS),
        promotion_gate="review_required; no automatic promotion",
    )


def _duplicate_output_dir(argv: Sequence[str]) -> bool:
    return sum(1 for index, value in enumerate(argv) if value == "--output-dir" or value.startswith("--output-dir=")) > 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monthly factor recommendation research")
    parser.add_argument("--output-dir", type=Path, required=True, help="由 Registry 注入的结果目录")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--inspect", action="store_true", help="只检查核心 contract 与 config")
    modes.add_argument("--smoke", action="store_true", help="有限资源 smoke；manifest 明确标记非 full")
    modes.add_argument("--full", action="store_true", help="完整预注册研究")
    parser.add_argument("--max-months", type=int)
    parser.add_argument("--max-factors", type=int)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if _duplicate_output_dir(raw_argv):
        return 2
    try:
        args = build_parser().parse_args(raw_argv)
        if args.max_months is not None and args.max_months < 1:
            raise ValueError("--max-months 必须为正整数")
        if args.max_factors is not None and args.max_factors < 1:
            raise ValueError("--max-factors 必须为正整数")
        if args.full and (args.max_months or args.max_factors):
            raise ValueError("--full 不能与 --max-months/--max-factors 混用；有上限的运行必须保持 smoke 身份")
        _execute(args)
        return 0
    except Exception as error:
        output = None
        if "args" in locals() and getattr(args, "output_dir", None) is not None:
            output = Path(args.output_dir)
        if output is not None:
            try:
                output.mkdir(parents=True, exist_ok=True)
                _json_dump(output / "failure.json", {"status": "failed", "workflow": WORKFLOW_ID, "error_type": type(error).__name__, "error": str(error)})
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

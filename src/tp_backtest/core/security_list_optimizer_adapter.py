from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Optional

import numpy as np
import pandas as pd

from tp_backtest.utils.constants import (
    COL_DATE,
    COL_ESG_SCORE,
    COL_ISIN,
    COL_SECTOR_ICB19,
    COL_SEDOL,
)
from tp_backtest.utils.data_utils import read_liste_noire

logger = logging.getLogger(__name__)

from tp_core.portfolio_weights import normalize_long_only_weights
from tp_portfolio import (
    GroupConstraint,
    LinearConstraint,
    OptimizerConfig,
    OptimizerObjective,
    optimize_portfolio,
)


class SecurityOptimizerAdapterMixin:
    def _prepare_screen_for_optimizer(self, screen: pd.DataFrame) -> pd.DataFrame:
        """Prepare explicit identifiers, benchmark weights and scores."""

        out = screen.copy()
        if COL_ISIN not in out.columns:
            out[COL_ISIN] = out.index.astype(str)
        if COL_SEDOL not in out.columns:
            raise KeyError(f"optimizer candidates require {COL_SEDOL}")
        bench_col = f"Weight in {self.bench}"
        if bench_col not in out.columns:
            raise KeyError(f"optimizer candidates require {bench_col}")
        if "Score ML" not in out.columns:
            metric = self.metrics[0] if isinstance(self.metrics, list) else self.metrics
            if metric in out.columns:
                out["Score ML"] = pd.to_numeric(out[metric], errors="coerce").rank(pct=True) * 10.0
            else:
                out["Score ML"] = 0.0
        if "Name" not in out.columns:
            out["Name"] = out.index.astype(str)
        if "Exchange Country Region" not in out.columns:
            out["Exchange Country Region"] = "Others"
        if "Secto" not in out.columns:
            out["Secto"] = out[COL_SECTOR_ICB19]
        out["Key_Secto_Geo"] = (
            out["Secto"].astype("string")
            + "_"
            + out["Exchange Country Region"].astype("string")
        )
        if COL_ESG_SCORE not in out.columns:
            out[COL_ESG_SCORE] = 100.0
        out[bench_col] = pd.to_numeric(out[bench_col], errors="coerce").fillna(0.0)
        out["Score ML"] = pd.to_numeric(out["Score ML"], errors="coerce").fillna(0.0)
        return out.reset_index(drop=True)

    @staticmethod
    def _optimizer_group_targets(
        candidates: pd.DataFrame,
        group_col: str,
        benchmark_col: str,
        overrides: Mapping[object, float] | None,
    ) -> dict[object, float]:
        if overrides is not None:
            targets = normalize_long_only_weights(pd.Series(overrides, dtype=float))
            return targets.to_dict()
        return (
            candidates.groupby(group_col, dropna=False)[benchmark_col]
            .sum()
            .to_dict()
        )

    def _optimizer_current_weights(
        self,
        candidates: pd.DataFrame,
        previous_portfolio: pd.DataFrame | None,
        *,
        drift: bool,
    ) -> tuple[pd.Series | None, float]:
        if previous_portfolio is None or previous_portfolio.empty:
            return None, 0.0
        previous = previous_portfolio.copy()
        id_col = COL_SEDOL if COL_SEDOL in previous.columns else COL_ISIN
        if id_col not in previous.columns or "Weight" not in previous.columns:
            raise KeyError(
                f"previous_portfolio requires Weight and {COL_SEDOL} or {COL_ISIN}"
            )
        previous["Weight"] = pd.to_numeric(previous["Weight"], errors="coerce").fillna(0.0)
        if drift and COL_DATE in previous.columns:
            previous_date = pd.to_datetime(previous[COL_DATE], errors="coerce").max()
            target_date = pd.to_datetime(candidates[COL_DATE], errors="coerce").max()
            returns = self._get_returns_for_drift()
            if id_col == COL_ISIN:
                id_map = candidates.set_index(COL_ISIN)[COL_SEDOL]
                previous["__returns_id"] = previous[COL_ISIN].map(id_map)
            else:
                previous["__returns_id"] = previous[COL_SEDOL]
            period = returns.loc[
                (returns.index > previous_date) & (returns.index <= target_date)
            ]
            growth = (1.0 + period).prod() if not period.empty else pd.Series(dtype=float)
            previous["Weight"] *= previous["__returns_id"].map(growth).fillna(1.0)

        if float(previous["Weight"].sum()) <= 0:
            return None, 0.0
        previous["Weight"] = normalize_long_only_weights(previous["Weight"])
        current = candidates[[id_col]].merge(
            previous[[id_col, "Weight"]].groupby(id_col, as_index=False).sum(),
            on=id_col,
            how="left",
        )["Weight"].fillna(0.0)
        if float(current.sum()) <= 0:
            return None, 0.0
        external_weight = max(0.0, 1.0 - float(current.sum()))
        return current, external_weight

    def _optimizer_covariance(
        self,
        candidates: pd.DataFrame,
        model: str,
    ) -> np.ndarray:
        count = len(candidates)
        if model == "identity":
            return np.eye(count) * 0.04**2
        returns = self._get_returns_for_drift().reindex(
            columns=candidates[COL_SEDOL].astype(str)
        )
        usable = returns.tail(756).fillna(0.0)
        if len(usable) < 2:
            return np.eye(count) * 0.04**2
        covariance = usable.cov().to_numpy(dtype=float) * 252.0
        if not np.isfinite(covariance).all() or float(np.trace(covariance)) <= 0:
            return np.eye(count) * 0.04**2
        return covariance

    def build_optimized_monthly_security_list(
        self,
        screen_agg_monthly: Optional[pd.DataFrame] = None,
        previous_portfolio: Optional[pd.DataFrame] = None,
        drift: bool = True,
        objective: OptimizerObjective | str = OptimizerObjective.MIN_TRACKING_ERROR,
        score_col: str = "Score ML",
        model_covariance: str = "sample",
        min_weight: float = 0.0,
        max_weight: float = 1.0,
        max_active_weight: float | None = None,
        max_tracking_error: float | None = None,
        max_turnover: float | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        min_holdings: int | None = None,
        max_holdings: int | None = None,
        min_weight_if_selected: float = 0.0,
        sector_margin: float | None = 0.02,
        country_margin: float | None = 0.03,
        sector_targets: Mapping[object, float] | None = None,
        country_targets: Mapping[object, float] | None = None,
        linear_constraints: Sequence[LinearConstraint] = (),
        forced_ids: Sequence[object] = (),
        forbidden_ids: Sequence[object] = (),
        score_weight: float = 1.0,
        tracking_error_weight: float = 1.0,
        turnover_weight: float = 0.0,
        active_weight_penalty: float = 0.0,
        solver_order: Sequence[str] = (),
    ) -> pd.DataFrame:
        """Build one optimized security list through the sole optimizer API."""

        screen = (
            self.screen[self.screen[COL_DATE] == self.screen[COL_DATE].max()]
            if screen_agg_monthly is None
            else screen_agg_monthly
        )
        candidates = self._prepare_screen_for_optimizer(screen)
        bench_col = f"Weight in {self.bench}"
        candidates[bench_col] = normalize_long_only_weights(
            candidates[bench_col],
            allow_equal_fallback=True,
        )
        if score_col not in candidates.columns:
            raise KeyError(f"optimizer candidates require score column {score_col}")
        current, external_current_weight = self._optimizer_current_weights(
            candidates,
            previous_portfolio,
            drift=drift,
        )
        blocked = set(str(value) for value in forbidden_ids)
        if self._liste_noire is not None:
            blacklist = (
                read_liste_noire(self._liste_noire, [], [])
                if isinstance(self._liste_noire, str)
                else list(self._liste_noire)
            )
            blacklist_values = {str(value) for value in blacklist}
            blocked.update(blacklist_values)
            blocked.update(
                candidates.loc[
                    candidates[COL_ISIN].astype(str).isin(blacklist_values),
                    COL_SEDOL,
                ]
                .astype(str)
                .tolist()
            )
        forced = set(str(value) for value in forced_ids)
        if self.top_mandatory:
            forced.update(
                candidates.nlargest(int(self.top_mandatory), bench_col)[COL_SEDOL]
                .astype(str)
                .tolist()
            )

        group_constraints: list[GroupConstraint] = []
        if sector_margin is not None:
            targets = self._optimizer_group_targets(
                candidates,
                "Key_Secto_Geo",
                bench_col,
                sector_targets,
            )
            group_constraints.append(
                GroupConstraint.around_targets(
                    name="sector_region",
                    group_col="Key_Secto_Geo",
                    targets=targets,
                    margin=float(sector_margin),
                )
            )
        if country_margin is not None:
            targets = self._optimizer_group_targets(
                candidates,
                "Exchange Country Region",
                bench_col,
                country_targets,
            )
            group_constraints.append(
                GroupConstraint.around_targets(
                    name="country_region",
                    group_col="Exchange Country Region",
                    targets=targets,
                    margin=float(country_margin),
                )
            )

        result = optimize_portfolio(
            candidates,
            id_col=COL_SEDOL,
            benchmark_weights=bench_col,
            scores=score_col,
            covariance=self._optimizer_covariance(candidates, model_covariance),
            current_weights=current,
            external_current_weight=external_current_weight,
            lower_bounds=np.full(len(candidates), float(min_weight)),
            upper_bounds=np.full(len(candidates), float(max_weight)),
            group_constraints=group_constraints,
            linear_constraints=linear_constraints,
            config=OptimizerConfig(
                objective=OptimizerObjective(objective),
                score_weight=float(score_weight),
                tracking_error_weight=float(tracking_error_weight),
                turnover_weight=float(turnover_weight),
                active_weight_penalty=float(active_weight_penalty),
                min_score=min_score,
                max_score=max_score,
                max_tracking_error=max_tracking_error,
                max_turnover=max_turnover,
                max_active_weight=max_active_weight,
                min_holdings=min_holdings,
                max_holdings=max_holdings,
                min_weight_if_selected=min_weight_if_selected,
                forced_ids=tuple(forced),
                forbidden_ids=tuple(blocked),
                solver_order=tuple(solver_order),
            ),
        )
        optimized_full = result.to_frame(candidates)
        optimized = optimized_full.rename(columns={"target_weight": "Weight"})
        if abs(float(optimized["Weight"].sum()) - 1.0) > 1e-8:
            raise RuntimeError(
                "optimizer output weights do not sum to one"
            )
        optimized["PTF"] = f"{self.ptf_name} OPTIM"
        columns = [
            "PTF", "Name", COL_ISIN, COL_SEDOL, "Weight", "Exchange Country Region",
            "Key_Secto_Geo", COL_DATE, "Secto", "Score ML", "Raison Exclusion",
            "optimizer_id", "optimizer_version", "optimizer_objective",
            "optimizer_solver", "optimizer_status",
        ]
        columns = [column for column in columns if column in optimized.columns]
        result_sec_list = optimized[columns].copy()
        self.optimizer_result_monthly = optimized_full.copy()
        audit_row = {
            COL_DATE: pd.to_datetime(candidates[COL_DATE]).max(),
            **result.metadata,
            **{
                key: value
                for key, value in result.audit.items()
                if not isinstance(value, (list, dict))
            },
        }
        self.optimizer_constraint_log = pd.concat(
            [self.optimizer_constraint_log, pd.DataFrame([audit_row])],
            ignore_index=True,
        )
        self.sec_list_optimized_monthly = result_sec_list.copy(deep=True)
        return result_sec_list

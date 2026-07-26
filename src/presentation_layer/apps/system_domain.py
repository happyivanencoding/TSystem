"""Domain service for dashboard reads and controlled job submissions."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DashboardDomainService:
    """Application boundary used by HTTP routers and presentation callbacks."""

    defaults: Mapping[str, Any]
    state_provider: Callable[..., dict[str, Any]]
    backtest_provider: Callable[[], list[dict[str, Any]]]
    latest_job_provider: Callable[[], dict[str, Any]]
    queue_provider: Callable[[], dict[str, Any]]
    regime_provider: Callable[[], dict[str, Any]]
    country_provider: Callable[[], dict[str, Any]]
    small_cap_provider: Callable[[], dict[str, Any]]
    sector_provider: Callable[[], dict[str, Any]]
    technical_provider: Callable[[], dict[str, Any]]
    score_ml_provider: Callable[..., dict[str, Any]]
    company_provider: Callable[[str], dict[str, Any]]
    job_provider: Callable[[str | None], dict[str, str] | None]
    queue_event_provider: Callable[..., Iterable[str]]
    job_event_provider: Callable[..., Iterable[str]]
    submit_job: Callable[[list[str], str], dict[str, Any]]
    job_view_model: Callable[[dict[str, Any] | None], dict[str, str]]
    system_checks_command: Callable[[], list[str]]
    regime_command: Callable[[], list[str]]
    country_command: Callable[[], list[str]]
    small_cap_command: Callable[[], list[str]]
    project_command: Callable[[str, str], list[str]]
    pipeline_command: Callable[..., list[str]]

    def state(
        self,
        *,
        include_signals: bool = False,
        include_backtest: bool = False,
    ) -> dict[str, Any]:
        return self.state_provider(
            include_signals=include_signals,
            include_backtest=include_backtest,
        )

    def launch(self, command: list[str], step: str) -> dict[str, Any]:
        record = self.submit_job(command, step)
        return {"job": self.job_view_model(record), "record": record}

    def launch_system_checks(self) -> dict[str, Any]:
        return self.launch(self.system_checks_command(), "system_checks")

    def launch_regime(self) -> dict[str, Any]:
        return self.launch(
            self.regime_command(),
            "signal:regime_risk_budget",
        )

    def launch_country(self) -> dict[str, Any]:
        return self.launch(self.country_command(), "signal:country_model")

    def launch_small_cap(self) -> dict[str, Any]:
        return self.launch(self.small_cap_command(), "signal:small_cap_model")

    def launch_project(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        project_id = str(
            payload.get("project_id") or self.defaults["project_id"]
        )
        mode = str(
            payload.get("mode")
            or payload.get("project_mode")
            or self.defaults["project_mode"]
        )
        return self.launch(
            self.project_command(project_id, mode),
            f"project:{project_id}:{mode}",
        )

    def launch_pipeline(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        flags = payload.get("flags")
        if not isinstance(flags, list):
            flags = self.defaults["flags"]
        step = str(payload.get("step") or self.defaults["step"])
        command = self.pipeline_command(
            step,
            payload.get("input_month") or "",
            payload.get("as_of") or "",
            str(payload.get("update_mode") or self.defaults["update_mode"]),
            payload.get("top_pct", self.defaults["top_pct"]),
            payload.get("ml_weight", self.defaults["ml_weight"]),
            payload.get("technical_weight", self.defaults["technical_weight"]),
            payload.get("max_weight", self.defaults["max_weight"]),
            str(
                payload.get("optimizer_method")
                or self.defaults["optimizer_method"]
            ),
            payload.get("portfolio_region") or "",
            payload.get("backtest_profile") or "",
            payload.get("bench") or "",
            payload.get("start_date") or "",
            payload.get("percentile"),
            flags,
        )
        return self.launch(command, step)

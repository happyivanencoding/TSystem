"""HTTP API router for the TP system dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from flask import Response, jsonify, request, send_from_directory, stream_with_context


class DashboardDomain(Protocol):
    def state(
        self,
        *,
        include_signals: bool = False,
        include_backtest: bool = False,
    ) -> dict[str, Any]: ...

    def job_provider(self, job_id: str | None) -> dict[str, str] | None: ...

    def queue_event_provider(self, **kwargs: Any): ...

    def job_event_provider(self, job_id: str, **kwargs: Any): ...

    def launch_system_checks(self) -> dict[str, Any]: ...

    def launch_regime(self) -> dict[str, Any]: ...

    def launch_country(self) -> dict[str, Any]: ...

    def launch_small_cap(self) -> dict[str, Any]: ...

    def launch_project(self, payload: dict[str, Any]) -> dict[str, Any]: ...

    def launch_pipeline(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class DashboardStaticAssets:
    client_dist_dir: Path
    client_assets_dir: Path
    factor_explorer_path: Path
    factor_research_app_path: Path


def register_dashboard_routes(
    server: Any,
    *,
    domain: DashboardDomain,
    assets: DashboardStaticAssets,
) -> None:
    """Register static and JSON/SSE routes against a Flask-compatible server."""

    @server.after_request
    def preserve_dash_json_unicode(response: Response):
        if request.path.startswith("/dash/_dash-") and response.mimetype == "application/json":
            try:
                payload = json.loads(response.get_data(as_text=True))
            except Exception:
                return response
            response.set_data(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            )
        return response

    @server.route("/", methods=["GET"])
    @server.route("/index.html", methods=["GET"])
    @server.route("/client/", methods=["GET"])
    @server.route("/client/index.html", methods=["GET"])
    def api_dashboard_client_index():
        return send_from_directory(assets.client_dist_dir, "index.html")

    @server.route("/client/assets/<path:filename>", methods=["GET"])
    def api_dashboard_client_assets(filename: str):
        return send_from_directory(assets.client_assets_dir, filename)

    @server.route("/reports/factor-explorer.html", methods=["GET"])
    def factor_explorer_report():
        path = assets.factor_explorer_path
        return send_from_directory(path.parent, path.name)

    @server.route("/reports/factor-research-app.html", methods=["GET"])
    def factor_research_app_report():
        path = assets.factor_research_app_path
        return send_from_directory(path.parent, path.name)

    @server.route("/api/dashboard/state", methods=["GET"])
    def api_dashboard_state():
        truthy = {"1", "true", "yes"}
        include_details = request.args.get("include_details", "").lower() in truthy
        include_signals = (
            include_details
            or request.args.get("include_signals", "").lower() in truthy
        )
        include_backtest = (
            include_details
            or request.args.get("include_backtest", "").lower() in truthy
        )
        return jsonify(
            domain.state(
                include_signals=include_signals,
                include_backtest=include_backtest,
            )
        )

    @server.route("/api/dashboard/backtest", methods=["GET"])
    def api_dashboard_backtest():
        return jsonify(domain.backtest_provider())

    @server.route("/api/dashboard/jobs/latest", methods=["GET"])
    def api_dashboard_latest_job():
        return jsonify(domain.latest_job_provider())

    @server.route("/api/dashboard/jobs/queue", methods=["GET"])
    def api_dashboard_job_queue():
        return jsonify(domain.queue_provider())

    @server.route("/api/dashboard/signals/regime", methods=["GET"])
    def api_dashboard_regime_signal():
        return jsonify(domain.regime_provider())

    @server.route("/api/dashboard/signals/country", methods=["GET"])
    def api_dashboard_country_signal():
        return jsonify(domain.country_provider())

    @server.route("/api/dashboard/signals/small-cap", methods=["GET"])
    def api_dashboard_small_cap_signal():
        return jsonify(domain.small_cap_provider())

    @server.route("/api/dashboard/signals/sector", methods=["GET"])
    def api_dashboard_sector_signal():
        return jsonify(domain.sector_provider())

    @server.route("/api/dashboard/signals/technical", methods=["GET"])
    def api_dashboard_technical_signal():
        return jsonify(domain.technical_provider())

    @server.route("/api/dashboard/score-ml-components", methods=["GET"])
    def api_dashboard_score_ml_components():
        return jsonify(
            domain.score_ml_provider(
                date=request.args.get("date"),
                side=request.args.get("side", "top"),
            )
        )

    @server.route("/api/dashboard/company-detail/<isin>", methods=["GET"])
    def api_dashboard_company_detail(isin: str):
        return jsonify(domain.company_provider(isin))

    @server.route("/api/dashboard/jobs/queue/events", methods=["GET"])
    def api_dashboard_job_queue_events():
        try:
            limit_arg = request.args.get("limit")
            limit = int(limit_arg) if limit_arg else None
            interval = max(float(request.args.get("interval", "3")), 0.5)
        except ValueError:
            return jsonify({"error": "invalid queue events query parameters"}), 400
        return Response(
            stream_with_context(
                domain.queue_event_provider(
                    interval_seconds=interval,
                    limit=limit,
                )
            ),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @server.route("/api/dashboard/jobs/<job_id>", methods=["GET"])
    def api_dashboard_job(job_id: str):
        payload = domain.job_provider(job_id)
        if payload is None:
            return jsonify({"error": "job not found", "job_id": job_id}), 404
        return jsonify(payload)

    @server.route("/api/dashboard/jobs/<job_id>/events", methods=["GET"])
    def api_dashboard_job_events(job_id: str):
        if domain.job_provider(job_id) is None:
            return jsonify({"error": "job not found", "job_id": job_id}), 404
        try:
            limit_arg = request.args.get("limit")
            limit = int(limit_arg) if limit_arg else None
            interval = max(float(request.args.get("interval", "2")), 0.2)
        except ValueError:
            return jsonify({"error": "invalid events query parameters"}), 400
        return Response(
            stream_with_context(
                domain.job_event_provider(
                    job_id,
                    interval_seconds=interval,
                    limit=limit,
                )
            ),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @server.route("/api/dashboard/jobs/system-checks", methods=["POST"])
    def api_dashboard_launch_system_checks():
        return jsonify(domain.launch_system_checks()), 202

    @server.route("/api/dashboard/jobs/signals/regime", methods=["POST"])
    def api_dashboard_refresh_regime_signal():
        return jsonify(domain.launch_regime()), 202

    @server.route("/api/dashboard/jobs/signals/country", methods=["POST"])
    def api_dashboard_refresh_country_signal():
        return jsonify(domain.launch_country()), 202

    @server.route("/api/dashboard/jobs/signals/small-cap", methods=["POST"])
    def api_dashboard_refresh_small_cap_signal():
        return jsonify(domain.launch_small_cap()), 202

    @server.route("/api/dashboard/jobs/project", methods=["POST"])
    def api_dashboard_launch_project():
        payload = request.get_json(silent=True) or {}
        try:
            result = domain.launch_project(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result), 202

    @server.route("/api/dashboard/jobs/pipeline", methods=["POST"])
    def api_dashboard_launch_pipeline():
        payload = request.get_json(silent=True) or {}
        try:
            result = domain.launch_pipeline(payload)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(result), 202


__all__ = [
    "DashboardDomain",
    "DashboardStaticAssets",
    "register_dashboard_routes",
]

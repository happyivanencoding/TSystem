"""展示/报告层统一命令入口。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m presentation_layer.cli",
        description="TP 展示/报告层统一入口",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inventory", help="列出当前统一管理的 app/report 入口")

    web = sub.add_parser("web-companies", help="启动 Dash 公司展示应用")
    web.add_argument("--host", default=None)
    web.add_argument("--port", type=int, default=None)
    web.add_argument("--debug", action="store_true")
    web.add_argument("--no-debug", dest="debug", action="store_false")
    web.set_defaults(debug=None)

    api = sub.add_parser("company-api", help="启动公司分析 FastAPI")
    api.add_argument("--host", default="0.0.0.0")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true")

    system = sub.add_parser("system-dashboard", help="启动 TP 系统总控 dashboard")
    system.add_argument("--host", default="127.0.0.1")
    system.add_argument("--port", type=int, default=8060)
    system.add_argument("--debug", action="store_true")

    worker = sub.add_parser("system-worker", help="运行 TP 系统总控后台 job worker")
    worker.add_argument("--once", action="store_true", help="只扫描并执行一轮 queued jobs")
    worker.add_argument("--interval", type=float, default=2.0, help="连续模式下的扫描间隔秒数")
    worker.add_argument("--limit", type=int, default=None, help="最多处理的 queued jobs 数量")
    worker.add_argument("--launch-dir", default=None, help="覆盖默认 launch queue 目录")

    checks = sub.add_parser("system-checks", help="运行 TP 子项目安全 smoke/inspect 检查")
    checks.add_argument("--project", action="append", help="只检查指定 project 或 project_id；可重复")

    sub.add_parser("dashboard-smoke", help="验证组合 dashboard 报告类可导入")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "inventory":
        print("apps:")
        print("  web-companies  -> presentation_layer.apps.des_companies")
        print("  company-api    -> presentation_layer.apps.company_analysis_api")
        print("  system-dashboard -> presentation_layer.apps.system_dashboard")
        print("  system-worker  -> presentation_layer.apps.system_jobs")
        print("  system-checks  -> presentation_layer.apps.system_checks")
        print("  system-registry -> presentation_layer.apps.system_registry")
        print("reports:")
        print("  dashboard      -> presentation_layer.reports.portfolio_dashboard")
        return 0

    if args.command == "web-companies":
        from presentation_layer.apps.des_companies import run

        run(host=args.host, port=args.port, debug=args.debug)
        return 0

    if args.command == "company-api":
        from presentation_layer.apps.company_analysis_api import run

        run(host=args.host, port=args.port, reload=args.reload)
        return 0

    if args.command == "system-dashboard":
        from presentation_layer.apps.system_dashboard import run

        run(host=args.host, port=args.port, debug=args.debug)
        return 0

    if args.command == "system-worker":
        from presentation_layer.apps import system_jobs
        from tp_core.data_sources import TP_ROOT
        from tp_core.workspace import DASHBOARD_WORK_DIR

        launch_dir = Path(args.launch_dir) if args.launch_dir else DASHBOARD_WORK_DIR / "launches"
        processed = system_jobs.run_worker(
            launch_dir,
            TP_ROOT,
            interval_seconds=args.interval,
            once=args.once,
            limit=args.limit,
        )
        print(f"system-worker processed {processed} queued jobs")
        return 0

    if args.command == "system-checks":
        from presentation_layer.apps.system_checks import main as checks_main

        check_args: list[str] = []
        for project in args.project or []:
            check_args.extend(["--project", project])
        return checks_main(check_args)

    if args.command == "dashboard-smoke":
        from presentation_layer.reports.portfolio_dashboard import get_dashboard_class

        cls = get_dashboard_class()
        print(f"PortfolioDashboard OK: {cls}")
        return 0

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

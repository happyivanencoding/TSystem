"""公司分析 FastAPI 的统一入口。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd

from tp_core.data_sources import TP_ROOT


BACKEND_ROOT = TP_ROOT / "08_presentation_layer" / "legacy_apps" / "company_analysis" / "backend"


def _evict_if_outside(module_name: str, root: Path) -> None:
    module = sys.modules.get(module_name)
    if module is None:
        return
    module_file = getattr(module, "__file__", None)
    if module_file is None:
        return
    try:
        Path(module_file).resolve().relative_to(root.resolve())
    except ValueError:
        sys.modules.pop(module_name, None)


def _prepare_imports() -> None:
    if not BACKEND_ROOT.exists():
        raise FileNotFoundError(f"公司分析 backend 目录不存在: {BACKEND_ROOT}")
    backend_path = str(BACKEND_ROOT)
    while backend_path in sys.path:
        sys.path.remove(backend_path)
    sys.path.insert(0, backend_path)
    _evict_if_outside("analysis", BACKEND_ROOT)
    importlib.invalidate_caches()


def _analysis() -> ModuleType:
    _prepare_imports()
    return importlib.import_module("analysis")


def create_app() -> Any:
    """创建公司分析 FastAPI app。

    路由定义集中在 presentation layer；业务函数暂时复用
    `08_presentation_layer/legacy_apps/company_analysis/backend/analysis.py`，其中数据读取已接入
    `PresentationDataRepository`。
    """

    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    analysis = _analysis()
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health_check():
        return {"status": "ok"}

    @app.get("/api/data-date")
    def data_date():
        try:
            return {"date": analysis.get_data_date()}
        except Exception as exc:  # pragma: no cover - FastAPI converts this for clients
            raise HTTPException(status_code=500, detail=f"Error getting data date: {exc}") from exc

    @app.get("/api/search")
    def search_companies(q: str = ""):
        try:
            df = analysis.get_data()
        except Exception as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Data loading error: {exc}") from exc
        if not q:
            return []
        q_l = q.lower()
        mask = (
            df["Symbol"].astype(str).str.lower().str.contains(q_l)
            | df["Name"].astype(str).str.lower().str.contains(q_l)
            | df["ISIN"].astype(str).str.lower().str.contains(q_l)
        )
        filtered = df[mask]
        if "Log Market Value" in filtered.columns:
            filtered = filtered.sort_values(by="Log Market Value", ascending=False)
        return analysis.clean_nan(filtered.head(20).to_dict(orient="records"))

    @app.get("/api/company/{isin}")
    def get_company_detail(isin: str):
        df = analysis.get_data()
        company_row = df[df["ISIN"] == isin]
        if company_row.empty:
            raise HTTPException(status_code=404, detail="Company not found")
        row = company_row.iloc[0]
        medians_dict = analysis.get_medians_data()
        region = row.get("Exchange Country Region")
        sector = row.get("Supersector")
        benchmark_data = {}
        if region and sector:
            raw_medians = medians_dict.get((region, sector), {})
            benchmark_data = {k: (v if pd.notna(v) else None) for k, v in raw_medians.items()}
        return analysis.clean_nan(
            {
                "data": row.to_dict(),
                "medians": benchmark_data,
                "clipboard_text": analysis.format_for_clipboard(row),
            }
        )

    @app.get("/api/company/{isin}/history")
    def get_company_history(isin: str):
        try:
            return analysis.get_history_data(isin)
        except Exception as exc:  # pragma: no cover
            print(f"Error fetching history for {isin}: {exc}")
            return []

    @app.get("/api/company/{isin}/returns")
    def get_company_returns(isin: str):
        try:
            return analysis.get_stock_returns(isin)
        except Exception as exc:  # pragma: no cover
            print(f"Error fetching returns for {isin}: {exc}")
            return []

    return app


def run(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:
    """本地启动公司分析 FastAPI app。"""

    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, reload=reload)


__all__ = ["BACKEND_ROOT", "create_app", "run"]

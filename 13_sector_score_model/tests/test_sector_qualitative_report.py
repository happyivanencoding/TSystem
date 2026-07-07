from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "sector_qualitative_report.py"
SPEC = importlib.util.spec_from_file_location("sector_qualitative_report_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sector_qualitative_report = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sector_qualitative_report
SPEC.loader.exec_module(sector_qualitative_report)


from tp_core.research_context import (  # noqa: E402
    CompanyAnalysisCsvAdapter,
    CountryModelAdapter,
    LatestCsvModelAdapter,
    LatestCsvSpec,
    ObsidianBridge,
    load_public_page_sources_from_yaml,
    load_rss_sources_from_yaml,
)


def test_query_terms_include_region_sector_and_factor_drivers() -> None:
    row = {
        "market": "EU",
        "sector_name": "Technology",
        "recommendation": "Positive",
        "momentum": 9.0,
        "growth": 8.0,
        "margin": 7.5,
        "lowvol": 5.0,
        "valuation": 2.0,
    }

    terms = sector_qualitative_report.query_terms("EU", "Technology", row)

    assert "欧洲" in terms
    assert "Technology" in terms
    assert "AI Capex" in terms
    assert "Trend" in terms
    assert "Value" in terms


def test_commentary_marks_missing_web_evidence() -> None:
    pack = sector_qualitative_report.EvidencePack(
        region="US",
        subject="Technology",
        view="Positive",
        model_scores={"score_final": 9.0},
        items=[
            sector_qualitative_report.EvidenceItem(
                id="1",
                kind="model",
                region="US",
                subject="Technology",
                view="Positive",
                stance="支持",
                title="model",
                summary="模型给出 Positive。",
            )
        ],
        missing_obsidian=True,
        missing_web_count=2,
    )

    text = sector_qualitative_report.commentary_for_pack(pack)

    assert "待复核观点" in text


def test_neutral_commentary_is_neutral_not_negative() -> None:
    pack = sector_qualitative_report.EvidencePack(
        region="US",
        subject="Media",
        view="Neutral",
        model_scores={"score_final": 5.0},
        items=[
            sector_qualitative_report.EvidenceItem(
                id="1",
                kind="model",
                region="US",
                subject="Media",
                view="Neutral",
                stance="支持",
                title="model",
                summary="模型给出 Neutral。",
            )
        ],
        missing_obsidian=True,
        missing_web_count=2,
    )

    text = sector_qualitative_report.commentary_for_pack(pack)

    assert "中性行业" in text
    assert "负面行业" not in text


def test_overview_table_includes_all_packs() -> None:
    packs = [
        sector_qualitative_report.EvidencePack(
            region="US",
            subject=f"Sector {rank}",
            view="Neutral",
            model_scores={
                "rank": float(rank),
                "score_final": float(20 - rank),
                "Trend": 1.0,
                "Growth": 2.0,
                "Margin": 3.0,
                "LowVol": 4.0,
                "Value": 5.0,
            },
            items=[],
            missing_obsidian=True,
            missing_web_count=2,
        )
        for rank in range(1, 20)
    ]

    table = sector_qualitative_report.render_overview_table(packs)

    assert len([line for line in table if line.startswith("| ")]) == 21
    assert "| 1 | [[US Sector 1]]" in "\n".join(table)
    assert "| 19 | [[US Sector 19]]" in "\n".join(table)


def test_obsidian_terms_exclude_region_and_factor_noise() -> None:
    terms = sector_qualitative_report.obsidian_terms("Technology")

    assert "Technology" in terms
    assert "AI Capex" in terms
    assert "US" not in terms
    assert "Trend" not in terms


def test_obsidian_search_skips_generated_monthly_sector_views(tmp_path: Path) -> None:
    generated = tmp_path / "10_Investment" / "02_Sectors" / "Monthly_Sector_Views"
    generated.mkdir(parents=True)
    (generated / "2026-06 TP 行业观点.md").write_text("Technology needs_review", encoding="utf-8")
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "Technology cycle.md").write_text("Technology demand notes", encoding="utf-8")

    hits = ObsidianBridge(tmp_path).search(["Technology"], limit=10)

    assert [hit.title for hit in hits] == ["Technology cycle"]


def test_source_config_loaders_keep_rss_and_public_pages_separate(tmp_path: Path) -> None:
    config = tmp_path / "sources.yaml"
    config.write_text(
        """
sources:
  - name: RSS A
    url: https://example.com/rss.xml
    region: US
    subjects: [Technology]
public_pages:
  - name: Page B
    url: https://example.com/page
    region: EU
    subjects: [Energy]
""".strip(),
        encoding="utf-8",
    )

    rss = load_rss_sources_from_yaml(config)
    pages = load_public_page_sources_from_yaml(config)

    assert [source.name for source in rss] == ["RSS A"]
    assert [source.name for source in pages] == ["Page B"]


def test_latest_csv_model_adapter_adds_market_and_parses_dates(tmp_path: Path) -> None:
    latest = tmp_path / "latest.csv"
    latest.write_text("Date,sector_name,recommendation\n2026-06-30,Technology,Positive\n", encoding="utf-8")

    rows = LatestCsvModelAdapter((LatestCsvSpec("US", latest),)).load_rows()

    assert rows[0]["market"] == "US"
    assert str(rows[0]["Date"].date()) == "2026-06-30"


def test_short_theme_matching_uses_word_boundaries() -> None:
    assert not sector_qualitative_report._matches_sector_text(
        "large banks are well positioned to weather a severe recession",
        "automobiles and parts",
        ["ev"],
    )
    assert sector_qualitative_report._matches_sector_text(
        "ev demand remains an important auto cycle driver",
        "automobiles and parts",
        ["ev"],
    )


def test_explicit_subject_matching_keeps_comma_sector_names_intact() -> None:
    assert sector_qualitative_report._matches_explicit_subject(
        "Food, Beverage and Tobacco",
        "Food, Beverage and Tobacco",
    )
    assert not sector_qualitative_report._matches_explicit_subject(
        "Construction and Materials",
        "Chemicals",
    )


def test_country_model_adapter_adds_generic_subject_fields(tmp_path: Path) -> None:
    latest = tmp_path / "country.csv"
    latest.write_text(
        "Date,country,country_label,recommendation\n2026-06-30,EMU,EMU,Negative\n",
        encoding="utf-8",
    )

    rows = CountryModelAdapter(latest).load_rows()

    assert rows[0]["model_region"] == "EMU"
    assert rows[0]["model_subject"] == "EMU"
    assert rows[0]["model_view"] == "Negative"


def test_company_analysis_csv_adapter_adds_generic_subject_fields(tmp_path: Path) -> None:
    latest = tmp_path / "company.csv"
    latest.write_text(
        "Date,Name,COUNTRY,recommendation\n2026-06-30,ASML,NETHERLANDS,Positive\n",
        encoding="utf-8",
    )

    rows = CompanyAnalysisCsvAdapter(latest).load_rows()

    assert rows[0]["model_region"] == "NETHERLANDS"
    assert rows[0]["model_subject"] == "ASML"
    assert rows[0]["model_view"] == "Positive"

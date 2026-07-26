from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from tp_data.providers import OkfNewsProvider, ProviderContext, ProviderQuery


def test_okf_provider_reads_public_news_without_modifying_notes(tmp_path: Path) -> None:
    note = tmp_path / "卡片盒子" / "40_News_Room" / "2026_Q3_Clippings" / "clip.md"
    note.parent.mkdir(parents=True)
    original = """---
title: Test market news
source: https://example.com/news?utm_source=test
source_date: 2026-07-01
captured: 2026-07-02
region: US
view: Neutral
stance: neutral
---
## 摘要
Markets were unchanged.

## 相关笔记
[[private-local-note]]
"""
    note.write_text(original, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "source_path": "卡片盒子/40_News_Room/2026_Q3_Clippings/clip.md",
                    "okf_path": "news/clip.md",
                    "type": "clipping",
                    "title": "Test market news",
                    "privacy_level": "public_internal",
                }
            ]
        ),
        encoding="utf-8",
    )

    result = OkfNewsProvider().fetch(
        ProviderQuery(
            source="okf_news",
            job={"manifest_path": str(manifest), "notes_root": str(tmp_path)},
        ),
        ProviderContext(retrieved_at=datetime(2026, 7, 3, tzinfo=timezone.utc)),
    )

    assert len(result.records) == 1
    record = result.records[0]
    assert record.source_url == "https://example.com/news"
    assert record.available_at.date().isoformat() == "2026-07-02"
    assert "private-local-note" not in record.text
    assert record.metadata["predictor_default"] is False
    assert note.read_text(encoding="utf-8") == original

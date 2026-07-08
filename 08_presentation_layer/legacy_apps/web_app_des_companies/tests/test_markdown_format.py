"""Tests for Markdown normalization used before ``dcc.Markdown`` rendering."""
from __future__ import annotations

import re

from src.services.markdown_format import format_markdown_body


def test_empty_none():
    assert format_markdown_body(None) == ""
    assert format_markdown_body("") == ""


def test_normalize_dup_h2_title():
    src = "## ACME Corp ##\n\na) foo.\n"
    out = format_markdown_body(src)
    assert out.startswith("## ACME Corp\n")
    assert "## ACME Corp ##" not in out


def test_normalize_dup_h1_title():
    src = "# Pas de résumé #\n\nHello."
    out = format_markdown_body(src)
    assert out.startswith("## Pas de résumé\n")
    assert "# Pas de résumé #" not in out


def test_sentiment_block_footer_html():
    src = "Some analysis text.\n##SENTIMENT = 7##"
    out = format_markdown_body(src)
    assert "##SENTIMENT" not in out
    assert "md-sentiment-card" in out
    assert "7" in out


def test_sentiment_eq_frac_italics():
    src = "Intro. *SENTIMENT = 5/10* commentaire"
    out = format_markdown_body(src)
    assert "SENTIMENT = 5/10" not in out
    assert "5/10" in out
    assert "md-sentiment" in out
    assert "commentaire" in out


def test_letter_rubric_h4():
    src = "a) Description.\n\nBody para."
    out = format_markdown_body(src)
    assert "md-subhead" in out
    assert "Description" in out


def test_letter_ticker_on_same_line_and_hash_sentiment_without_closing_pounds():
    src = (
        "a) Description. ABN AM \n"
        "b) Activités. ABN AMRO offers a compre\n"
        " Suite. ##SENTIMENT = 6"
    )
    out = format_markdown_body(src)
    assert out.count("<h4") == 2
    assert "ABN AMRO" in out
    assert "md-sentiment-card" in out
    assert "##SENTIMENT" not in out
    assert "6" in out


def test_letter_b_glued_to_previous_line_gets_a_newline():
    src = "Foo bar. b) activités. Suite."
    out = format_markdown_body(src)
    assert "md-subhead" in out
    assert "activités" in out.lower() or "Activ" in out


def test_letter_rubric_very_long_a_line_still_forms_h4():
    """Aucune troncature de ``core`` à 200 caractères : a) … b) en un seul run."""
    long_body = "x" * 400
    src = f"Arista Networks\na) description. {long_body} Asie-Pacifique. b) activités. Suite contenu."
    out = format_markdown_body(src)
    assert out.count("<h4") == 2
    assert "data-sec=\"a\"" in out
    assert "data-sec=\"b\"" in out


def test_title_line_then_letter_rubric_a():
    src = "Arista Networks\na) description. Court. Asie. b) activités. Suite."
    out = format_markdown_body(src)
    assert "Arista Networks" in out
    assert out.count("<h4") == 2


def test_letter_rubric_without_period_after_keyword():
    """Exporters often omit the full stop: ``a) Description ABB …``."""
    src = "a) Description ABB Ltd is \nb) Activités ABB operates throu"
    out = format_markdown_body(src)
    assert out.count("<h4") == 2
    assert "ABB Ltd" in out
    assert "ABB operates" in out


def test_escaped_quotes_then_emphasis():
    src = 'Intro \\"supermajors\\" end.'
    out = format_markdown_body(src)
    assert '\\"' not in out
    assert '"supermajors"' in out or "supermajors" in out


def test_reflow_french_semicolon_long_line():
    """Ligne > 300 car. : ` ; ` entre propositions -> paragraphes distincts."""
    a = "Phrase " * 45
    b = "Autre " * 50
    src = a + " ; " + b
    out = format_markdown_body(src)
    assert "\n\n" in out


def test_reflow_respects_inc_abbreviation():
    s = "Arista " * 30 + "Inc. The company remains active. " + "More " * 50
    out = format_markdown_body(s)
    norm = re.sub(r"\s+", " ", out)
    assert "Inc. The" in norm


def test_reflow_inserts_blanks_in_very_long_line():
    s = "Mot " * 80 + ". " + "Suite " * 80
    out = format_markdown_body(s)
    assert out.count("\n\n") >= 1


def test_fused_bold_bullet_atouts_style():
    src = (
        "**Atouts:** * **Brands:** First block of text. "
        "* **Global:** Second block. * **Other:** End."
    )
    out = format_markdown_body(src)
    assert "**Atouts:**" in out
    assert "\n\n" in out
    assert "First block" in out

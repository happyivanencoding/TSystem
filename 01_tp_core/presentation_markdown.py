"""共享 Markdown 清洗器。

Normalize raw Markdown from parquet for better on-screen reading.

The column is named ``HTMLbody`` but content is often Markdown with noisy
conventions: duplicated ``##`` titles, SENTIMENT markers in many shapes,
and pseudo-highlights ``\\word\\`` or ``\\\"...\\\"`` from LLM / export.
"""
from __future__ import annotations

import html
import re

# --- SENTIMENT: multiple real-world patterns (incl. at start or mid-paragraph) ---
# Order matters: most specific first, then looser. Each pass removes a family.
# Type tags for footer rendering: "signed" (-10..+10 style), "frac" (x/10), "raw"

# ``##SENTIMENT = n`` with optional ``##`` (many exports forget the closing hash).
_RE_SENT_1 = re.compile(
    r"##\s*SENTIMENT\s*=\s*([+-]?\d{1,2})(?:\s*#+)?",
    re.IGNORECASE,
)
# Bold rubric, e.g. **SENTIMENT : 8/10**
_RE_SENT_2 = re.compile(
    r"\*{0,2}\s*SENTIMENT\s*:\s*(\d{1,2}\s*/\s*10)\s*\*{0,2}",
    re.IGNORECASE,
)
# Inline colon without hash: SENTIMENT : 8/10
_RE_SENT_3 = re.compile(
    r"(?<![\w#])SENTIMENT\s*:\s*(\d{1,2}\s*/\s*10)",
    re.IGNORECASE,
)
# ``*SENTIMENT = 5/10*`` or ``SENTIMENT = 5/10`` (fraction, not a signed int scale)
_RE_SENT_EQ_FRAC = re.compile(
    r"(?<!\w)SENTIMENT\s*=\s*(\d{1,2}/10)(?:\s*\*+)?",
    re.IGNORECASE,
)
# Remaining "SENTIMENT = ±n" with optional # / ** (no slash fraction)
_RE_SENT_4 = re.compile(
    r"(?<![\w#])SENTIMENT\s*=\s*([+-]?\d{1,2})(?:\s*#+|\s*\*+)*",
    re.IGNORECASE,
)

# First-line title: ## Name ##  (duplicate hashes are redundant noise).
_RE_H2_DUP = re.compile(r"^##\s+(.+?)\s*##\s*$")

# Some exports use a single-# title with a trailing ``#`` (e.g. ``# Pas de résumé #``).
_RE_H1_DUP = re.compile(r"^#\s+(.+?)\s*#\s*$")

# Filler / separator lines in NEWS when no real news.
_RE_NO_NEWS_FENCE = re.compile(
    r"^\s*[-_]{3,}\s*(\[.+?\].*?)\s*[-_]{3,}\s*$", re.DOTALL | re.MULTILINE
)

# Long runs of hyphens (plain-text rulers).
_RE_LONG_DASH = re.compile(r"^\s*[-]{5,}\s*$", re.MULTILINE)

# Excessive vertical whitespace after normalization.
_RE_MANY_BLANKS = re.compile(r"\n{3,}")

# a) / b) / c) section labels after inline text: force a soft break.
_RE_LETTER_SECTION = re.compile(
    r"([.!?\u2026\"»])\s+([a-e]\)\s)",  # a–e + Unicode ellipsis, case-insensitive below
    re.IGNORECASE,
)

# Slash-wrapped short phrases (e.g. \Conserver\, \supermajors\).
_RE_SLASH_EMPH = re.compile(
    r"\\(\s*[^\n\\*#]{1,120}?)\\",
    re.DOTALL,
)

# a) / b) / c) / d) / e) rubric lines (Description, Activités, etc.)
_RUBRIC_LABELS: tuple[str, ...] = (
    "atouts et enjeux",
    "atouts",
    "enjeux",
    "activités",
    "activities",
    "compétiteurs",
    "competiteurs",
    "competiteur",
    "compétiteur",
    "description",
    "sentiment",
    "risques",
    "risque",
)

# After ``a)``/``b)`` …, a known label then body. Optional ``.`` after the label. Exporters
# often use ``a) Description ABB`` (no full stop) — ``(Rubric)(?:\.)?\s*(rest)`` covers both.
# Put the longest headword first in the alternation to avoid a short ``atouts`` winning over
# ``atouts et enjeux``.
_RUBRIC_LEAD = re.compile(
    r"(?i)^"
    r"(atouts et enjeux|activités|activities|atouts|enjeux|"
    r"comp[ée]titeurs?|competiteurs?|competiteur|compet|"
    r"descriptions?|description|sentiment|risques?)"
    r"(?:\.)?"
    r"\s*"
    r"(.*)$"
)


def _match_letter_rubric_title(
    letter: str, core: str
) -> tuple[str, str, str] | None:
    """If ``core`` (after a-e)) is a known DES/NEWS rubric, return (letter, display, rest)."""
    t = re.sub(r"\*+", "", core).strip()
    if not t:
        return None
    # Cores are often a full long paragraph: never reject on length; only
    # m_short (ticker) heuristics use a short-remainder bound.

    m_lead = _RUBRIC_LEAD.match(t)
    if m_lead:
        first = m_lead.group(1).strip()
        rem = (m_lead.group(2) or "").strip()
        stem = re.sub(r"\*+", "", first).strip(" .:;*").lower().rstrip(".")
        ok = any(
            stem == lab
            or stem.startswith(lab + " ")
            for lab in _RUBRIC_LABELS
        )
        if not ok and re.match(
            r"^(description|activités|activities|descriptions?|sentiment|risques?)\b",
            stem,
        ):
            ok = True
        if ok:
            display = html.escape(re.sub(r"\*+", "", first)[:120])
            if rem:
                rem = re.sub(r"\*+", "", rem)
            return (letter.lower(), display, rem)
    # "Description. ABN" (short remainder, e.g. company ticker on same line)
    m_short = re.match(
        r"^([^.]+)\.(\s*[A-ZÀ-Æ0-9(«\"](?:[A-ZÀ-Æ0-9 .&'\-]|\*+){0,50})$", t
    )
    m_dot = re.match(r"^([^.]+)\.(\s+[A-ZÀ-Æ0-9(«\"].+)$", t)
    m_dot2 = re.match(r"^([^.]+)\.(\s+[a-zà-ÿ].{15,})$", t)
    if m_short and len(m_short.group(1)) <= 50 and 0 < len(m_short.group(2).strip()) < 32:
        first, rem = m_short.group(1).strip(), m_short.group(2).strip()
    elif m_dot and len(m_dot.group(1)) <= 60:
        first, rem = m_dot.group(1).strip(), m_dot.group(2).strip()
    elif m_dot2 and len(m_dot2.group(1)) <= 55:
        first, rem = m_dot2.group(1).strip(), m_dot2.group(2).strip()
    else:
        first, rem = t, ""

    stem = re.sub(r"\*+", "", first).strip(" .:;*").lower().rstrip(".")
    ok = any(
        stem == lab
        or stem.startswith(lab + " ")
        or stem.startswith(lab + ".")
        for lab in _RUBRIC_LABELS
    )
    if not ok and re.match(
        r"^(description|activités|activities|sentiment|risques?)\b", stem
    ):
        ok = True
    if not ok:
        return None

    display = html.escape(re.sub(r"\*+", "", first).strip()[:120])
    if rem:
        rem = re.sub(r"\*+", "", rem)
    return (letter.lower(), display, rem)


def _iter_lines_with_letter_rubrics(s: str) -> str:
    """Turn ``a) Description.``-style lines into HTML headings + remainder."""
    out: list[str] = []
    for line in s.split("\n"):
        m = re.match(r"^(\s*)([a-e])\)\s*(.+)$", line, re.IGNORECASE)
        if not m:
            out.append(line)
            continue
        letter = m.group(2).lower()
        core = m.group(3)
        tri = _match_letter_rubric_title(letter, core)
        if not tri:
            out.append(line)
            continue
        ltr, display, remainder = tri
        row = (
            f'{m.group(1)}<h4 class="md-subhead md-subhead--{html.escape(ltr)}"'
            f' data-sec="{html.escape(ltr)}">'
            f'<span class="md-subhead__index">{html.escape(ltr)})</span> '
            f'<span class="md-subhead__label">{display}</span></h4>'
        )
        out.append(row)
        if remainder:
            out.append(remainder)
    return "\n".join(out)


def _strip_sentiment_marks(
    s: str,
) -> tuple[str, list[tuple[str, str]]]:
    """Remove SENTIMENT markers anywhere in ``s``; return (clean, signals)."""
    found: list[tuple[str, str]] = []
    t = s

    def _add_signed(m: re.Match[str]) -> str:
        val = m.group(1).replace(" ", "")
        found.append(("signed", val))
        return " "

    def _add_frac(m: re.Match[str]) -> str:
        parts = m.group(1).split("/", 1)
        if len(parts) == 2:
            found.append(("frac", f"{parts[0].strip()}/{parts[1].strip()}"))
        return " "

    t = re.sub(_RE_SENT_1, _add_signed, t)
    t = re.sub(_RE_SENT_2, _add_frac, t)
    t = re.sub(_RE_SENT_3, _add_frac, t)
    t = re.sub(_RE_SENT_EQ_FRAC, _add_frac, t)
    t = re.sub(_RE_SENT_4, _add_signed, t)
    t = re.sub(r"\n{2,}\s*\n{2,}", "\n\n", t)
    return t, found


def _sentiment_footer_html(
    found: list[tuple[str, str]],
) -> str:
    if not found:
        return ""
    # De-dup by (kind, value) preserving order
    seen: set[tuple[str, str]] = set()
    uniq: list[tuple[str, str]] = []
    for k, v in found:
        key = (k, v)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((k, v))
    if not uniq:
        return ""
    li_parts: list[str] = []
    for kind, val in uniq:
        if kind == "frac":
            li_parts.append(
                f'<li class="md-sentiment__item" data-type="frac">'
                f'<span class="md-sentiment__value">{html.escape(val)}</span> '
                f'<span class="md-sentiment__meta">(échelle 0–10, extrait texte)</span></li>'
            )
        else:
            li_parts.append(
                f'<li class="md-sentiment__item" data-type="signed">'
                f'<span class="md-sentiment__value">{html.escape(val)}</span> '
                f'<span class="md-sentiment__meta">(échelle signée approx. −10 à +10, extrait texte)</span></li>'
            )
    items = "\n".join(li_parts)
    return (
        "\n\n<aside class=\"md-sentiment-card\" role=\"complementary\" aria-label=\"Polarité\">"
        f"<h5 class=\"md-sentiment__title\">Indicateurs de polarité (extraits)</h5>"
        f"<p class=\"md-sentiment__hint\">Repérés dans le texte; plusieurs formats d'export regroupés ici.</p>"
        f"<ul class=\"md-sentiment__list\">{items}</ul></aside>\n"
    )


def _normalize_leading_block_title(s: str) -> str:
    r"""Turn ``## Title ##`` or ``# Title #`` (first line) into a clean ``## Title`` heading."""
    if not s or s.lstrip()[:1] != "#":
        return s
    first_line, sep, rest = s.partition("\n")
    m2 = _RE_H2_DUP.match(first_line.strip())
    if m2:
        title = m2.group(1).strip()
        return f"## {title}{sep}{rest}" if rest else f"## {title}\n"
    m1 = _RE_H1_DUP.match(first_line.strip())
    if m1:
        title = m1.group(1).strip()
        return f"## {title}{sep}{rest}" if rest else f"## {title}\n"
    return s


def _unescape_pseudo_latex(s: str) -> str:
    r"""Unescape common artifacts: \\"...\\"  ->  "...", ``\\term\\` -> *term*."""
    s = s.replace("\\\"", '"')

    def _emph(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if not inner or inner.startswith("#"):
            return match.group(0)
        if len(inner) > 200:
            return match.group(0)
        return f"*{inner}*"

    s = _RE_SLASH_EMPH.sub(_emph, s)
    return s


def _break_embedded_letter_parens(s: str) -> str:
    """Insert newlines so ``(letter)`` section markers are not glued to the title line.

    Handles:
    - ``Arista Networks a) description. …``  →  title line + ``a)`` on the next line
    - ``Asie-Pacifique. b) activités. …``  (including lowercase rubrics) after sentence end
    """
    s = s.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2007", " ")
    s = re.sub(
        r"([.!?:;\u2026»\u00bb])\s*([a-e]\))\s+",
        r"\1\n\2 ",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"([A-Za-zÀ-ÿ0-9\)\]»%])\s+"
        r"([a-e]\))\s+"
        r"(?=(?:"
        r"description|descriptions?|activités|activities|atouts|enjeux|"
        r"comp[ée]titeurs?|competiteurs?|compet|sentiment|risques?)\b)",
        r"\1\n\2 ",
        s,
        flags=re.IGNORECASE,
    )
    return s


def _insert_letter_section_breaks(s: str) -> str:
    """Add a line break before ``a) `` … ``b)`` when glued to a sentence end."""
    return _RE_LETTER_SECTION.sub(r"\1\n\n\2", s)


def _insert_newlines_before_letter_rubrics(s: str) -> str:
    """If ``b) Activités`` starts on the same line as previous text, force a new line.

    Exporters often concatenate ``a) … b)…`` on one line, which would otherwise
    miss the per-line letter regex.
    """
    return re.sub(
        r"(?<=[A-Za-zÀ-ÿ0-9.!?»,]) +"
        r"([a-e]\))(\s+)"
        r"((?:\*\*)?(?:Description|descriptions?|activités|activities|atouts|enjeux|"
        r"comp[ée]titeurs?|competiteurs?|compet|sentiment|risques?)\b)",
        r"\n\1\2\3",
        s,
        flags=re.IGNORECASE,
    )


def _insert_newlines_before_letter_paren(s: str) -> str:
    r"""Generic break: ``… text b) …``  →  newline before ``<letter>)``.

    Catches same-line rubrics that do not match the keyword list, as long as the
    next token starts with a letter (incl. ``activités`` in lower case) or digit.
    """
    return re.sub(
        r"(?<=[A-Za-zÀ-ÿ0-9.!?»,\)])\s+"
        r"([a-e]\))(\s+)"
        r"(?=[0-9A-Za-zÀ-ÿà-ÿ\"«(])",
        r"\n\1\2",
        s,
    )


def _normalize_dashes(s: str) -> str:
    """Long hyphen-only lines -> Markdown ``---`` for visual separation."""
    return _RE_LONG_DASH.sub("---", s)


def _style_no_news_filler(s: str) -> str:
    """Make \"no news\" blocks readable as a callout (when matching the pattern)."""
    m = _RE_NO_NEWS_FENCE.search(s)
    if not m:
        return s
    inner = m.group(1).strip()
    if not inner:
        return s
    return s.replace(
        m.group(0),
        f"\n\n> **Aucun fait marquant (source)**\n> {inner}\n",
        1,
    )


def _collapse_blank_runs(s: str) -> str:
    s = s.strip()
    s = _RE_MANY_BLANKS.sub("\n\n", s)
    return s


def _normalize_fused_bold_bullet_stanza(s: str) -> str:
    r"""Break glued ``\*\*Rubric:\*\* * \*\*Sous-titre\*\*:`` so lists render with hierarchy.

    Exports often put ``**Atouts:** * **Marques :** text * **R&D :** …`` on one line; without
    newlines, Markdown misparses italics and list markers.
    """
    # 1) After a bold line ``**Rubric:`` (content ends with : then ``**``), new block before ``* **Sous-élément:`` …
    s = re.sub(
        r"(\*\*[^*]+:\*\*)\s+(\*)\s+(\*\*[^*]+:\*\*)",
        r"\1\n\n\2 \3",
        s,
    )
    # 2) Next fused item: ``… . * **Label:**`` (line-start ``*`` for list + bold sublabel)
    s = re.sub(
        r'(?<=[\w.!?:)»"0-9%])\s+(\*)\s+(\*\*[^*]+:\*\*)',
        r"\n\n\1 \2",
        s,
    )
    return s


# Long DES blocks are often one exporter line. Reflow plain lines (not h4) so
# Markdown can emit several <p> and improve vertical rhythm.
_MIN_LINE_FOR_REFLOW = 300
_STILL_LONG = 420
# Token just before a period: skip (abbrev / legal form), not a sentence end
_ABB_NO_SPLIT: frozenset[str] = frozenset(
    {
        "m", "mme", "dr", "st", "sté", "stes", "cf", "eg", "e.g", "i.e", "ie",
        "etc", "vol", "art", "inc", "ltd", "sa", "s.a", "sas", "gmbh", "ag", "se",
        "b.v", "bv", "plc", "llc", "l.l.c", "assoc", "nv", "ul", "cie",
    }
)


def _insert_extra_sentence_breaks(text: str) -> str:
    """Add ``\n\n`` after sentence-ish ``. +`` in still-long segments."""
    m = re.finditer(
        r"(?<![0-9])\. +(?=[A-ZÀ-Ÿ\"«(])", text, flags=re.IGNORECASE
    )
    insert_at: list[int] = []
    for mo in m:
        end_dot = mo.start()
        if end_dot < 200:
            continue
        pre_start = max(0, end_dot - 32)
        window = text[pre_start:end_dot]
        wds = re.findall(
            r"[A-Za-zÀ-ÿ&][A-Za-zÀ-ÿ&'.-]+", window.replace("\n", " ")
        )
        if wds:
            lw = wds[-1].lower().rstrip(".")
            if lw in _ABB_NO_SPLIT or len(lw) <= 1:
                continue
        insert_at.append(mo.end())

    if not insert_at:
        return text
    parts: list[str] = []
    start = 0
    for pos in insert_at:
        parts.append(text[start:pos].rstrip())
        start = pos
    parts.append(text[start:].lstrip())
    return "\n\n".join(p for p in parts if p).strip()


def _reflow_rich_paragraphs(s: str) -> str:
    """Add paragraph breaks in very long text blocks to restore visual hierarchy."""
    lines = s.split("\n")
    out: list[str] = []
    for line in lines:
        t = line
        st = t.lstrip()
        if st.startswith("<h4 "):
            out.append(t)
            continue
        if len(t.strip()) < _MIN_LINE_FOR_REFLOW:
            out.append(t)
            continue
        t = t.replace(" ; ", " ;\n\n")
        chunks = re.split(r"\n\n+", t)
        merged: list[str] = []
        for c in chunks:
            c2 = c.strip()
            if not c2:
                continue
            if len(c2) >= _STILL_LONG:
                c2 = _insert_extra_sentence_breaks(c2)
            merged.append(c2)
        out.append("\n\n".join(merged))
    return "\n".join(out)

def format_markdown_body(raw: str | None) -> str:
    """Return content for ``dcc.Markdown`` (Markdown + a little HTML) with better rhythm.

    The output may include ``<h4>``/``<aside>`` tags: enable ``dangerously_allow_html`` on
    the caller when rendering.
    """
    if raw is None:
        return ""
    s = str(raw).replace("\r\n", "\n").replace("\r", "\n")

    s, sent_found = _strip_sentiment_marks(s)
    s = _normalize_leading_block_title(s)
    s = _unescape_pseudo_latex(s)
    s = _style_no_news_filler(s)
    s = _normalize_fused_bold_bullet_stanza(s)
    s = _break_embedded_letter_parens(s)
    s = _insert_letter_section_breaks(s)
    s = _insert_newlines_before_letter_rubrics(s)
    s = _insert_newlines_before_letter_paren(s)
    s = _iter_lines_with_letter_rubrics(s)
    s = _normalize_dashes(s)
    s = _reflow_rich_paragraphs(s)
    s = _collapse_blank_runs(s)
    s = s + _sentiment_footer_html(sent_found)
    return s

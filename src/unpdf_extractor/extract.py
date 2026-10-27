"""Text repair, value checks, and box-based field extraction.

Words never become page-wide phrases.  A profile field is a small box; only
words inside that box take part in the field, and lines are built inside the
box.  This is what keeps side-by-side panels from bleeding into each other.

Everything here is pure: no PDF reading, no SQLite, no printing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from .profile import Field, LayoutProfile

ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
ARABIC_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)
PRESENTATION_RANGES = ((0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


# ------------------------------------------------------------------ text


def norm_text(text: str) -> str:
    """Lowercase and drop everything but word characters."""
    return re.sub(r"[^\w]+", "", text.lower(), flags=re.UNICODE)


def clean(text: str) -> str:
    """Collapse whitespace runs and trim."""
    return re.sub(r"\s+", " ", text).strip()


def is_arabic(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in ARABIC_RANGES)


def presentation_count(text: str) -> int:
    """Count shaped Arabic glyphs that NFKC would change back to letters."""
    count = 0
    for ch in text:
        code = ord(ch)
        if any(start <= code <= end for start, end in PRESENTATION_RANGES):
            if unicodedata.normalize("NFKC", ch) != ch:
                count += 1
    return count


def repair_arabic(text: str) -> str:
    """Turn visually-ordered, shaped Arabic into logical order."""
    presentation = presentation_count(text)
    if not presentation:
        return text

    base_letters = sum(1 for ch in text if 0x0600 <= ord(ch) <= 0x06FF and ch.isalpha())
    if base_letters > presentation:
        return text

    runs: list[tuple[str, str]] = []
    current = ""
    current_kind: str | None = None
    for ch in text:
        if unicodedata.category(ch).startswith("M"):
            kind = current_kind or "rtl"
        elif ch.isdigit():
            kind = "ltr"
        elif not ch.isalnum():
            kind = "neutral"
        else:
            kind = "rtl" if is_arabic(ch) else "ltr"
        if current_kind == kind:
            current += ch
        else:
            if current:
                runs.append((current_kind, current))
            current, current_kind = ch, kind
    if current:
        runs.append((current_kind, current))

    resolved: list[list[str]] = []
    for index, (kind, chunk) in enumerate(runs):
        if kind != "neutral":
            resolved.append([kind, chunk])
            continue
        previous = next(
            (runs[i][0] for i in range(index - 1, -1, -1) if runs[i][0] != "neutral"),
            None,
        )
        following = next(
            (runs[i][0] for i in range(index + 1, len(runs)) if runs[i][0] != "neutral"),
            None,
        )
        resolved.append([previous if previous == following and previous else "neutral", chunk])

    merged: list[list[str]] = []
    for kind, chunk in resolved:
        if merged and merged[-1][0] == kind:
            merged[-1][1] += chunk
        else:
            merged.append([kind, chunk])

    logical = "".join(chunk[::-1] if kind == "rtl" else chunk for kind, chunk in reversed(merged))
    return unicodedata.normalize("NFKC", logical)


# --------------------------------------------------------------- values

DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M",
)


def parse_date(value: str):
    """Parse the date formats that appear in the source documents."""
    value = re.sub(r"\s*:\s*", ":", str(value).strip())
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(value, pattern)
        except (ValueError, TypeError):
            continue
    return None


def check_value(value: str, kind: str) -> str | None:
    """Return why ``value`` does not match ``kind``, or None when it does."""
    kind = (kind or "text").strip().lower()
    if kind == "digits":
        if not re.fullmatch(r"\d+", value):
            return "not digits"
    elif kind in {"number", "decimal"}:
        try:
            float(value.replace(",", ""))
        except ValueError:
            return "not a number"
    elif kind == "integer":
        if not re.fullmatch(r"\d+", value):
            return "not an integer"
    elif kind == "date":
        if not parse_date(value):
            return "invalid date"
    return None


# ------------------------------------------------------------- geometry


def word_center(word: dict) -> tuple[float, float]:
    """Centre of a word box in PDF points."""
    x = (float(word["x0"]) + float(word["x1"])) / 2
    y = (float(word["top"]) + float(word["bottom"])) / 2
    return x, y


@dataclass(frozen=True)
class FieldValue:
    name: str
    value: str
    page: int
    box: tuple[float, float, float, float]
    method: str = "text"


def words_in_box(
    words: list[dict],
    page: int,
    box,
    page_size: tuple[float, float],
) -> list[dict]:
    x0, y0, x1, y1 = box.points(*page_size)
    selected = []
    for word in words:
        if int(word.get("page", 0)) != page:
            continue
        x, y = word_center(word)
        if x0 <= x <= x1 and y0 <= y <= y1:
            selected.append(word)
    return selected


def group_lines(words: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    """Group words whose vertical midpoints overlap one visual line."""
    ordered = sorted(words, key=lambda word: (word_center(word)[1], float(word["x0"])))
    lines: list[list[dict]] = []
    for word in ordered:
        y = word_center(word)[1]
        if not lines:
            lines.append([word])
            continue
        previous = lines[-1]
        previous_y = sum(word_center(item)[1] for item in previous) / len(previous)
        if abs(y - previous_y) <= tolerance:
            previous.append(word)
        else:
            lines.append([word])
    return lines


def join_line(words: list[dict]) -> str:
    """Read a line in its natural direction, then repair shaped Arabic.

    Whole Arabic lines read right-to-left.  A contiguous Latin run inside an
    Arabic line still reads left-to-right, so the run is flipped back after the
    line is ordered.  This matters for routes like ``WADI DAWASIR``.
    """
    if not words:
        return ""
    has_arabic = any(ARABIC.search(str(word.get("text", ""))) for word in words)
    ordered = sorted(words, key=lambda word: float(word["x0"]), reverse=has_arabic)
    if has_arabic:
        ordered = _fix_latin_runs(ordered)
    pieces = [repair_arabic(str(word.get("text", ""))) for word in ordered]
    return clean(" ".join(piece for piece in pieces if piece))


def _fix_latin_runs(words: list[dict]) -> list[dict]:
    result: list[dict] = []
    run: list[dict] = []

    def flush() -> None:
        if run:
            result.extend(reversed(run) if len(run) > 1 else run)
            run.clear()

    for word in words:
        text = str(word.get("text", ""))
        if ARABIC.search(text) or not re.search(r"[A-Za-z]", text):
            flush()
            result.append(word)
        else:
            run.append(word)
    flush()
    return result


def extract_fields(
    profile: LayoutProfile,
    words: list[dict],
    page_sizes: list[tuple[float, float]],
    ocr_pages: set[int] | frozenset[int] = frozenset(),
) -> dict[str, FieldValue]:
    """Extract every declared field that has words in its box."""
    result: dict[str, FieldValue] = {}
    for field in profile.fields:
        if not 1 <= field.page <= len(page_sizes):
            continue
        selected = words_in_box(words, field.page, field.box, page_sizes[field.page - 1])
        value = _value_for(field, selected) if selected else ""
        if not value:
            continue
        result[field.name] = FieldValue(
            name=field.name,
            value=value,
            page=field.page,
            box=(field.box.left, field.box.top, field.box.right, field.box.bottom),
            method="ocr" if field.page in ocr_pages else "text",
        )
    return result


def _value_for(field: Field, words: list[dict]) -> str:
    lines = group_lines(words)
    if field.mode == "multi":
        return " ".join(text for text in (join_line(line) for line in lines) if text)
    if field.mode == "all":
        return " | ".join(text for text in (join_line(line) for line in lines) if text)
    if not lines:
        return ""
    # Most fields are one line.  If the box catches a neighbouring row, the
    # line with the most characters is the intended value, not a label.
    line = max(lines, key=lambda item: sum(len(str(word.get("text", ""))) for word in item))
    return join_line(line)

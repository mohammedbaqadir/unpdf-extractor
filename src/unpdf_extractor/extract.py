"""Region-first extraction from a profile.

Words never become page-wide phrases.  A profile field is a small box; only
words inside that box take part in the field, and lines are built inside the
box.  This is what keeps side-by-side panels from bleeding into each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .pipeline import clean, repair_arabic
from .profile import Field, LayoutProfile

ARABIC = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


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
    width, height = page_size
    x0, y0, x1, y1 = box.points(width, height)
    selected = []
    for word in words:
        if int(word.get("page", 0)) != page:
            continue
        x = (float(word["x0"]) + float(word["x1"])) / 2
        y = (float(word["top"]) + float(word["bottom"])) / 2
        if x0 <= x <= x1 and y0 <= y <= y1:
            selected.append(word)
    return selected


def group_lines(words: list[dict], tolerance: float = 4.0) -> list[list[dict]]:
    """Group words whose vertical midpoints overlap one visual line."""
    ordered = sorted(
        words,
        key=lambda word: (
            (float(word["top"]) + float(word["bottom"])) / 2,
            float(word["x0"]),
        ),
    )
    lines: list[list[dict]] = []
    for word in ordered:
        mid = (float(word["top"]) + float(word["bottom"])) / 2
        if not lines:
            lines.append([word])
            continue
        previous = lines[-1]
        previous_mid = sum(
            (float(item["top"]) + float(item["bottom"])) / 2 for item in previous
        ) / len(previous)
        if abs(mid - previous_mid) <= tolerance:
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
    text = " ".join(piece for piece in pieces if piece)
    return clean(re.sub(r"\s+", " ", text))


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
    method: str = "text",
) -> dict[str, FieldValue]:
    result: dict[str, FieldValue] = {}
    for field in profile.fields:
        if field.page < 1 or field.page > len(page_sizes):
            continue
        selected = words_in_box(words, field.page, field.box, page_sizes[field.page - 1])
        if not selected:
            continue
        value = _value_for(field, selected)
        if not value:
            continue
        result[field.name] = FieldValue(
            name=field.name,
            value=value,
            page=field.page,
            box=(
                field.box.left,
                field.box.top,
                field.box.right,
                field.box.bottom,
            ),
            method=method,
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


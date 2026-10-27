"""Draw help pages.

This module knows about typography, terminal width, and colour.  It does not
contain command-specific content; all of that lives in ``content.py``.
"""

from __future__ import annotations

import os
import shutil
import sys
import textwrap
from difflib import get_close_matches

from .content import (
    Page,
    all_page_names,
    command_page,
    overview,
    topic_names,
    topic_page,
    type_choice_page,
)


class Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def teal(self, text: str) -> str:
        return self._wrap("38;5;30", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)


def terminal_width(default: int = 88) -> int:
    try:
        columns = shutil.get_terminal_size((default, 24)).columns
    except OSError:
        columns = default
    return max(60, min(100, columns))


def color_enabled(no_color: bool = False) -> bool:
    if no_color or os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


def help_text(
    topic: str | None,
    profiles,
    *,
    width: int | None = None,
    color: bool | None = None,
    version: str = "",
) -> str | None:
    """Return the page for ``topic``, or None when the topic does not exist."""
    width = width or terminal_width()
    style = Style(color_enabled() if color is None else color)

    if topic == "all":
        pages = [overview(profiles)]
        pages.extend(_page(name, profiles) for name in all_page_names(profiles))
        rule = style.dim("-" * width)
        return f"\n{rule}\n".join(
            _render(page, style, width, version).rstrip() for page in pages if page
        )

    page = overview(profiles) if topic is None else _page(topic, profiles)
    if page is None:
        return None
    return _render(page, style, width, version)


def type_choice_text(profiles, *, width: int | None = None, color: bool | None = None) -> str:
    width = width or terminal_width()
    style = Style(color_enabled() if color is None else color)
    return _render(type_choice_page(profiles), style, width, "")


def unknown_topic_text(
    topic: str, profiles, *, width: int | None = None, color: bool | None = None
) -> str:
    style = Style(color_enabled() if color is None else color)
    names = list(topic_names(profiles))
    matches = get_close_matches(topic, names, n=3, cutoff=0.4)
    lines = [f"Unknown help topic {style.bold(repr(topic))}.", ""]
    if matches:
        lines.append("Did you mean:")
        lines.extend(f"  unpdf-extractor help {match}" for match in matches)
    else:
        lines.append("Run unpdf-extractor help to see every topic.")
    return "\n".join(lines)


def _page(topic: str, profiles) -> Page | None:
    return command_page(topic, profiles) or topic_page(topic, profiles)


def _render(page: Page, style: Style, width: int, version: str) -> str:
    title = style.bold(page.title)
    if version and page.title == "unpdf-extractor":
        title += " " + style.dim(version)
    lines = [title]
    if page.summary:
        lines.extend(_wrap(page.summary, width))

    if page.usage:
        lines.extend(("", style.bold("Usage")))
        lines.extend(f"  {line}" for line in page.usage)

    for section in page.sections:
        if section.title:
            lines.extend(("", style.bold(section.title)))
        for text in section.body:
            for part in str(text).splitlines():
                lines.extend(_wrap(part, width, subsequent="    ") if part else [""])
        if section.entries:
            lines.extend(_table([(entry.command, entry.summary) for entry in section.entries], style, width))

    if page.examples:
        lines.extend(("", style.bold("Examples")))
        for example in page.examples:
            lines.extend(_wrap(example, width))

    if page.options:
        lines.extend(("", style.bold("Options")))
        lines.extend(_table([(option.flag, option.summary) for option in page.options], style, width))

    return "\n".join(lines)


def _table(rows: list[tuple[str, str]], style: Style, width: int) -> list[str]:
    """Two aligned columns, or a stacked list on a narrow terminal."""
    if not rows:
        return []
    label_width = max(len(label) for label, _ in rows)
    if width < 72 or label_width > width // 2:
        lines = []
        for label, summary in rows:
            lines.append(f"  {style.teal(label)}")
            if summary:
                lines.extend(_wrap(summary, width, "    "))
        return lines

    lines = []
    for label, summary in rows:
        head = f"  {style.teal(label)}" + " " * (label_width - len(label) + 2)
        if not summary:
            lines.append(head.rstrip())
            continue
        wrapped = textwrap.wrap(
            summary,
            max(20, width - label_width - 4),
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.append(head + wrapped[0])
        lines.extend(" " * (label_width + 4) + line for line in wrapped[1:])
    return lines


def _wrap(
    text: str, width: int, indent: str = "  ", subsequent: str | None = None
) -> list[str]:
    return textwrap.wrap(
        text,
        max(20, width - len(indent)),
        initial_indent=indent,
        subsequent_indent=indent if subsequent is None else subsequent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [indent.rstrip()]

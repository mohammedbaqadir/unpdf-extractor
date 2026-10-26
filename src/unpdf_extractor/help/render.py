"""Draw the help pages.

This module knows about typography, terminal width, and color. It does not
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

    def green(self, text: str) -> str:
        return self._wrap("38;5;28", text)

    def amber(self, text: str) -> str:
        return self._wrap("38;5;130", text)

    def red(self, text: str) -> str:
        return self._wrap("38;5;124", text)


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
) -> str:
    width = width or terminal_width()
    style = Style(color_enabled() if color is None else color)

    if topic == "all":
        parts = [_render_page(overview(profiles), style, width, version)]
        for name in all_page_names(profiles):
            page = command_page(name, profiles) or topic_page(name, profiles)
            if page is not None:
                parts.append(_render_page(page, style, width, version))
        return _join(parts, width, style)

    if topic is None:
        return _render_page(overview(profiles), style, width, version)

    page = command_page(topic, profiles) or topic_page(topic, profiles)
    if page is not None:
        return _render_page(page, style, width, version)

    return unknown_topic(topic, profiles, style, width)


def missing_type_text(profiles, style: Style | None = None) -> str:
    style = style or Style(color_enabled())
    lines = ["Which document type?", ""]
    if not profiles:
        lines.extend(
            (
                "  No local profiles found.",
                "",
                "Try:",
                f"  {style.teal('unpdf-extractor pull NAME')}",
                f"  {style.teal('unpdf-profiler build NAME --samples .')}",
                f"  {style.teal('unpdf-profiler approve NAME')}",
            )
        )
        return "\n".join(lines)
    for profile in profiles:
        padding = " " * max(2, 10 - len(profile.flag))
        lines.append(f"  {style.bold(profile.flag)}{padding}{profile.display_name}")
    example = profiles[0].flag
    lines.extend(("", "Try:", f"  {style.teal(f'unpdf-extractor run {example} .')}"))
    return "\n".join(lines)


def unknown_topic(topic: str, profiles, style: Style, width: int) -> str:
    names = [*topic_names(profiles), "all"]
    matches = get_close_matches(topic, names, n=3, cutoff=0.35)
    lines = [f"I don't know the topic {style.bold(repr(topic))}.", ""]
    if matches:
        lines.append("Did you mean:")
        lines.extend(f"  unpdf-extractor help {match}" for match in matches)
    else:
        lines.append("Available topics:")
        lines.extend(f"  unpdf-extractor help {name}" for name in names)
    return "\n".join(lines)


def _join(parts: list[str], width: int, style: Style) -> str:
    rule = style.dim("-" * width)
    return f"\n{rule}\n".join(part.rstrip() for part in parts)


def _render_page(page: Page, style: Style, width: int, version: str) -> str:
    lines: list[str] = []
    title = style.bold(page.title)
    if version and page.title == "unpdf-extractor":
        title += " " + style.dim(version)
    lines.append(title)
    lines.append(style.teal(page.summary))
    if page.usage:
        lines.append("")
        lines.append(style.dim("Usage"))
        lines.append(f"  {page.usage}")

    lines.extend(_render_sections(page, style, width))

    if page.examples:
        lines.extend(("", style.bold("Examples")))
        for example in page.examples:
            lines.extend(_indented_lines(example, width, style))

    if page.options:
        lines.extend(("", style.bold("Options")))
        flag_width = min(max(len(option.flag) for option in page.options), max(12, width // 3))
        for option in page.options:
            if width < 72:
                lines.append(f"  {style.teal(option.flag)}")
                lines.extend(_wrap_indent(option.summary, width, "    "))
            else:
                head = (
                    f"  {style.teal(option.flag)}"
                    + " " * max(2, flag_width - len(option.flag) + 2)
                )
                body = textwrap.wrap(option.summary, max(20, width - flag_width - 4))
                if not body:
                    lines.append(head.rstrip())
                else:
                    lines.append(f"{head}{body[0]}")
                    for continuation in body[1:]:
                        lines.append(" " * (flag_width + 4) + continuation)

    if page.next_steps:
        lines.extend(("", style.bold("Next")))
        for step in page.next_steps:
            lines.append(f"  {style.teal(step)}")

    if page.footer:
        lines.extend(("", style.dim(page.footer)))

    return "\n".join(lines)


def _render_sections(page: Page, style: Style, width: int) -> list[str]:
    lines: list[str] = []
    for section in page.sections:
        lines.extend(("", style.bold(section.title)))
        for text in section.body:
            for part in str(text).splitlines():
                if not part:
                    lines.append("")
                else:
                    lines.extend(_indented_lines(part, width, style))
        if section.entries:
            cmd_width = min(max(len(entry.command) for entry in section.entries), max(20, width // 2))
            for entry in section.entries:
                if width < 70:
                    lines.append(f"  {style.teal(entry.command)}")
                    lines.extend(_wrap_indent(entry.summary, width, "    "))
                else:
                    head = (
                        f"  {style.teal(entry.command)}"
                        + " " * max(2, cmd_width - len(entry.command) + 2)
                    )
                    body = textwrap.wrap(entry.summary, max(20, width - cmd_width - 4))
                    if not body:
                        lines.append(head.rstrip())
                    else:
                        lines.append(f"{head}{body[0]}")
                        for continuation in body[1:]:
                            lines.append(" " * (cmd_width + 4) + continuation)
    return lines


def _indented_lines(text: str, width: int, style: Style) -> list[str]:
    return _wrap_indent(text, width, "  ")


def _wrap_indent(text: str, width: int, indent: str) -> list[str]:
    return [
        indent + line
        for line in textwrap.wrap(
            text,
            max(20, width - len(indent)),
            break_long_words=False,
            break_on_hyphens=False,
        )
    ] or [indent.rstrip()]

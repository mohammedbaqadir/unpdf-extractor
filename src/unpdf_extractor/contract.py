"""Runtime checks that a PDF is the document type a profile describes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .pipeline import repair_arabic
from .profile import LayoutProfile


def norm_token(text: str) -> str:
    return re.sub(r"[^\w]+", "", repair_arabic(text).lower(), flags=re.UNICODE)


@dataclass(frozen=True)
class ContractResult:
    ok: bool
    reason: str = ""
    page: int | None = None
    missing: tuple[str, ...] = ()
    details: tuple[str, ...] = field(default_factory=tuple)


def check_contract(
    profile: LayoutProfile,
    words: list[dict],
    page_sizes: list[tuple[float, float]],
) -> ContractResult:
    """Validate page count, page size, and required label anchors."""
    if len(page_sizes) != profile.page_count:
        return ContractResult(
            False,
            f"expected {profile.page_count} page(s), found {len(page_sizes)}",
        )

    details = []
    for page_no, (width, height) in enumerate(page_sizes, start=1):
        width_error = abs(width - profile.page_width) / profile.page_width
        height_error = abs(height - profile.page_height) / profile.page_height
        if width_error > profile.page_tolerance or height_error > profile.page_tolerance:
            return ContractResult(
                False,
                f"page {page_no} is {width:.0f}x{height:.0f}pt, "
                f"expected {profile.page_width:.0f}x{profile.page_height:.0f}pt",
                page=page_no,
            )
        details.append(f"page {page_no}: {width:.0f}x{height:.0f}pt")

    for anchor in profile.anchors:
        if not 1 <= anchor.page <= len(page_sizes):
            return ContractResult(
                False,
                f"anchor '{anchor.id}' refers to page {anchor.page}, but the document "
                f"has {len(page_sizes)} page(s)",
                page=anchor.page,
            )
        box = anchor.box
        tokens = {norm_token(token) for token in anchor.tokens if norm_token(token)}
        page_width, page_height = page_sizes[anchor.page - 1]
        found = set()
        for word in words:
            if int(word.get("page", 0)) != anchor.page:
                continue
            x = (float(word["x0"]) + float(word["x1"])) / 2 / page_width
            y = (float(word["top"]) + float(word["bottom"])) / 2 / page_height
            if not box.contains(x, y):
                continue
            value = norm_token(str(word.get("text", "")))
            for token in tokens:
                if value == token or token in value or value in token:
                    found.add(token)
        missing = sorted(tokens - found)
        if missing:
            return ContractResult(
                False,
                f"page {anchor.page} is missing anchor '{anchor.id}' "
                f"({', '.join(missing)})",
                page=anchor.page,
                missing=tuple(missing),
                details=tuple(details),
            )
        details.append(f"anchor {anchor.id}: ok")

    return ContractResult(True, details=tuple(details))

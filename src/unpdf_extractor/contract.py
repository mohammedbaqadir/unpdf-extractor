"""Runtime checks that a PDF is the document type a contract describes."""

from __future__ import annotations

from dataclasses import dataclass, field

from .extract import norm_text, repair_arabic, word_center
from .profile import LayoutProfile


def norm_token(text: str) -> str:
    """Normalize a token the same way the page text was normalized."""
    return norm_text(repair_arabic(text))


def tokens_match(value: str, token: str) -> bool:
    """Allow OCR to glue or drop a few letters at the edges of a label."""
    if not value or not token:
        return False
    if value == token:
        return True
    short, long = sorted((value, token), key=len)
    return len(short) >= 3 and short in long


@dataclass(frozen=True)
class ContractResult:
    ok: bool
    reason: str = ""
    page: int | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


def check_contract(
    contract: LayoutProfile,
    words: list[dict],
    page_sizes: list[tuple[float, float]],
) -> ContractResult:
    """Validate page count, page size, and required label anchors."""
    if len(page_sizes) != contract.page_count:
        return ContractResult(
            False,
            f"expected {contract.page_count} page(s), found {len(page_sizes)}",
        )

    details = []
    for page_no, (width, height) in enumerate(page_sizes, start=1):
        width_error = abs(width - contract.page_width) / contract.page_width
        height_error = abs(height - contract.page_height) / contract.page_height
        if width_error > contract.page_tolerance or height_error > contract.page_tolerance:
            return ContractResult(
                False,
                f"page {page_no} is {width:.0f}x{height:.0f}pt, "
                f"expected {contract.page_width:.0f}x{contract.page_height:.0f}pt",
                page=page_no,
            )
        details.append(f"page {page_no}: {width:.0f}x{height:.0f}pt")

    for anchor in contract.anchors:
        if not 1 <= anchor.page <= len(page_sizes):
            return ContractResult(
                False,
                f"anchor '{anchor.id}' refers to page {anchor.page}, but the document "
                f"has {len(page_sizes)} page(s)",
                page=anchor.page,
            )
        page_width, page_height = page_sizes[anchor.page - 1]
        tokens = {normed for normed in (norm_token(token) for token in anchor.tokens) if normed}
        found = set()
        for word in words:
            if int(word.get("page", 0)) != anchor.page:
                continue
            x, y = word_center(word)
            if not anchor.box.contains(x / page_width, y / page_height):
                continue
            value = norm_token(str(word.get("text", "")))
            found.update(token for token in tokens if tokens_match(value, token))
        missing = sorted(tokens - found)
        if missing:
            return ContractResult(
                False,
                f"page {anchor.page} is missing anchor '{anchor.id}' "
                f"({', '.join(missing)})",
                page=anchor.page,
                details=tuple(details),
            )
        details.append(f"anchor {anchor.id}: ok")

    return ContractResult(True, details=tuple(details))

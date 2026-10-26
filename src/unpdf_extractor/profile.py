"""Profile contract loading and validation.

A profile is data, not code.  It describes the pages a document type is
expected to have, the labels that prove the document type, and the boxes that hold
each value.  Runtime extraction only works against an approved profile.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UnpdfError

SCHEMA_VERSION = 3
MAX_PAGES = 100
MAX_ANCHORS = 200
MAX_FIELDS = 500
MAX_REGIONS = 100
MAX_TOLERANCE = 0.5


def _integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")
    return value


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("expected a finite number")
    return number


def _tokens(value) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of tokens")
    return tuple(
        token.strip() for token in value if isinstance(token, str) and token.strip()
    )


def _items(data: dict, key: str, limit: int) -> list:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise UnpdfError(f"Profile {key} must be a list.", exit_code=3)
    if len(value) > limit:
        raise UnpdfError(
            f"Profile cannot declare more than {limit} {key}.", exit_code=3
        )
    return value


@dataclass(frozen=True)
class Box:
    """Normalized page box: (left, top, right, bottom), each 0..1."""

    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_value(cls, value) -> "Box":
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            raise ValueError("box must contain four numbers")
        left, top, right, bottom = (float(item) for item in value)
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("box must be inside 0..1 and left<right, top<bottom")
        return cls(left, top, right, bottom)

    def points(self, width: float, height: float) -> tuple[float, float, float, float]:
        return (self.left * width, self.top * height, self.right * width, self.bottom * height)

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True)
class Anchor:
    id: str
    page: int
    box: Box
    tokens: tuple[str, ...]


@dataclass(frozen=True)
class Field:
    name: str
    page: int
    box: Box
    kind: str = "text"
    required: bool = False
    label: str = ""
    region: str = ""
    mode: str = "line"


@dataclass(frozen=True)
class Region:
    id: str
    page: int
    box: Box
    kind: str = "panel"


@dataclass
class LayoutProfile:
    name: str
    display_name: str
    version: str
    page_count: int
    page_width: float
    page_height: float
    page_tolerance: float
    anchors: tuple[Anchor, ...]
    fields: tuple[Field, ...]
    regions: tuple[Region, ...] = ()
    approved: bool = False
    path: Path | None = None
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        if self.path and self.path.exists():
            return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]
        payload = json.dumps(self.raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    @property
    def fields_by_name(self) -> dict[str, Field]:
        return {item.name: item for item in self.fields}

    @classmethod
    def load(cls, path: str | Path) -> "LayoutProfile":
        source = Path(path)
        if not source.exists():
            raise UnpdfError(f"Profile file not found: {source}", exit_code=3)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UnpdfError(f"Cannot read profile {source}: {exc}", exit_code=3) from exc
        return cls.from_dict(data, source)

    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> "LayoutProfile":
        if not isinstance(data, dict):
            raise UnpdfError("Profile must be a JSON object.", exit_code=3)
        if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
            raise UnpdfError(
                f"Unsupported profile schema version {data.get('schema_version')!r}; "
                f"expected {SCHEMA_VERSION}.",
                exit_code=3,
            )
        page = data.get("page")
        if not isinstance(page, dict):
            raise UnpdfError("Profile page block is incomplete.", exit_code=3)
        try:
            page_count = _integer(page["count"])
            page_width = _number(page["width"])
            page_height = _number(page["height"])
            tolerance = _number(page.get("tolerance", 0.02))
        except (KeyError, TypeError, ValueError) as exc:
            raise UnpdfError("Profile page block is incomplete.", exit_code=3) from exc
        if not 1 <= page_count <= MAX_PAGES:
            raise UnpdfError(
                f"Profile page count must be between 1 and {MAX_PAGES}.", exit_code=3
            )
        if page_width <= 0 or page_height <= 0:
            raise UnpdfError(
                "Profile page width and height must be positive.", exit_code=3
            )
        if not 0 <= tolerance <= MAX_TOLERANCE:
            raise UnpdfError(
                f"Profile page tolerance must be between 0 and {MAX_TOLERANCE}.",
                exit_code=3,
            )

        anchors = []
        anchor_ids = set()
        for item in _items(data, "anchors", MAX_ANCHORS):
            try:
                anchor = Anchor(
                    id=str(item["id"]).strip(),
                    page=_integer(item["page"]),
                    box=Box.from_value(item["box"]),
                    tokens=_tokens(item["tokens"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile anchor: {item!r}", exit_code=3) from exc
            if not anchor.id or anchor.id in anchor_ids:
                raise UnpdfError(
                    f"Duplicate or empty profile anchor id: {anchor.id!r}", exit_code=3
                )
            if not 1 <= anchor.page <= page_count:
                raise UnpdfError(
                    f"Profile anchor {anchor.id!r} page must be between 1 and {page_count}.",
                    exit_code=3,
                )
            if not anchor.tokens:
                raise UnpdfError(
                    f"Profile anchor {anchor.id!r} must declare at least one token.",
                    exit_code=3,
                )
            anchor_ids.add(anchor.id)
            anchors.append(anchor)

        fields = []
        field_names = set()
        for item in _items(data, "fields", MAX_FIELDS):
            try:
                field_item = Field(
                    name=str(item["name"]).strip(),
                    page=_integer(item["page"]),
                    box=Box.from_value(item["box"]),
                    kind=str(item.get("kind", "text")),
                    required=bool(item.get("required", False)),
                    label=str(item.get("label", "")),
                    region=str(item.get("region", "")),
                    mode=str(item.get("mode", "line")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile field: {item!r}", exit_code=3) from exc
            if not field_item.name or field_item.name in field_names:
                raise UnpdfError(
                    f"Duplicate or empty profile field: {field_item.name!r}", exit_code=3
                )
            if not 1 <= field_item.page <= page_count:
                raise UnpdfError(
                    f"Profile field {field_item.name!r} page must be between 1 and {page_count}.",
                    exit_code=3,
                )
            field_names.add(field_item.name)
            fields.append(field_item)

        regions = []
        region_ids = set()
        for item in _items(data, "regions", MAX_REGIONS):
            try:
                region = Region(
                    id=str(item["id"]).strip(),
                    page=_integer(item["page"]),
                    box=Box.from_value(item["box"]),
                    kind=str(item.get("kind", "panel")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile region: {item!r}", exit_code=3) from exc
            if not region.id or region.id in region_ids:
                raise UnpdfError(
                    f"Duplicate or empty profile region id: {region.id!r}", exit_code=3
                )
            if not 1 <= region.page <= page_count:
                raise UnpdfError(
                    f"Profile region {region.id!r} page must be between 1 and {page_count}.",
                    exit_code=3,
                )
            region_ids.add(region.id)
            regions.append(region)

        if not anchors:
            raise UnpdfError("Profile must declare at least one anchor.", exit_code=3)
        if not fields:
            raise UnpdfError("Profile must declare at least one field.", exit_code=3)

        return cls(
            name=str(data.get("name") or (path.parent.name if path else "profile")),
            display_name=str(data.get("display_name") or data.get("name") or "Profile"),
            version=str(data.get("version") or "0"),
            page_count=page_count,
            page_width=page_width,
            page_height=page_height,
            page_tolerance=tolerance,
            anchors=tuple(anchors),
            fields=tuple(fields),
            regions=tuple(regions),
            approved=bool(data.get("approved", False)),
            path=path,
            raw=data,
        )

    def require_approved(self) -> None:
        if not self.approved:
            raise UnpdfError(
                f"Profile '{self.name}' is not approved. Run `unpdf-profiler approve {self.name}` first.",
                exit_code=4,
            )

"""Profile contract loading and validation.

A profile is data, not code.  It describes the pages a document type is
expected to have, the labels that prove the document type, and the boxes that hold
each value.  Runtime extraction only works against an approved profile.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UnpdfError

SCHEMA_VERSION = 3


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
        page = data.get("page") or {}
        try:
            page_count = int(page["count"])
            page_width = float(page["width"])
            page_height = float(page["height"])
            tolerance = float(page.get("tolerance", 0.02))
        except (KeyError, TypeError, ValueError) as exc:
            raise UnpdfError("Profile page block is incomplete.", exit_code=3) from exc
        if page_count < 1 or page_width <= 0 or page_height <= 0:
            raise UnpdfError("Profile page values are invalid.", exit_code=3)

        anchors = []
        for item in data.get("anchors") or []:
            try:
                anchors.append(
                    Anchor(
                        id=str(item["id"]),
                        page=int(item["page"]),
                        box=Box.from_value(item["box"]),
                        tokens=tuple(str(token) for token in item["tokens"] if str(token).strip()),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile anchor: {item!r}", exit_code=3) from exc

        fields = []
        names = set()
        for item in data.get("fields") or []:
            try:
                field_item = Field(
                    name=str(item["name"]),
                    page=int(item["page"]),
                    box=Box.from_value(item["box"]),
                    kind=str(item.get("kind", "text")),
                    required=bool(item.get("required", False)),
                    label=str(item.get("label", "")),
                    region=str(item.get("region", "")),
                    mode=str(item.get("mode", "line")),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile field: {item!r}", exit_code=3) from exc
            if not field_item.name or field_item.name in names:
                raise UnpdfError(f"Duplicate or empty profile field: {field_item.name!r}", exit_code=3)
            names.add(field_item.name)
            fields.append(field_item)

        regions = []
        for item in data.get("regions") or []:
            try:
                regions.append(
                    Region(
                        id=str(item["id"]),
                        page=int(item["page"]),
                        box=Box.from_value(item["box"]),
                        kind=str(item.get("kind", "panel")),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile region: {item!r}", exit_code=3) from exc

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

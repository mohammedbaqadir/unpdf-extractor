"""Profile contract loading and validation.

A profile is data, not code.  It describes the pages a document type is
expected to have, the labels that prove the document type, and the boxes that
hold each value.  Runtime extraction only works against an approved profile.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import UnpdfError

SCHEMA_VERSION = 3
MIN_SUPPORTED_VERSION = 1
MAX_PAGES = 100
MAX_ANCHORS = 200
MAX_FIELDS = 500
MAX_TOLERANCE = 0.5

FIELD_KINDS = ("text", "digits", "number", "integer", "date")
FIELD_MODES = ("line", "multi")
FIELD_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_FIELD_NAMES = frozenset({"doc_id", "file", "format", "added_at"})


def _migrate_profile(data: dict) -> dict:
    """Migrate an older profile dict up to SCHEMA_VERSION in memory.

    Each step is a pure dict transform. The file on disk is never rewritten.
    Bump SCHEMA_VERSION only for a breaking format change, and add the
    matching step here so older profiles keep loading.
    """
    result = copy.deepcopy(data)
    # No migrations needed yet: versions 1..3 share the current shape.
    # Future steps look like:
    #   if version == 3 and SCHEMA_VERSION > 3:
    #       result.setdefault(...)  # apply the v3 -> v4 change
    #       result["schema_version"] = 4
    return result


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
    tokens = []
    for token in value:
        if not isinstance(token, str):
            raise ValueError("expected text tokens")
        text = token.strip()
        if text:
            tokens.append(text)
    return tuple(tokens)


def _items(data: dict, key: str, limit: int) -> list:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise UnpdfError(f"Profile {key} must be a list.", exit_code=3)
    if len(value) > limit:
        raise UnpdfError(f"Profile cannot declare more than {limit} {key}.", exit_code=3)
    return value


def _identity(kind: str, value: str, seen: set[str], page: int, page_count: int) -> str:
    if not value or value in seen:
        raise UnpdfError(f"Duplicate or empty profile {kind}: {value!r}", exit_code=3)
    if not 1 <= page <= page_count:
        raise UnpdfError(
            f"Profile {kind} {value!r} page must be between 1 and {page_count}.",
            exit_code=3,
        )
    seen.add(value)
    return value


def _choice(value: object, allowed: tuple[str, ...], key: str, name: str) -> str:
    text = str(value)
    if text not in allowed:
        raise UnpdfError(
            f"Profile field {name!r} has an unknown {key} {text!r}; "
            f"expected one of: {', '.join(allowed)}.",
            exit_code=3,
        )
    return text


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
        return (
            self.left * width,
            self.top * height,
            self.right * width,
            self.bottom * height,
        )

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
    mode: str = "line"
    fallback_box: Box | None = None

    @property
    def boxes(self) -> tuple[Box, ...]:
        """The boxes to try in order, ending with the fallback when declared."""
        if self.fallback_box is None:
            return (self.box,)
        return (self.box, self.fallback_box)


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
    approved: bool = False
    path: Path | None = None
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        if self.path and self.path.exists():
            return hashlib.sha256(self.path.read_bytes()).hexdigest()[:16]
        payload = json.dumps(self.raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

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
        schema_version = data.get("schema_version")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or not MIN_SUPPORTED_VERSION <= schema_version <= SCHEMA_VERSION
        ):
            if isinstance(schema_version, int) and not isinstance(schema_version, bool):
                if schema_version > SCHEMA_VERSION:
                    raise UnpdfError(
                        f"Profile schema version {schema_version!r} needs a newer "
                        f"extractor; this one supports up to {SCHEMA_VERSION}.",
                        exit_code=3,
                    )
            raise UnpdfError(
                f"Unsupported profile schema version {schema_version!r}; "
                f"expected {MIN_SUPPORTED_VERSION} to {SCHEMA_VERSION}.",
                exit_code=3,
            )
        if schema_version < SCHEMA_VERSION:
            data = _migrate_profile(data)
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
            raise UnpdfError("Profile page width and height must be positive.", exit_code=3)
        if not 0 <= tolerance <= MAX_TOLERANCE:
            raise UnpdfError(
                f"Profile page tolerance must be between 0 and {MAX_TOLERANCE}.",
                exit_code=3,
            )

        anchors = []
        anchor_ids: set[str] = set()
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
            _identity("anchor", anchor.id, anchor_ids, anchor.page, page_count)
            if not anchor.tokens:
                raise UnpdfError(
                    f"Profile anchor {anchor.id!r} must declare at least one token.",
                    exit_code=3,
                )
            anchors.append(anchor)

        fields = []
        field_names: set[str] = set()
        for item in _items(data, "fields", MAX_FIELDS):
            try:
                name = str(item["name"]).strip()
                box = item["box"]
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile field: {item!r}", exit_code=3) from exc
            if not FIELD_NAME_RE.fullmatch(name):
                raise UnpdfError(
                    f"Profile field name {name!r} must be lowercase snake_case "
                    "(^[a-z][a-z0-9_]*$).",
                    exit_code=3,
                )
            if name in RESERVED_FIELD_NAMES:
                raise UnpdfError(
                    f"Profile field name {name!r} is reserved (doc_id, file, "
                    "format, added_at).",
                    exit_code=3,
                )
            if "required" in item and not isinstance(item["required"], bool):
                raise UnpdfError(
                    f"Profile field {name!r} required must be a boolean.",
                    exit_code=3,
                )
            try:
                field_item = Field(
                    name=name,
                    page=_integer(item["page"]),
                    box=Box.from_value(box),
                    kind=_choice(item.get("kind", "text"), FIELD_KINDS, "kind", name),
                    required=bool(item.get("required", False)),
                    mode=_choice(item.get("mode", "line"), FIELD_MODES, "mode", name),
                    fallback_box=(
                        Box.from_value(item["fallback_box"])
                        if item.get("fallback_box") is not None
                        else None
                    ),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise UnpdfError(f"Invalid profile field: {item!r}", exit_code=3) from exc
            _identity("field", field_item.name, field_names, field_item.page, page_count)
            fields.append(field_item)

        if not anchors:
            raise UnpdfError("Profile must declare at least one anchor.", exit_code=3)
        if not fields:
            raise UnpdfError("Profile must declare at least one field.", exit_code=3)

        family = data.get("family")
        if family is not None:
            if not isinstance(family, str) or not re.fullmatch(
                r"[a-z][a-z0-9-]*", family.strip()
            ):
                raise UnpdfError(
                    "Profile family must be lowercase letters, digits, and "
                    "hyphens, starting with a letter.",
                    exit_code=3,
                )
        match = data.get("match")
        if match is not None:
            if not isinstance(match, dict):
                raise UnpdfError("Profile match must be an object.", exit_code=3)
            match_field = str(match.get("field") or "").strip()
            if not match_field:
                raise UnpdfError("Profile match.field is required.", exit_code=3)
            if match_field not in field_names:
                raise UnpdfError(
                    f"Profile match.field {match_field!r} is not a declared field.",
                    exit_code=3,
                )
            contains = match.get("contains_any")
            if (
                not isinstance(contains, list)
                or not contains
                or any(not str(item).strip() for item in contains)
            ):
                raise UnpdfError(
                    "Profile match.contains_any must contain at least one value.",
                    exit_code=3,
                )

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
            approved=bool(data.get("approved", False)),
            path=path,
            raw=data,
        )

    def require_approved(self) -> None:
        if not self.approved:
            raise UnpdfError(
                f"Profile '{self.name}' is not approved. "
                "Only approved profiles are accepted; see: unpdf-extractor help profiles",
                exit_code=4,
            )

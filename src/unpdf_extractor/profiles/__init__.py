"""Profile discovery.

Profiles are ordinary folders under ``profiles/`` (or ``UNPDF_PROFILES``):

    profiles/<name>/profile.json

No document type is built in.  Adding a profile adds a CLI flag automatically.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..errors import UnpdfError
from .base import DocumentProfile

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class FileProfile(DocumentProfile):
    """A profile loaded from a JSON file on disk."""

    def __init__(self, path: Path, name: str | None = None) -> None:
        self.name = name or path.parent.name
        self.display_name = self.name
        self.summary = f"Profile loaded from {path}."
        self.db_name = f"{self.name}.db"
        self.work_name = ".unpdf"
        self.profile_path = path
        self.help_about = (
            f"Read the {self.name} profile contract and extract its declared fields."
        )
        self.help_checks = (
            "page count, page size, and required label anchors",
            "required profile fields",
            "field kinds declared by the profile",
        )


def profiles_root() -> Path:
    """Return the directory that holds profile packages."""
    configured = os.environ.get("UNPDF_PROFILES")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "profiles").resolve()


def profile_dir(name: str) -> Path:
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid profile name: {name!r}")
    return profiles_root() / name


def _discover() -> dict[str, object]:
    found: dict[str, object] = {}
    root = profiles_root()
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            path = folder / "profile.json"
            if _NAME_RE.fullmatch(folder.name) and path.is_file():
                found[folder.name] = lambda path=path: FileProfile(path)
    from .. import registry

    for name, path in registry.cached_profile_paths().items():
        found.setdefault(name, lambda path=path, name=name: FileProfile(path, name))
    return found


def all_profiles() -> tuple[DocumentProfile, ...]:
    """Return every discovered profile instance, sorted by name."""
    found = _discover()
    return tuple(found[name]() for name in sorted(found))


def get_profile(name: str) -> DocumentProfile:
    """Return one profile, downloading it from the registry when needed."""
    found = _discover()
    if name in found:
        return found[name]()

    from .. import registry

    cached = registry.cached_profile(name)
    if cached is not None:
        return FileProfile(cached, name=name)
    if registry.load_credentials() is not None:
        fetched = registry.fetch_profile(name)
        return FileProfile(fetched["path"], name=name)

    known = ", ".join(sorted(found)) or "none"
    raise UnpdfError(
        f"Unknown profile '{name}'. Available: {known}. "
        "Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN to download it, or build one "
        "with: unpdf-profiler build NAME --samples FOLDER",
        exit_code=1,
    )


def all_families() -> tuple[str, ...]:
    """Return approved family names declared by profile metadata."""
    import json

    families: set[str] = set()
    for profile in all_profiles():
        try:
            data = json.loads(profile.profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        family = str(data.get("family", "")).strip()
        if family and data.get("approved"):
            families.add(family)
    return tuple(sorted(families))


def family_profiles(family: str) -> tuple[DocumentProfile, ...]:
    """Return approved profiles that declare the same family.

    A complete local or cached family is used without a network call. When the
    family is missing members and the registry is configured, it is downloaded.
    """
    members = _family_members(family)
    if len(members) >= 2:
        return members

    from .. import registry

    if registry.load_credentials() is None:
        return members
    for name in registry.family_members(family):
        registry.fetch_profile(name)
    return _family_members(family)


def _family_members(family: str) -> tuple[DocumentProfile, ...]:
    import json

    members = []
    for profile in all_profiles():
        try:
            data = json.loads(profile.profile_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(data.get("family", "")) == family and data.get("approved"):
            members.append(profile)
    return tuple(members)

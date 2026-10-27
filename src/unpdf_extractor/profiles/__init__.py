"""Profile discovery.

A profile is a folder with ``profile.json``.  Sources, in order:

1. ``$UNPDF_PROFILES`` or ``./profiles`` -- the folder you run the tool in.
2. The registry cache -- the newest downloaded version per name.

Profiles are data, never code: adding one adds no CLI flag and no branch.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import UnpdfError

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class Profile:
    """A discovered profile: a name and the JSON contract that defines it."""

    name: str
    path: Path

    @property
    def db_name(self) -> str:
        return f"{self.name}.db"


def profiles_root() -> Path:
    """Return the folder that holds local profile packages."""
    configured = os.environ.get("UNPDF_PROFILES")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.cwd() / "profiles").resolve()


def profile_dir(name: str) -> Path:
    """Return the folder for one profile name, rejecting unsafe names."""
    if not _NAME_RE.fullmatch(name):
        raise ValueError(f"Invalid profile name: {name!r}")
    return profiles_root() / name


def _discover() -> dict[str, Profile]:
    found: dict[str, Profile] = {}
    root = profiles_root()
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            path = folder / "profile.json"
            if _NAME_RE.fullmatch(folder.name) and path.is_file():
                found[folder.name] = Profile(folder.name, path)

    from .. import registry

    for name, path in registry.cached_profile_paths().items():
        found.setdefault(name, Profile(name, path))
    return found


def all_profiles() -> tuple[Profile, ...]:
    """Every discovered profile, sorted by name."""
    found = _discover()
    return tuple(found[name] for name in sorted(found))


def get_profile(name: str) -> Profile:
    """Return one profile, downloading it from the registry when needed."""
    found = _discover()
    if name in found:
        return found[name]

    from .. import registry

    if registry.load_credentials() is not None:
        fetched = registry.fetch_profile(name)
        return Profile(name, fetched["path"])

    known = ", ".join(sorted(found)) or "none"
    raise UnpdfError(
        f"Unknown profile '{name}'. Available: {known}. "
        "Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN to download it.",
        exit_code=1,
    )


def profile_meta(profile: Profile) -> dict:
    """The raw JSON of one profile, or an empty dict when it cannot be read."""
    try:
        data = json.loads(profile.path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def all_families() -> tuple[str, ...]:
    """Family names declared by at least one approved profile."""
    families = set()
    for profile in all_profiles():
        data = profile_meta(profile)
        family = str(data.get("family") or "").strip()
        if family and data.get("approved"):
            families.add(family)
    return tuple(sorted(families))


def family_profiles(family: str) -> tuple[Profile, ...]:
    """Return the approved profiles in one family, completing it if possible.

    The registry knows the complete membership; the local cache may not.  When
    credentials exist the registry is asked once so a partly cached family is
    never silently treated as complete.  A failed registry call falls back to
    what is already local.
    """
    members = _family_members(family)
    from .. import registry

    if registry.load_credentials() is not None:
        try:
            expected = registry.family_members(family)
        except UnpdfError:
            if not members:
                raise
            expected = []
        known = {profile.name for profile in members}
        for name in expected:
            if name not in known:
                registry.fetch_profile(name)
        members = _family_members(family)

    if len(members) < 2:
        raise UnpdfError(
            f"Family '{family}' has {len(members)} approved profile(s); a family needs at least two. "
            "Run: unpdf-extractor pull NAME",
            exit_code=1,
        )
    return members


def _family_members(family: str) -> tuple[Profile, ...]:
    members = []
    for profile in all_profiles():
        data = profile_meta(profile)
        if str(data.get("family") or "").strip() == family and data.get("approved"):
            members.append(profile)
    return tuple(members)

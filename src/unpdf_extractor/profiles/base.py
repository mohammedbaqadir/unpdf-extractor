"""The small contract every profile instance exposes to the core."""

from __future__ import annotations

from pathlib import Path


class DocumentProfile:
    """A named profile package loaded from ``profiles/<name>/profile.json``."""

    name: str = ""
    display_name: str = ""
    summary: str = ""
    db_name: str = ""
    work_name: str = ".unpdf"
    profile_path: Path = Path()
    help_about: str = ""
    help_checks: tuple[str, ...] = ()

    @property
    def flag(self) -> str:
        return f"--{self.name}"

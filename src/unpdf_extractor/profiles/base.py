"""The small contract every profile instance exposes to the core."""

from __future__ import annotations

import sqlite3
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

    def ensure(self, conn: sqlite3.Connection) -> None:
        """Optional profile-specific schema hook; generic profiles use core tables."""

    def write_document(self, conn: sqlite3.Connection, doc_id: int, out_dir: Path) -> None:
        """Optional profile-specific canonical hook."""

    def rebuild(self, conn: sqlite3.Connection, out_dir: Path) -> dict:
        """Optional profile-specific canonical rebuild hook."""
        row = conn.execute(
            "SELECT COUNT(*) FROM docs WHERE format = ?", (self.name,)
        ).fetchone()
        return {"documents": int(row[0]) if row else 0}

    def refresh(self, conn: sqlite3.Connection) -> None:
        """Optional profile-specific refresh hook."""

    def prune(self, conn: sqlite3.Connection) -> None:
        """Optional profile-specific cleanup hook."""

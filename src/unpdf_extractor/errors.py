"""Errors that the CLI knows how to translate into exit codes."""

from __future__ import annotations


class UnpdfError(Exception):
    """A user-facing failure with an explicit process exit code."""

    def __init__(self, message: str, exit_code: int = 3) -> None:
        super().__init__(message)
        self.exit_code = exit_code

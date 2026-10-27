"""The `unpdf-extractor` command line interface."""

from __future__ import annotations

import argparse
import sys

from .errors import UnpdfError
from .help import (
    color_enabled,
    help_text,
    terminal_width,
    type_choice_text,
    unknown_topic_text,
)
from .profiles import all_profiles
from .version import __version__


class HelpAction(argparse.Action):
    """Print a help page instead of argparse's generated text."""

    def __init__(self, option_strings, dest, *, profiles, color, topic=None, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self.profiles = profiles
        self.color = color
        self.topic = topic

    def __call__(self, parser, namespace, values, option_string=None):
        print(
            help_text(
                self.topic,
                self.profiles,
                width=terminal_width(),
                color=self.color,
                version=__version__,
            )
        )
        parser.exit(0)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse defaults to exit 2, but 2 already means "review needed".
        if self.usage:
            print(f"usage: {self.usage}", file=sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        print("Try: unpdf-extractor help", file=sys.stderr)
        raise SystemExit(1)


def build_parser(profiles, color: bool) -> Parser:
    parser = Parser(
        prog="unpdf-extractor",
        add_help=False,
        usage="unpdf-extractor COMMAND [options]",
    )
    parser.add_argument("--version", action="version", version=f"unpdf-extractor {__version__}")
    parser.add_argument(
        "-h", "--help", action=HelpAction, profiles=profiles, color=color
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    def selection_command(name: str, usage: str, *, work: bool = True) -> None:
        command = commands.add_parser(name, add_help=False, usage=usage)
        command.add_argument("folder", nargs="?", default=".", metavar="folder")
        group = command.add_mutually_exclusive_group()
        group.add_argument("--type", dest="profile", metavar="NAME")
        group.add_argument("--family", metavar="NAME")
        command.add_argument("--db", metavar="PATH")
        if work:
            command.add_argument("--work", metavar="PATH")
        command.add_argument(
            "-h", "--help", action=HelpAction, profiles=profiles, color=color, topic=name
        )

    selection_command(
        "run",
        "unpdf-extractor run [folder] (--type NAME | --family NAME) [options]",
    )
    selection_command(
        "check",
        "unpdf-extractor check [folder] (--type NAME | --family NAME) [options]",
        work=False,
    )

    pull = commands.add_parser(
        "pull", add_help=False, usage="unpdf-extractor pull NAME [--version VERSION]"
    )
    pull.add_argument("profile", metavar="NAME")
    pull.add_argument("--version", metavar="VERSION")
    pull.add_argument(
        "-h", "--help", action=HelpAction, profiles=profiles, color=color, topic="pull"
    )

    help_page = commands.add_parser(
        "help", add_help=False, usage="unpdf-extractor help [TOPIC]"
    )
    help_page.add_argument("topic", nargs="?", metavar="TOPIC")
    help_page.add_argument(
        "-h", "--help", action=HelpAction, profiles=profiles, color=color, topic="help"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    arguments = list(sys.argv[1:] if argv is None else argv)
    color = color_enabled("--no-color" in arguments)
    arguments = [item for item in arguments if item != "--no-color"]

    profiles = all_profiles()
    parser = build_parser(profiles, color)
    args = parser.parse_args(arguments)

    if args.command is None:
        print(_page(None, profiles, color))
        return 0

    if args.command == "help":
        if args.topic is None:
            print(_page(None, profiles, color))
            return 0
        text = help_text(
            args.topic, profiles, width=terminal_width(), color=color, version=__version__
        )
        if text is None:
            print(unknown_topic_text(args.topic, profiles, color=color), file=sys.stderr)
            return 1
        print(text)
        return 0

    if args.command == "pull":
        return _pull(args.profile, args.version)

    if not args.profile and not args.family:
        print(type_choice_text(profiles, color=color), file=sys.stderr)
        return 1

    from . import api

    try:
        job = api.family_job(args.family) if args.family else api.type_job(args.profile)
        if args.command == "run":
            summary = api.run(job, args.folder, args.db, args.work)
        else:
            summary = api.check(job, args.folder, args.db)
    except UnpdfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    if args.command == "check" and summary.documents == 0:
        print(f"No documents for {job.name} in this database.", file=sys.stderr)
        return 1
    _print_summary(summary)
    return summary.exit_code


def _page(topic: str | None, profiles, color: bool) -> str:
    return (
        help_text(
            topic, profiles, width=terminal_width(), color=color, version=__version__
        )
        or ""
    )


def _pull(name: str, version: str | None) -> int:
    from . import registry

    try:
        result = registry.fetch_profile(name, version)
    except UnpdfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    print(f"cached {result['name']} {result['version']}")
    print(f"sha256 {result['sha256']}")
    print(f"profile {result['path']}")
    return 0


def _print_summary(summary) -> None:
    if summary.added or summary.skipped or summary.failed:
        print(
            f"\nrun: {summary.added} added, {summary.skipped} skipped, {summary.failed} failed"
        )
    print(
        f"database: {summary.documents} document(s) | "
        f"{summary.accepted} accepted, {summary.review} review, "
        f"{summary.missing} missing (optional)"
    )
    if summary.quarantined:
        print(f"\nquarantined: {summary.quarantined} file(s)")
        _print_rows(summary.quarantine_rows, "query the quarantine table")
    if summary.review:
        print("\nreview queue:")
        _print_rows(summary.review_rows, "query the review view")


def _print_rows(rows, hint: str) -> None:
    for row in rows[:20]:
        print("  " + " | ".join(row))
    if len(rows) > 20:
        print(f"  ... and {len(rows) - 20} more; {hint}")


if __name__ == "__main__":
    raise SystemExit(main())

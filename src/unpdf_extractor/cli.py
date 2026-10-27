"""The `unpdf-extractor` command line interface."""

from __future__ import annotations

import argparse
import sys

from .errors import UnpdfError
from .profiles import all_families, all_profiles, get_profile
from .version import __version__

from .help import color_enabled, help_text, missing_type_text, terminal_width
from .help.render import Style


class HelpAction(argparse.Action):
    def __init__(self, option_strings, dest, *, profiles, topic=None, **kwargs):
        super().__init__(option_strings, dest, nargs=0, **kwargs)
        self.profiles = profiles
        self.topic = topic

    def __call__(self, parser, namespace, values, option_string=None):
        no_color = "--no-color" in sys.argv
        print(
            help_text(
                self.topic,
                self.profiles,
                width=terminal_width(),
                color=color_enabled(no_color),
                version=__version__,
            )
        )
        parser.exit(0)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        print(f"error: {message}", file=sys.stderr)
        print("Try: unpdf-extractor --help", file=sys.stderr)
        raise SystemExit(1)


def build_parser(profiles) -> Parser:
    parser = Parser(
        prog="unpdf-extractor",
        add_help=False,
        description="Extract approved profile fields from PDFs into SQLite.",
    )
    parser.add_argument("--version", action="version", version=f"unpdf-extractor {__version__}")
    parser.add_argument("--no-color", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "-h",
        "--help",
        action=HelpAction,
        profiles=profiles,
        help=argparse.SUPPRESS,
    )
    sub = parser.add_subparsers(dest="command")

    def add_common(command_parser, topic):
        command_parser.add_argument("folder", nargs="?", default=".", help=argparse.SUPPRESS)
        group = command_parser.add_mutually_exclusive_group()
        group.add_argument("--type", dest="profile")
        group.add_argument("--family", dest="family", metavar="NAME")
        for profile in profiles:
            group.add_argument(
                profile.flag,
                action="store_const",
                const=profile.name,
                dest="profile",
                help=argparse.SUPPRESS,
            )
        profile_names = {profile.name for profile in profiles}
        for family in all_families():
            if family not in profile_names:
                group.add_argument(
                    f"--{family}",
                    action="store_const",
                    const=family,
                    dest="family",
                    help=argparse.SUPPRESS,
                )
        command_parser.add_argument("--db", help=argparse.SUPPRESS)
        command_parser.add_argument("--work", help=argparse.SUPPRESS)
        command_parser.add_argument(
            "--no-color", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
        )
        command_parser.add_argument(
            "-h",
            "--help",
            action=HelpAction,
            profiles=profiles,
            topic=topic,
            help=argparse.SUPPRESS,
        )

    run_parser = sub.add_parser("run", add_help=False, help=argparse.SUPPRESS)
    add_common(run_parser, "run")
    check_parser = sub.add_parser("check", add_help=False, help=argparse.SUPPRESS)
    add_common(check_parser, "check")

    pull_parser = sub.add_parser("pull", add_help=False, help=argparse.SUPPRESS)
    pull_parser.add_argument("profile")
    pull_parser.add_argument("--version")
    pull_parser.add_argument("--no-color", action="store_true", default=argparse.SUPPRESS)
    pull_parser.add_argument(
        "-h",
        "--help",
        action=HelpAction,
        profiles=profiles,
        topic="pull",
        help=argparse.SUPPRESS,
    )

    help_parser = sub.add_parser("help", add_help=False, help=argparse.SUPPRESS)
    help_parser.add_argument("topic", nargs="?", help=argparse.SUPPRESS)
    help_parser.add_argument(
        "--no-color", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    help_parser.add_argument(
        "-h",
        "--help",
        action=HelpAction,
        profiles=profiles,
        topic="help",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    profiles = all_profiles()
    parser = build_parser(profiles)
    args = parser.parse_args(argv)

    if args.command is None:
        print(
            help_text(
                None,
                profiles,
                width=terminal_width(),
                color=color_enabled("--no-color" in (argv or sys.argv)),
                version=__version__,
            )
        )
        return 0

    no_color = bool(getattr(args, "no_color", False) or "--no-color" in (argv or sys.argv))
    if args.command == "help":
        if args.topic is None:
            print(
                help_text(
                    None,
                    profiles,
                    width=terminal_width(),
                    color=color_enabled(no_color),
                    version=__version__,
                )
            )
            return 0
        print(
            help_text(
                args.topic,
                profiles,
                width=terminal_width(),
                color=color_enabled(no_color),
                version=__version__,
            )
        )
        return 0

    if args.command == "pull":
        from . import registry

        try:
            result = registry.fetch_profile(args.profile, args.version)
        except UnpdfError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return exc.exit_code
        print(f"cached {result['name']} {result['version']}")
        print(f"sha256 {result['sha256']}")
        print(f"profile {result['path']}")
        return 0

    profile_name = getattr(args, "profile", None)
    family_name = getattr(args, "family", None)
    if not profile_name and not family_name:
        style = Style(color_enabled(no_color))
        print(missing_type_text(profiles, style))
        return 1

    from . import api

    try:
        if family_name:
            if args.command == "run":
                summary = api.run_family(family_name, args.folder, args.db, args.work)
            elif args.command == "check":
                summary = api.check_family(family_name, args.folder, args.db, args.work)
            else:
                parser.error(f"unknown command: {args.command}")
                return 1
        else:
            profile = get_profile(profile_name)
            if args.command == "run":
                summary = api.run_folder(profile, args.folder, args.db, args.work)
            elif args.command == "check":
                summary = api.check_database(profile, args.folder, args.db, args.work)
            else:
                parser.error(f"unknown command: {args.command}")
                return 1
    except UnpdfError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code

    if args.command == "check" and summary.documents == 0:
        print("No documents in the database.", file=sys.stderr)
        return 1
    _print_summary(summary)
    return summary.exit_code


def _print_summary(summary) -> None:
    if summary.added or summary.skipped:
        print(f"run: {summary.added} added, {summary.skipped} skipped")
    print(
        f"\nvalidation: {summary.documents} document(s) | "
        f"{summary.accepted} accepted, {summary.review} review, "
        f"{summary.missing} missing (optional)"
    )
    if summary.quarantined:
        print(f"\nquarantined: {summary.quarantined} file(s)")
        for filename, reason in summary.quarantine_rows[:20]:
            print(f"  {filename} | {reason}")
        if len(summary.quarantine_rows) > 20:
            print(f"  ... and {len(summary.quarantine_rows) - 20} more; query the `quarantine` table")
    if summary.review:
        print("\nreview queue:")
        for filename, field, reason in summary.review_rows[:20]:
            print(f"  {filename} | {field} | {reason}")
        if len(summary.review_rows) > 20:
            print(f"  ... and {len(summary.review_rows) - 20} more; query the `review` view")


if __name__ == "__main__":
    raise SystemExit(main())

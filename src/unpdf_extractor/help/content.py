"""The content of `unpdf-extractor help`, kept separate from how it is drawn."""

from __future__ import annotations

from dataclasses import dataclass

from unpdf_core.profiles import all_families


@dataclass(frozen=True)
class Entry:
    command: str
    summary: str = ""


@dataclass(frozen=True)
class Option:
    flag: str
    summary: str = ""


@dataclass(frozen=True)
class Section:
    title: str
    body: tuple[str, ...] = ()
    entries: tuple[Entry, ...] = ()


@dataclass(frozen=True)
class Page:
    title: str
    summary: str
    usage: str = ""
    sections: tuple[Section, ...] = ()
    examples: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()
    next_steps: tuple[str, ...] = ()
    footer: str = ""


def profile_entries(profiles) -> tuple[Entry, ...]:
    return tuple(Entry(profile.flag, profile.display_name) for profile in profiles)


def family_entries() -> tuple[Entry, ...]:
    return tuple(
        Entry(f"--{family}", f"{family} (content-routed family)")
        for family in all_families()
    )


def type_options(profiles) -> tuple[Option, ...]:
    names = ", ".join(profile.name for profile in profiles) or "none discovered"
    options = [Option("--type NAME", f"select a profile; available: {names}")]
    options.extend(Option(profile.flag, f"{profile.display_name} (shortcut)") for profile in profiles)
    options.extend(
        Option(f"--{family}", f"{family} family (content-routed)")
        for family in all_families()
    )
    return tuple(options)


def common_options(profiles) -> tuple[Option, ...]:
    return (
        Option("[folder]", "PDF folder; defaults to the current folder"),
        *type_options(profiles),
        Option("--db PATH", "database file; defaults to <profile>.db"),
        Option("--work PATH", "artifact folder; defaults to .unpdf/<profile>"),
        Option("--no-color", "plain text output"),
    )


def _primary(profiles) -> str:
    return profiles[0].flag if profiles else "--forms"


def _db_name(profiles) -> str:
    return profiles[0].db_name if profiles else "forms.db"


def overview(profiles) -> Page:
    primary = _primary(profiles)
    entries = profile_entries(profiles) + family_entries()
    if entries:
        start = (
            Entry(f"unpdf-extractor run {primary} .", "read the PDFs in this folder"),
            Entry(f"unpdf-extractor check {primary} .", "re-check an existing database"),
            Entry(f"unpdf-extractor rebuild {primary} .", "rebuild generic output from stored fields"),
        )
    else:
        start = (
            Entry("unpdf-profiler build forms --samples .", "create the first profile"),
            Entry("unpdf-profiler approve forms", "approve the generated contract"),
        )
    return Page(
        title="unpdf-extractor",
        summary="Profile-driven PDF extraction into a validation-checked SQLite database.",
        sections=(
            Section("Document types", entries=entries),
            Section("Start here", entries=start),
            Section(
                "You get",
                body=(
                    f"{_db_name(profiles)}  - SQLite database",
                    ".unpdf/<profile>/ - profile snapshot and extraction evidence",
                    "No document type is built in; profiles come from profiles/<name>/.",
                ),
            ),
            Section(
                "More help",
                entries=(
                    Entry("unpdf-extractor help profiles", "how profiles are discovered"),
                    Entry("unpdf-profiler help", "build and approve a profile"),
                    Entry("unpdf-extractor help extraction", "how a PDF becomes fields"),
                    Entry("unpdf-extractor help review", "why a field is flagged"),
                    Entry("unpdf-extractor help contract", "why a document is quarantined"),
                    Entry("unpdf-extractor help exit-codes", "what 0 / 1 / 2 / 3 / 4 mean"),
                    Entry("unpdf-extractor help all", "full reference"),
                ),
            ),
        ),
        footer="Runtime is local. No LLM or network call is made.",
    )


def command_page(name: str, profiles) -> Page | None:
    primary = _primary(profiles)
    options = common_options(profiles)
    if name == "run":
        return Page(
            title="unpdf-extractor run",
            summary="Read PDFs, extract the selected profile, validate fields, and write SQLite.",
            usage=f"unpdf-extractor run {primary} [folder] [options]",
            sections=(
                Section(
                    "What happens",
                    body=(
                        "1. Find PDFs in the folder (default: current folder).",
                        "2. Read the text layer or run local Tesseract OCR.",
                        "3. Check page count, page size, and required label anchors.",
                        "4. Extract words inside each declared field box.",
                        "5. Validate fields, write the database, and report quarantine/review.",
                    ),
                ),
                Section(
                    "What it leaves behind",
                    body=(
                        f"{_db_name(profiles)}  - the queryable database",
                        ".unpdf/<profile>/ - profile snapshot and extraction evidence",
                        "The PDFs are never moved or modified.",
                    ),
                ),
            ),
            examples=(
                f"unpdf-extractor run {primary} .",
                f"unpdf-extractor run {primary} D:\\docs\\forms",
                f"unpdf-extractor run {primary} D:\\docs\\forms --db D:\\db\\forms.db",
            ),
            options=options,
            next_steps=(f"unpdf-extractor check {primary} .", "unpdf-extractor help review"),
            footer="Exit: 0 clean | 2 review | 3 failed | 4 profile mismatch | 1 usage/no input",
        )
    if name == "check":
        return Page(
            title="unpdf-extractor check",
            summary="Re-run field rules against an existing database without reading the PDFs.",
            usage=f"unpdf-extractor check {primary} [folder] [options]",
            sections=(
                Section(
                    "Use this when",
                    body=(
                        "You changed a profile rule or want to re-check stored values.",
                        "It needs an existing database and does not extract PDFs.",
                    ),
                ),
            ),
            examples=(f"unpdf-extractor check {primary} .",),
            options=options,
            next_steps=(f"unpdf-extractor run {primary} .", "unpdf-extractor help review"),
            footer="Exit: 0 clean | 2 review | 1 no database",
        )
    if name == "rebuild":
        return Page(
            title="unpdf-extractor rebuild",
            summary="Rebuild generic output from extracted field rows already stored in the database.",
            usage=f"unpdf-extractor rebuild {primary} [folder] [options]",
            sections=(
                Section(
                    "When to use it",
                    body=(
                        "The generic output or profile metadata changed.",
                        "The source of truth is extracted_fields; the PDFs are not read again.",
                    ),
                ),
            ),
            examples=(f"unpdf-extractor rebuild {primary} .",),
            options=options,
            next_steps=(f"unpdf-extractor check {primary} .", "unpdf-extractor help extraction"),
            footer="Exit: 0 clean | 2 review | 1 no database",
        )
    if name == "help":
        return Page(
            title="unpdf-extractor help",
            summary="Find the next useful command or concept.",
            usage="unpdf-extractor help [topic]",
            examples=("unpdf-extractor help", "unpdf-extractor help run", "unpdf-profiler help", "unpdf-extractor help all"),
            options=(Option("--no-color", "plain text output"),),
            next_steps=(f"unpdf-extractor run {primary} .",),
        )
    return None


def topic_page(name: str, profiles) -> Page | None:
    profile = next((item for item in profiles if item.name == name), None)
    if profile is not None:
        checks = "\n".join(f"- {item}" for item in profile.help_checks)
        return Page(
            title=profile.display_name,
            summary=profile.summary,
            sections=(
                Section("What it reads", body=(profile.help_about,)),
                Section(
                    "Default files",
                    body=(
                        f"{profile.db_name}  - database",
                        ".unpdf/<profile>/  - extraction evidence",
                    ),
                ),
                Section("Checks", body=(checks,)),
            ),
            examples=(f"unpdf-extractor run {profile.flag} .", "unpdf-profiler help"),
            next_steps=("unpdf-extractor help profiles",),
        )
    if name == "profiles":
        return Page(
            title="Profiles",
            summary="A profile describes one document type. No profile is built in.",
            sections=(
                Section(
                    "Where they live",
                    body=(
                        "profiles/<name>/profile.json, relative to the current folder.",
                        "Set UNPDF_PROFILES to use another profile directory.",
                        "When a profile is approved, its name becomes a CLI flag automatically.",
                    ),
                ),
                Section("Discovered", entries=profile_entries(profiles) + family_entries()),
                Section(
                    "Create one",
                    body=(
                        "unpdf-profiler build NAME --samples FOLDER",
                        "Review the generated overlay, then:",
                        "unpdf-profiler approve NAME",
                    ),
                ),
            ),
            next_steps=("unpdf-profiler help", "unpdf-extractor help extraction"),
        )
    if name == "extraction":
        return Page(
            title="How extraction works",
            summary="The core reads PDFs and geometry; the selected profile supplies the boxes and rules.",
            sections=(
                Section(
                    "Reading a page",
                    body=(
                        "Text layer present -> pdfplumber words",
                        "Scan -> local Tesseract (ara+eng)",
                        "Words keep page coordinates and are never merged across the whole page.",
                        "Each profile field is a box; lines are grouped only inside that box.",
                    ),
                ),
                Section(
                    "The contract",
                    body=(
                        "The profile is a frozen JSON contract: pages, anchors, regions, and field boxes.",
                        "A document that fails the contract is quarantined, not guessed at.",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help review", "unpdf-extractor help contract"),
        )
    if name == "review":
        return Page(
            title="Review queue",
            summary="The tool does not silently store values it cannot trust.",
            sections=(
                Section(
                    "Statuses",
                    body=(
                        "accepted  - present and passed its type check",
                        "review    - present but failed a rule, or a required field is empty",
                        "missing   - absent; optional or genuinely blank",
                    ),
                ),
                Section(
                    "Inspect it",
                    body=(
                        "SELECT * FROM review;",
                        "SELECT file, field, reason FROM review ORDER BY file, field;",
                    ),
                ),
                Section(
                    "Fix it",
                    body=(
                        "Open the PDF and compare the field.",
                        "If a rule is wrong, update the profile field type and re-run check.",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help contract", "unpdf-extractor help exit-codes"),
        )
    if name == "contract":
        return Page(
            title="Contract check",
            summary="Before extraction, the document must prove it is the type the profile describes.",
            sections=(
                Section(
                    "What is checked",
                    body=(
                        "page count",
                        "page size within the profile tolerance",
                        "every required label anchor inside its expected box",
                    ),
                ),
                Section(
                    "What happens on a mismatch",
                    body=(
                        "the file is recorded in the quarantine table",
                        "no extracted fields or docs row are written",
                        "the rest of the batch continues",
                        "the command exits with code 4",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help quarantine", "unpdf-extractor help exit-codes"),
        )
    if name == "quarantine":
        return Page(
            title="Quarantine",
            summary="Quarantine is the safe branch for a PDF that is not the declared profile.",
            sections=(
                Section(
                    "Inspect it",
                    body=(
                        "SELECT * FROM quarantine;",
                        "The table stores file, sha256, reason, page, and details.",
                    ),
                ),
                Section(
                    "Fix it",
                    body=(
                        "Check that the folder and profile flag match.",
                        "If the document has a new structure, build and approve a new profile.",
                        "If it is unrelated, move it out of the batch.",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help contract", "unpdf-extractor help exit-codes"),
        )
    if name == "exit-codes":
        return Page(
            title="Exit codes",
            summary="Use the code when you automate the command.",
            sections=(
                Section(
                    "Codes",
                    body=(
                        "0  clean - every extracted field accepted",
                        "1  nothing to do - no PDFs, no database, no profile, or usage mistake",
                        "2  review needed - at least one field needs a human",
                        "3  processing failed - at least one PDF could not be read or extracted",
                        "4  profile mismatch - at least one PDF was quarantined",
                    ),
                ),
                Section(
                    "Order",
                    body=(
                        "3 wins over 4, and 4 wins over 2.",
                        "Good PDFs in the same batch are still saved.",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help review",),
        )
    return None


def topic_names(profiles) -> tuple[str, ...]:
    names = ["profiles", "extraction", "review", "contract", "quarantine", "exit-codes"]
    names.extend(profile.name for profile in profiles)
    return tuple(names)


def all_page_names(profiles) -> tuple[str, ...]:
    return ("run", "check", "rebuild", "help", *topic_names(profiles))

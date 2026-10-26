"""The content of `unpdf-extractor help`, kept separate from how it is drawn."""

from __future__ import annotations

from dataclasses import dataclass

from ..profiles import all_families
from .. import registry


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


def family_entries(profiles) -> tuple[Entry, ...]:
    names = {profile.name for profile in profiles}
    return tuple(
        Entry(f"--{family}", f"{family} (content-routed family)")
        for family in all_families()
        if family not in names
    )


def type_options(profiles) -> tuple[Option, ...]:
    names = ", ".join(profile.name for profile in profiles) or "none cached"
    profile_names = {profile.name for profile in profiles}
    options = [
        Option("--type NAME", f"select a profile; local: {names}"),
        Option("--family NAME", "content-routed family; downloads it when not cached"),
    ]
    options.extend(Option(profile.flag, f"{profile.display_name} (shortcut)") for profile in profiles)
    options.extend(
        Option(f"--{family}", f"{family} family (content-routed)")
        for family in all_families()
        if family not in profile_names
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
    return profiles[0].flag if profiles else "--type NAME"


def _db_name(profiles) -> str:
    return profiles[0].db_name if profiles else "profile.db"


def overview(profiles) -> Page:
    primary = _primary(profiles)
    entries = profile_entries(profiles) + family_entries(profiles)
    if entries:
        start = (
            Entry(f"unpdf-extractor run {primary} .", "read the PDFs in this folder"),
            Entry(f"unpdf-extractor check {primary} .", "re-check an existing database"),
            Entry(f"unpdf-extractor rebuild {primary} .", "rebuild generic output from stored fields"),
        )
    else:
        start = (
            Entry("unpdf-extractor pull NAME", "download an approved profile from the registry"),
            Entry("unpdf-profiler build NAME --samples .", "create the first profile"),
            Entry("unpdf-profiler approve NAME", "approve the generated contract"),
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
                    "Profiles come from profiles/<name>/ or the local registry cache.",
                ),
            ),
            Section(
                "More help",
                entries=(
                    Entry("unpdf-extractor help profiles", "how profiles are discovered"),
                    Entry("unpdf-extractor help registry", "credentials, download, and cache"),
                    Entry("unpdf-profiler help", "build, publish, and manage profiles"),
                    Entry("unpdf-extractor help extraction", "how a PDF becomes fields"),
                    Entry("unpdf-extractor help review", "why a field is flagged"),
                    Entry("unpdf-extractor help contract", "why a document is quarantined"),
                    Entry("unpdf-extractor help exit-codes", "what 0 / 1 / 2 / 3 / 4 mean"),
                    Entry("unpdf-extractor help all", "full reference"),
                ),
            ),
        ),
        footer="Extraction is local. The network is used only to download an uncached profile.",
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
                f"unpdf-extractor run {primary} D:\\docs\\pdfs",
                f"unpdf-extractor run {primary} D:\\docs\\pdfs --db D:\\db\\profile.db",
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
    if name == "pull":
        return Page(
            title="unpdf-extractor pull",
            summary="Download an approved profile from the private registry and cache it.",
            usage="unpdf-extractor pull NAME [--version VERSION]",
            sections=(
                Section(
                    "What happens",
                    body=(
                        "1. Read the registry URL and token from the environment or credentials file.",
                        "2. Download the profile metadata and JSON.",
                        "3. Verify the SHA-256 and the profile contract.",
                        f"4. Store it under {registry.cache_root()}.",
                    ),
                ),
                Section(
                    "Credentials",
                    body=(
                        "Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN, or create "
                        f"{registry.credentials_path()} with url and token keys.",
                        "The token is issued by the profiler owner and is shown only once.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull fasah-import",
                "unpdf-extractor pull fasah-import --version 1.0.0",
            ),
            options=(
                Option("--version VERSION", "pin a version; defaults to the current one"),
                Option("--no-color", "plain text output"),
            ),
            next_steps=("unpdf-extractor run --type fasah-import .", "unpdf-extractor help registry"),
            footer="Exit: 0 cached | 3 registry, hash, or profile error | 1 bad name or no credentials",
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
                        f"Registry profiles are cached under {registry.cache_root()} and used offline.",
                        "When a profile is approved, its name becomes a CLI flag automatically.",
                    ),
                ),
                Section("Discovered", entries=profile_entries(profiles) + family_entries(profiles)),
                Section(
                    "Create or download",
                    body=(
                        "unpdf-extractor pull NAME",
                        "unpdf-profiler build NAME --samples FOLDER",
                        "Review the generated overlay, then:",
                        "unpdf-profiler approve NAME",
                    ),
                ),
            ),
            next_steps=("unpdf-extractor help registry", "unpdf-extractor help extraction"),
        )
    if name == "registry":
        return Page(
            title="Profile registry",
            summary="Approved profiles are downloaded on demand and cached for offline use.",
            sections=(
                Section(
                    "Credentials",
                    body=(
                        "UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN are read first.",
                        f"Or create {registry.credentials_path()} with url and token keys.",
                        "The token belongs to one person; revoke it without touching anyone else.",
                        "No URL or token is stored in this package.",
                    ),
                ),
                Section(
                    "When the network is used",
                    body=(
                        "run --type NAME uses a local or cached profile first.",
                        "An unknown name is downloaded, hash-checked, and cached.",
                        "run --family NAME downloads the family members when none are cached.",
                        "Extraction itself never calls the registry.",
                    ),
                ),
                Section(
                    "Cache",
                    body=(
                        f"{registry.cache_root()}/<name>/<version>/profile.json",
                        "Delete a version folder to force a fresh download.",
                        "Pinned versions stay available offline.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull fasah-import",
                "unpdf-extractor run --type fasah-import C:\\docs",
                "unpdf-extractor run --family fasah C:\\docs",
            ),
            next_steps=("unpdf-extractor help profiles", "unpdf-extractor help exit-codes"),
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
    names = ["profiles", "registry", "extraction", "review", "contract", "quarantine", "exit-codes"]
    names.extend(profile.name for profile in profiles)
    return tuple(names)


def all_page_names(profiles) -> tuple[str, ...]:
    return ("run", "check", "rebuild", "pull", "help", *topic_names(profiles))

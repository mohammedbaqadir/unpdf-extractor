"""The content of `unpdf-extractor help`, kept separate from how it is drawn."""

from __future__ import annotations

from dataclasses import dataclass

from .. import registry
from ..profiles import all_families, profile_meta

TOPICS = (
    ("profiles", "where profiles come from"),
    ("registry", "credentials, download, and cache"),
    ("extraction", "how a PDF becomes fields"),
    ("review", "why a field is flagged"),
    ("contract", "why a PDF is rejected"),
    ("quarantine", "what happens to a rejected PDF"),
    ("exit-codes", "what 0-4 mean"),
)


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
    summary: str = ""
    usage: tuple[str, ...] = ()
    sections: tuple[Section, ...] = ()
    examples: tuple[str, ...] = ()
    options: tuple[Option, ...] = ()


def _profile_rows(profiles) -> tuple[Entry, ...]:
    rows = []
    for profile in profiles:
        display = str(profile_meta(profile).get("display_name") or profile.name)
        rows.append(Entry(f"--type {profile.name}", display))
    return tuple(rows)


def _family_rows() -> tuple[Entry, ...]:
    return tuple(
        Entry(f"--family {family}", "route each PDF to the family member that matches")
        for family in all_families()
    )


def _profile_names(profiles) -> str:
    return ", ".join(profile.name for profile in profiles) or "none yet"


def _start_example(profiles) -> str:
    if not profiles:
        return "unpdf-extractor help profiles"
    return f"unpdf-extractor run --type {profiles[0].name} ."


def _common_options(profiles, *, work: bool = True) -> tuple[Option, ...]:
    families = ", ".join(all_families()) or "none yet"
    options = [
        Option("[folder]", "PDF folder; defaults to the current folder"),
        Option("--type NAME", f"one profile; available: {_profile_names(profiles)}"),
        Option("--family NAME", f"one content-routed family; available: {families}"),
        Option("--db PATH", "database file; defaults to <name>.db in the PDF folder"),
    ]
    if work:
        options.append(
            Option("--work PATH", "evidence folder; defaults to .unpdf next to the database")
        )
    options.append(Option("--no-color", "plain text output"))
    return tuple(options)


def overview(profiles) -> Page:
    sections = [
        Section(
            "Commands",
            entries=(
                Entry("run", "read PDFs from a folder into the database"),
                Entry("check", "re-validate an existing database without the PDFs"),
                Entry("pull", "download an approved profile from the registry"),
                Entry("help", "show a topic: unpdf-extractor help TOPIC"),
            ),
        )
    ]
    rows = _profile_rows(profiles) + _family_rows()
    if rows:
        sections.append(Section("Profiles", entries=rows))
    example = _start_example(profiles)
    sections.extend(
        (
            Section("Start", body=(example,)),
            Section(
                "Output",
                entries=(
                    Entry("<name>.db", "SQLite database next to the PDFs"),
                    Entry(".unpdf/", "profile snapshot and extraction evidence"),
                ),
            ),
            Section(
                "Topics",
                entries=tuple(Entry(name, summary) for name, summary in TOPICS)
                + (Entry("all", "every topic on one page"),),
            ),
        )
    )
    return Page(
        title="unpdf-extractor",
        summary="Read PDFs into a validation-checked SQLite database using approved profiles.",
        sections=tuple(sections),
    )


def type_choice_page(profiles) -> Page:
    sections = []
    if profiles:
        sections.append(Section("Profiles", entries=_profile_rows(profiles)))
    families = _family_rows()
    if families:
        sections.append(Section("Families", entries=families))
    if not sections:
        sections.append(
            Section("No profiles found", body=("Download one first:", "unpdf-extractor pull NAME"))
        )
    example = _start_example(profiles)
    sections.append(Section("Example", body=(example,)))
    return Page(
        title="Which document type?",
        summary="Pass one of these with run or check.",
        sections=tuple(sections),
    )


def command_page(name: str, profiles) -> Page | None:
    if name == "run":
        return Page(
            title="unpdf-extractor run",
            summary="Read PDFs, extract one profile, validate fields, and write SQLite.",
            usage=(
                "unpdf-extractor run [folder] --type NAME [options]",
                "unpdf-extractor run [folder] --family NAME [options]",
            ),
            sections=(
                Section(
                    "What happens",
                    body=(
                        "1. Find *.pdf in the folder (default: the current folder).",
                        "2. Read the text layer, or run local Tesseract OCR on a scan.",
                        "3. Check page count, page size, and required label anchors.",
                        "4. Extract the words inside each declared field box.",
                        "5. Validate each field, write the database, and report review or quarantine.",
                    ),
                ),
                Section(
                    "Output",
                    entries=(
                        Entry("<name>.db", "SQLite database; a family writes one database"),
                        Entry(
                            ".unpdf/",
                            "profile snapshot and extraction evidence, next to the database",
                        ),
                    ),
                ),
                Section("", body=("The PDFs are never moved or modified.",)),
            ),
            examples=(
                "unpdf-extractor run --type bayan .",
                "unpdf-extractor run D:\\docs --type fasah-import",
                "unpdf-extractor run --family fasah --db D:\\db\\fasah.db",
            ),
            options=_common_options(profiles),
        )
    if name == "check":
        return Page(
            title="unpdf-extractor check",
            summary="Re-run field rules against an existing database without reading the PDFs.",
            usage=(
                "unpdf-extractor check [folder] --type NAME [options]",
                "unpdf-extractor check [folder] --family NAME [options]",
            ),
            sections=(
                Section(
                    "Use this when",
                    body=(
                        "You changed a profile and want to re-check stored values.",
                        "Only the database is read; the PDFs are not opened and no evidence is written.",
                    ),
                ),
            ),
            examples=("unpdf-extractor check --type bayan .",),
            options=_common_options(profiles, work=False),
        )
    if name == "pull":
        return Page(
            title="unpdf-extractor pull",
            summary="Download an approved profile from the private registry and cache it.",
            usage=("unpdf-extractor pull NAME [--version VERSION]",),
            sections=(
                Section(
                    "What happens",
                    body=(
                        "1. Read the registry URL and token.",
                        "2. Download the profile metadata and JSON.",
                        "3. Verify the SHA-256 and the profile contract.",
                        "4. Cache it under the profile cache folder.",
                    ),
                ),
                Section(
                    "Credentials",
                    body=(
                        "Environment: UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN.",
                        f"Or the file {registry.credentials_path()} with url and token keys.",
                        "The environment wins, and both values must come from the same place.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull fasah-import",
                "unpdf-extractor pull fasah-import --version 1.0.0",
            ),
            options=(
                Option("NAME", "profile to download, for example fasah-import"),
                Option("--version VERSION", "pin a version; defaults to the current one"),
                Option("--no-color", "plain text output"),
            ),
        )
    if name == "help":
        rows = (
            Entry("run", "read PDFs into the database"),
            Entry("check", "re-check an existing database"),
            Entry("pull", "download a profile"),
            Entry("help", "this page"),
            *(Entry(topic, summary) for topic, summary in TOPICS),
            Entry("all", "every topic on one page"),
        )
        return Page(
            title="unpdf-extractor help",
            summary="Show a command or a concept.",
            usage=(
                "unpdf-extractor help          overview",
                "unpdf-extractor help TOPIC    one topic",
                "unpdf-extractor help all      every topic",
            ),
            sections=(Section("Topics", entries=rows),),
        )
    return None


def topic_page(name: str, profiles) -> Page | None:
    profile = next((item for item in profiles if item.name == name), None)
    if profile is not None:
        return _profile_page(profile)
    if name == "profiles":
        return Page(
            title="Profiles",
            summary="A profile describes one document type: its pages, anchors, and field boxes.",
            sections=(
                Section(
                    "Where they are found",
                    body=(
                        "1. ./profiles/<name>/profile.json, or $UNPDF_PROFILES/<name>/profile.json",
                        "2. The registry cache, newest version per name.",
                    ),
                ),
                Section(
                    "Discovered right now",
                    entries=_profile_rows(profiles) or (Entry("none", "no profile found"),),
                ),
                Section(
                    "Rules",
                    body=(
                        "Only approved profiles are accepted; an unapproved one exits with code 4.",
                        "A profile is data, not code: adding one adds no flag and no branch.",
                        "The PDFs never leave this machine.",
                    ),
                ),
            ),
            examples=("unpdf-extractor run --type bayan .", "unpdf-extractor pull fasah-import"),
        )
    if name == "registry":
        return Page(
            title="Profile registry",
            summary="Approved profiles are downloaded on demand and cached for offline use.",
            sections=(
                Section(
                    "Credentials",
                    body=(
                        "Environment: UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN.",
                        f"Or the file {registry.credentials_path()} with url and token keys.",
                        "The environment wins, and both values must come from the same place.",
                        "No URL, token, or profile data is stored in this package.",
                    ),
                ),
                Section(
                    "When the network is used",
                    body=(
                        "run --type NAME uses a local or cached profile first.",
                        "An unknown name is downloaded when credentials exist.",
                        "run --family NAME asks the registry for the member list when credentials exist.",
                        "Extraction itself never calls the registry.",
                    ),
                ),
                Section(
                    "Cache",
                    body=(
                        f"{registry.cache_root()}/<name>/<version>/profile.json",
                        "Only the current version is kept; pulling another replaces it.",
                        "Delete the folder to force a fresh download.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull fasah-import",
                "unpdf-extractor run --type fasah-import C:\\docs",
            ),
        )
    if name == "extraction":
        return Page(
            title="How extraction works",
            summary="The tool reads the PDF; the profile supplies the boxes and the rules.",
            sections=(
                Section(
                    "Reading a page",
                    body=(
                        "A text layer is read as words with coordinates.",
                        "A scan goes through local Tesseract, Arabic and English.",
                        "Words are never merged across the page; each field is a box.",
                    ),
                ),
                Section(
                    "Checking the document",
                    body=(
                        "Page count, page size, and every required label anchor must match.",
                        "A document that fails is quarantined, never guessed at.",
                    ),
                ),
                Section(
                    "Building a field",
                    body=(
                        "Words whose centre falls inside the field box are selected.",
                        "Lines are grouped inside the box, then read right to left for Arabic.",
                        "The field mode decides one line, every line, or a joined value.",
                    ),
                ),
            ),
        )
    if name == "review":
        return Page(
            title="Review queue",
            summary="A value is stored, but flagged, when the tool cannot trust it.",
            sections=(
                Section(
                    "Statuses",
                    body=(
                        "accepted   present and passed its kind check",
                        "review     present but failed a check, or a required field is empty",
                        "missing    absent; optional or genuinely blank",
                    ),
                ),
                Section(
                    "Inspect",
                    body=("SELECT file, field, status, reason FROM review ORDER BY file, field;",),
                ),
                Section(
                    "Fix",
                    body=(
                        "Compare the PDF with the stored value.",
                        "If the rule is wrong, fix the profile and run check again.",
                    ),
                ),
            ),
        )
    if name == "contract":
        return Page(
            title="Contract check",
            summary="Before extraction, the PDF must prove it is the type the profile describes.",
            sections=(
                Section(
                    "Checked",
                    body=(
                        "page count",
                        "page size within the profile tolerance",
                        "every required label anchor inside its box",
                    ),
                ),
                Section(
                    "On a mismatch",
                    body=(
                        "the PDF is written to the quarantine table with a reason",
                        "no document or field rows are written",
                        "the rest of the batch continues",
                        "the command exits with code 4",
                    ),
                ),
            ),
        )
    if name == "quarantine":
        return Page(
            title="Quarantine",
            summary="A rejected PDF is kept out of the database but never hidden.",
            sections=(
                Section(
                    "Inspect",
                    body=(
                        "SELECT file, reason, page, details FROM quarantine;",
                        "The same record is written to .unpdf/quarantine/<pdf-name>.json.",
                    ),
                ),
                Section(
                    "Fix",
                    body=(
                        "Check that the folder and the selected profile match.",
                        "If the document is a new type, build and approve a profile for it.",
                        "If it does not belong, move it out of the folder.",
                    ),
                ),
            ),
        )
    if name == "exit-codes":
        return Page(
            title="Exit codes",
            summary="Use the code when you script the command.",
            sections=(
                Section(
                    "Codes",
                    body=(
                        "0  clean: every field accepted",
                        "1  nothing to do, or a usage or setup mistake",
                        "2  review needed: at least one field needs a person",
                        "3  at least one PDF could not be read, or the registry failed",
                        "4  a PDF was quarantined, or the profile is not approved",
                    ),
                ),
                Section(
                    "Order",
                    body=(
                        "3 wins over 4, and 4 wins over 2.",
                        "Documents that did pass are still saved.",
                    ),
                ),
            ),
        )
    return None


def _profile_page(profile) -> Page:
    data = profile_meta(profile)
    page = data.get("page") if isinstance(data.get("page"), dict) else {}
    family = str(data.get("family") or "").strip()
    rows = [
        Entry("file", str(profile.path)),
        Entry("version", str(data.get("version") or "unknown")),
    ]
    if family:
        rows.append(Entry("family", family))
    rows.extend(
        (
            Entry("pages", str(page.get("count", "unknown"))),
            Entry("fields", str(len(data.get("fields") or []))),
            Entry("anchors", str(len(data.get("anchors") or []))),
        )
    )
    return Page(
        title=str(data.get("display_name") or profile.name),
        summary=f"The {profile.name} profile.",
        sections=(Section("Details", entries=tuple(rows)),),
        examples=(f"unpdf-extractor run --type {profile.name} .",),
    )


def topic_names(profiles) -> tuple[str, ...]:
    """Every name `help` accepts, including profile names and ``all``."""
    return (
        "run",
        "check",
        "pull",
        "help",
        *(name for name, _summary in TOPICS),
        *(profile.name for profile in profiles),
        "all",
    )


def all_page_names(profiles) -> tuple[str, ...]:
    return tuple(name for name in topic_names(profiles) if name != "all")

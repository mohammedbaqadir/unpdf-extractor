"""The content of `unpdf-extractor help`, kept separate from how it is drawn."""

from __future__ import annotations

from dataclasses import dataclass

from .. import registry
from ..profiles import all_families, profile_meta

TOPICS = (
    ("profiles", "where profiles come from and which ones are ready"),
    ("registry", "credentials, downloads, and the local cache"),
    ("extraction", "how a PDF turns into fields"),
    ("review", "why a value gets flagged"),
    ("contract", "why a PDF gets rejected"),
    ("quarantine", "what happens to a rejected PDF"),
    ("exit-codes", "what the numbers 0-4 mean"),
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
        data = profile_meta(profile)
        display = str(data.get("display_name") or profile.name)
        if not data.get("approved"):
            display += " (not approved)"
        rows.append(Entry(f"--type {profile.name}", display))
    return tuple(rows)


def _family_rows() -> tuple[Entry, ...]:
    return tuple(
        Entry(f"--family {family}", "send each PDF to the family member that fits")
        for family in all_families()
    )


def _profile_names(profiles) -> str:
    names = [
        profile.name
        for profile in profiles
        if profile_meta(profile).get("approved") is True
    ]
    return ", ".join(names) or "none yet"


def _start_example(profiles) -> str:
    approved = [
        profile for profile in profiles if profile_meta(profile).get("approved") is True
    ]
    if not approved:
        return "unpdf-extractor help profiles"
    return f"unpdf-extractor run --type {approved[0].name} ."


def _common_options(
    profiles, *, work: bool = True, action: str = "use"
) -> tuple[Option, ...]:
    families = ", ".join(all_families()) or "none yet"
    names = _profile_names(profiles)
    if action == "check":
        folder_summary = (
            "the folder that holds the database; defaults to the one you're in"
        )
        type_summary = (
            "check this profile; can't be combined with --family. "
            f"available: {names}"
        )
        family_summary = (
            "check the family; can't be combined with --type, and a family needs "
            f"at least two approved members. available: {families}"
        )
        db_summary = (
            "database to check; defaults to <profile-or-family>.db next to the "
            "PDFs, or documents.db when you pick no profile"
        )
    else:
        folder_summary = "the folder to read; defaults to the one you're in"
        type_summary = (
            "use this profile; can't be combined with --family. "
            f"available: {names}"
        )
        family_summary = (
            "use the family member that fits each PDF; can't be combined with "
            "--type, and a family needs at least two approved members. "
            f"available: {families}"
        )
        db_summary = (
            "where to write the database; defaults to <profile-or-family>.db "
            "next to the PDFs, or documents.db when you pick no profile"
        )
    options = [
        Option("[folder]", folder_summary),
        Option("--type NAME", type_summary),
        Option("--family NAME", family_summary),
        Option("--db PATH", db_summary),
    ]
    if work:
        options.append(
            Option(
                "--work PATH",
                "where to keep the evidence; defaults to .unpdf next to the database",
            )
        )
    options.append(Option("-h, --help", "show this page"))
    options.append(Option("--no-color", "turn off color"))
    return tuple(options)


def overview(profiles) -> Page:
    sections = [
        Section(
            "Commands",
            entries=(
                Entry("run", "read a folder of PDFs into the database"),
                Entry("check", "re-check a database you already have, without the PDFs"),
                Entry("identify", "see which profile each PDF would get; writes nothing"),
                Entry("pull", "download a profile from the registry"),
                Entry("help", "explain a command or a topic; --help works too"),
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
                    Entry("<name>.db", "one database per profile or family"),
                    Entry(
                        "documents.db",
                        "what you get when you pass no --type or --family",
                    ),
                    Entry(
                        ".unpdf/",
                        "the profile, the words, and the fields; saved next to the database",
                    ),
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
        summary=(
            "This reads PDFs from a folder and puts the fields you care about into a "
            "SQLite database. It checks each value as it goes, so you can see what "
            "passed, what needs a look, and what it couldn't use."
        ),
        sections=tuple(sections),
    )


def command_page(name: str, profiles) -> Page | None:
    if name == "run":
        return Page(
            title="unpdf-extractor run",
            summary=(
                "Reads every PDF in a folder, picks the profile that fits, pulls out "
                "the fields, checks them, and writes the results to a database."
            ),
            usage=(
                "unpdf-extractor run [folder] --type NAME [options]",
                "unpdf-extractor run [folder] --family NAME [options]",
                "unpdf-extractor run [folder] [options]",
            ),
            sections=(
                Section(
                    "What happens",
                    body=(
                        (
                            "1. It looks for *.pdf in the folder you name. If you "
                            "don't name one, it uses the folder you're in."
                        ),
                        (
                            "2. It reads the text layer on each page. If a page has "
                            "no usable text, it runs Tesseract locally, in Arabic and "
                            "English."
                        ),
                        (
                            "3. It picks the profile. With --type, it uses that one. "
                            "With --family, it picks the family member that fits. "
                            "With neither, it tries every approved profile on this "
                            "machine."
                        ),
                        (
                            "4. It checks the page count, the page size, and every "
                            "label anchor. The profile's match rule still has to "
                            "hold, even when you named the profile."
                        ),
                        (
                            "5. It reads the words inside each field box the profile "
                            "declares."
                        ),
                        (
                            "6. It checks each value, writes the database, and tells "
                            "you what needs a look and what it couldn't use."
                        ),
                    ),
                ),
                Section(
                    "Output",
                    entries=(
                        Entry("<name>.db", "one database per profile or family"),
                        Entry("documents.db", "what you get without --type or --family"),
                        Entry(
                            ".unpdf/",
                            "the profile, the words, and the fields; saved next to the database",
                        ),
                    ),
                ),
                Section(
                    "",
                    body=(
                        "",
                        "The PDFs themselves are never moved or changed.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor run --type invoice .",
                "unpdf-extractor run D:\\docs --type invoice",
                "unpdf-extractor run --family invoice --db D:\\db\\invoice.db",
                "unpdf-extractor run C:\\docs",
            ),
            options=_common_options(profiles),
        )
    if name == "check":
        return Page(
            title="unpdf-extractor check",
            summary=(
                "Re-checks the values already in a database against the current "
                "profiles. It never opens the PDFs."
            ),
            usage=(
                "unpdf-extractor check [folder] --type NAME [options]",
                "unpdf-extractor check [folder] --family NAME [options]",
                "unpdf-extractor check [folder] [options]",
            ),
            sections=(
                Section(
                    "Use this when",
                    body=(
                        "You changed a profile and want to see how the stored values hold up.",
                        "Only the database is read. The PDFs aren't opened, and no evidence is written.",
                        "With no --type or --family, it checks every approved profile against documents.db.",
                    ),
                ),
            ),
            examples=("unpdf-extractor check --type invoice .",),
            options=_common_options(profiles, work=False, action="check"),
        )
    if name == "identify":
        return Page(
            title="unpdf-extractor identify",
            summary="Shows which approved profile each PDF would get. It writes nothing.",
            usage=("unpdf-extractor identify [folder]",),
            sections=(
                Section(
                    "What it does",
                    body=(
                        (
                            "It tries every approved profile on this machine. "
                            "There's no --type or --family here."
                        ),
                        "It reads the PDFs, so a scan needs Tesseract too.",
                        "For each PDF, it prints one line:",
                        "",
                        "  identify  a.pdf: invoice           one profile matched",
                        "  identify  b.pdf: none (...)        nothing matched",
                        "  identify  c.pdf: ambiguous (...)   more than one matched",
                        "",
                        "No database, no evidence, nothing changed.",
                    ),
                ),
                Section(
                    "Exit codes",
                    body=(
                        "0  every PDF matched exactly one profile",
                        "1  a setup problem: no approved profiles, no PDFs, or a bad folder",
                        "3  at least one PDF couldn't be read",
                        "4  at least one PDF matched nothing, or matched more than one",
                        "",
                        "If both 3 and 4 happen, 3 wins.",
                    ),
                ),
            ),
            examples=("unpdf-extractor identify C:\\docs",),
            options=(
                Option("[folder]", "the folder to look in; defaults to the one you're in"),
                Option("-h, --help", "show this page"),
                Option("--no-color", "turn off color"),
            ),
        )
    if name == "pull":
        return Page(
            title="unpdf-extractor pull",
            summary=(
                "Downloads an approved profile from the registry and keeps a copy on "
                "this machine."
            ),
            usage=("unpdf-extractor pull NAME [--version VERSION]",),
            sections=(
                Section(
                    "What happens",
                    body=(
                        "1. It reads the registry URL and token.",
                        "2. It downloads the profile's details and its profile.json.",
                        "3. It checks the SHA-256, the profile name, and that the profile is approved.",
                        "4. It saves the profile in the local cache.",
                    ),
                ),
                Section(
                    "Credentials",
                    body=(
                        "Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN.",
                        f"Or put url and token in {registry.credentials_path()}.",
                        "The environment wins, but both values have to come from the same place.",
                        "If you set only one, it stops and tells you.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull invoice",
                "unpdf-extractor pull invoice --version 1.0.0",
            ),
            options=(
                Option("NAME", "profile to download, for example invoice"),
                Option("--version VERSION", "pin a version; defaults to the current one"),
                Option("-h, --help", "show this page"),
                Option("--no-color", "turn off color"),
            ),
        )
    if name == "help":
        rows = (
            Entry("run", "read PDFs into the database"),
            Entry("check", "re-check an existing database"),
            Entry("identify", "preview the profile for each PDF"),
            Entry("pull", "download a profile"),
            Entry("help", "this page"),
            *(Entry(topic, summary) for topic, summary in TOPICS),
            Entry("all", "every topic on one page"),
        )
        return Page(
            title="unpdf-extractor help",
            summary="Shows the overview, a command, a profile, or one of the topics.",
            usage=(
                "unpdf-extractor help          the overview",
                "unpdf-extractor help TOPIC    one page",
                "unpdf-extractor help all      every page at once",
            ),
            sections=(
                Section("Topics", entries=rows),
                Section(
                    "",
                    body=(
                        "",
                        "You can also pass a profile name, for example:",
                        "unpdf-extractor help bayan",
                        "For a command page, unpdf-extractor COMMAND --help does the same thing.",
                        "If a topic doesn't exist, it exits 1 and suggests the closest match.",
                    ),
                ),
            ),
            options=(Option("-h, --help", "show this page"),),
        )
    return None


def topic_page(name: str, profiles) -> Page | None:
    profile = next((item for item in profiles if item.name == name), None)
    if profile is not None:
        return _profile_page(profile)
    if name == "profiles":
        return Page(
            title="Profiles",
            summary=(
                "A profile is a JSON file that describes one document type. It says "
                "how many pages to expect, which labels prove the type, and where the "
                "fields are."
            ),
            sections=(
                Section(
                    "Where they're found",
                    body=(
                        "1. ./profiles/<name>/profile.json, or $UNPDF_PROFILES/<name>/profile.json",
                        "2. The registry cache, newest version of each name.",
                    ),
                ),
                Section(
                    "Discovered right now",
                    entries=_profile_rows(profiles) or (Entry("none", "no profile found"),),
                ),
                Section(
                    "Rules",
                    body=(
                        (
                            "Only approved profiles are used. Naming an unapproved "
                            "one with --type or --family stops with code 4; an "
                            "automatic run just skips it."
                        ),
                        (
                            "A profile is just data. Drop one in and the tool picks "
                            "it up; there's no new flag or code to add."
                        ),
                        "The PDFs never leave this machine.",
                    ),
                ),
            ),
            examples=("unpdf-extractor run --type invoice .", "unpdf-extractor pull invoice"),
        )
    if name == "registry":
        return Page(
            title="Profile registry",
            summary=(
                "The registry is where approved profiles live. The tool downloads one "
                "when it needs it, then keeps a copy for offline use."
            ),
            sections=(
                Section(
                    "Credentials",
                    body=(
                        "Set UNPDF_REGISTRY_URL and UNPDF_REGISTRY_TOKEN.",
                        f"Or put url and token in {registry.credentials_path()}.",
                        "The environment wins, but both values have to come from the same place.",
                    ),
                ),
                Section(
                    "When the network is used",
                    body=(
                        (
                            "run --type NAME checks the local profiles and the cache "
                            "first. If it doesn't know the name and credentials are "
                            "set, it downloads it."
                        ),
                        (
                            "run --family NAME asks the registry for the full member "
                            "list when credentials are set, and downloads any member "
                            "that isn't cached yet. A family needs at least two "
                            "approved members."
                        ),
                        (
                            "If the registry call fails and it already has members "
                            "locally, it uses those."
                        ),
                        (
                            "An automatic run (no --type, no --family) never calls "
                            "the registry. It only uses the approved profiles already "
                            "on this machine."
                        ),
                        "Once the profile is loaded, extraction is offline.",
                    ),
                ),
                Section(
                    "Cache",
                    body=(
                        f"{registry.cache_root()}/<name>/<version>/profile.json",
                        "Only the current version is kept. Pulling another version replaces it.",
                        "Delete the folder to force a fresh download.",
                    ),
                ),
            ),
            examples=(
                "unpdf-extractor pull invoice",
                "unpdf-extractor run --type invoice C:\\docs",
            ),
        )
    if name == "extraction":
        return Page(
            title="How extraction works",
            summary="The tool reads the PDF. The profile tells it where to look and what to check.",
            sections=(
                Section(
                    "Reading a page",
                    body=(
                        "If the page has a text layer, it reads the words and their coordinates directly.",
                        "If a page has no usable text, it runs Tesseract locally, in Arabic and English.",
                        "It never merges words across the page. Each field is its own box.",
                        "The database records whether the PDF needed OCR on any page, and how confident OCR was about each field.",
                    ),
                ),
                Section(
                    "Checking the document",
                    body=(
                        "The page count, page size, and every label anchor have to match.",
                        "If they don't, the PDF is quarantined. The tool doesn't guess.",
                    ),
                ),
                Section(
                    "Building a field",
                    body=(
                        "It takes the words whose centre falls inside the field box.",
                        "It groups them into lines, then reads right to left for Arabic.",
                        "line mode keeps the line with the most characters. multi mode joins the lines with a space.",
                        "A field can have a fallback box, used only when the first box is empty.",
                    ),
                ),
            ),
        )
    if name == "review":
        return Page(
            title="Review queue",
            summary=(
                "A value can be stored and still be wrong. When the tool can't trust it, "
                "it keeps the value but flags it."
            ),
            sections=(
                Section(
                    "Statuses",
                    body=(
                        "accepted  there's a value and it passed its check",
                        "review    there's a value but it failed a check, or a required field is empty",
                        "missing   there's no value. That's fine for an optional field; a required one becomes review instead.",
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
            summary=(
                "Before it extracts anything, the tool checks that the PDF really is "
                "the type the profile describes."
            ),
            sections=(
                Section(
                    "Checked",
                    body=(
                        "the number of pages",
                        "the page size, within the profile's tolerance",
                        "every label anchor, inside its box",
                    ),
                ),
                Section(
                    "On a mismatch",
                    body=(
                        "the PDF goes into the quarantine table with a reason",
                        "no document or field rows are written for it",
                        "the rest of the batch keeps going",
                        "the command exits with code 4",
                    ),
                ),
            ),
        )
    if name == "quarantine":
        return Page(
            title="Quarantine",
            summary=(
                "A rejected PDF isn't dropped silently. It's kept out of the document "
                "table, but the reason is recorded."
            ),
            sections=(
                Section(
                    "Inspect",
                    body=(
                        "SELECT file, reason, page, details FROM quarantine;",
                        "The same record is also written to .unpdf/quarantine/<name-without-.pdf>.json.",
                    ),
                ),
                Section(
                    "Fix",
                    body=(
                        "Check that the folder and the profile match.",
                        "If it's a new document type, build and approve a profile for it.",
                        "If it doesn't belong in this folder, move it out.",
                    ),
                ),
            ),
        )
    if name == "exit-codes":
        return Page(
            title="Exit codes",
            summary="Use these when you script the command.",
            sections=(
                Section(
                    "Codes",
                    body=(
                        "0  everything that was found passed; optional blanks are fine",
                        "1  nothing to do, or a usage or setup problem",
                        "2  something needs review",
                        "3  a PDF couldn't be read, or the registry failed",
                        "4  a PDF was quarantined, a profile isn't approved, or identify found no single match",
                    ),
                ),
                Section(
                    "Order",
                    body=(
                        "3 beats 4, and 4 beats 2.",
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
        Entry("approved", "yes" if data.get("approved") else "no"),
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
        summary=f"What the {profile.name} profile expects from a PDF.",
        sections=(
            Section("Details", entries=tuple(rows)),
            Section(
                "",
                body=(
                    "",
                    (
                        "pages is the page count it requires. fields are the boxes "
                        "it reads. anchors are the labels it looks for to prove the "
                        "PDF is this type."
                    ),
                ),
            ),
        ),
        examples=(f"unpdf-extractor run --type {profile.name} .",),
    )


def topic_names(profiles) -> tuple[str, ...]:
    """Every name `help` accepts, including profile names and ``all``."""
    return (
        "run",
        "check",
        "identify",
        "pull",
        "help",
        *(name for name, _summary in TOPICS),
        *(profile.name for profile in profiles),
        "all",
    )


def all_page_names(profiles) -> tuple[str, ...]:
    return tuple(name for name in topic_names(profiles) if name != "all")

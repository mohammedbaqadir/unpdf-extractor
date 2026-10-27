"""Run and check operations behind the command line.

A *job* is one database plus the contracts that may fill it: one contract for
``--type``, every family member for ``--family``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import pipeline
from .contract import check_contract
from .errors import UnpdfError
from .extract import FieldValue, extract_fields
from .profile import LayoutProfile
from .profiles import Profile, family_profiles, get_profile

PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = PACKAGE_ROOT.parent.parent if PACKAGE_ROOT.parent.name == "src" else None
WORK_DIR = ".unpdf"


@dataclass
class Summary:
    """What a run changed and what the database holds.

    Run-scoped: added, skipped, failed.
    Database-wide for this job: documents, accepted, review, missing,
    quarantined, review_rows, quarantine_rows.
    """

    documents: int = 0
    accepted: int = 0
    review: int = 0
    missing: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    quarantined: int = 0
    review_rows: list[tuple[str, str, str]] = field(default_factory=list)
    quarantine_rows: list[tuple[str, str]] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        if self.failed:
            return 3
        if self.quarantined:
            return 4
        if self.review:
            return 2
        return 0


@dataclass(frozen=True)
class Job:
    """One database and the contracts allowed to fill it."""

    name: str
    db_name: str
    contracts: dict[str, LayoutProfile]


@dataclass(frozen=True)
class Match:
    name: str
    contract: LayoutProfile
    values: dict[str, FieldValue]


@dataclass(frozen=True)
class Failure:
    reason: str
    page: int | None = None
    details: tuple[str, ...] = ()


def load_contract(profile: Profile) -> LayoutProfile:
    contract = LayoutProfile.load(profile.path)
    contract.require_approved()
    return contract


def type_job(name: str) -> Job:
    profile = get_profile(name)
    return Job(profile.name, profile.db_name, {profile.name: load_contract(profile)})


def family_job(family: str) -> Job:
    contracts = {
        profile.name: load_contract(profile) for profile in family_profiles(family)
    }
    return Job(family, f"{family}.db", contracts)


def resolve_paths(
    job: Job,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    """Return (PDF folder, database, work folder)."""
    source = Path(folder).expanduser()
    if not source.is_dir():
        raise UnpdfError(f"Folder not found: {source}", exit_code=1)
    source = source.resolve()
    db_path = Path(db).expanduser().resolve() if db else source / job.db_name
    work_root = Path(work).expanduser().resolve() if work else db_path.parent / WORK_DIR
    _ensure_external(db_path, "database")
    _ensure_external(work_root, "work folder")
    return source, db_path, work_root


def run(
    job: Job,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    """Extract every new PDF in the folder into the job database."""
    source, db_path, work_root = resolve_paths(job, folder, db, work)
    pdfs = _pdfs(source)
    fresh, skipped = pipeline.split_known(pdfs, db_path)
    print(f"extract  {job.name} -> {db_path}")

    if not fresh:
        print(f"skip     {len(skipped)} PDF(s) already in the database")
        return _database_state(job, db_path)

    work_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _write_snapshot(job, work_root)

    runner = _Run(job, work_root, sqlite3.connect(db_path), Summary(skipped=len(skipped)))
    try:
        pipeline.ensure_schema(runner.conn)
        _record_contracts(runner.conn, job)
        seen: set[str] = set()
        for pdf, digest in fresh:
            if digest in seen:
                print(f"skip     {pdf.name} (duplicate content in this batch)")
                runner.summary.skipped += 1
                continue
            seen.add(digest)
            runner.ingest(pdf, digest)
        runner.conn.commit()
        _fill_counts(runner.conn, job, runner.summary)
    finally:
        runner.conn.close()

    return runner.summary


def check(
    job: Job,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    """Re-validate every stored document against the current contracts."""
    _source, db_path, _work_root = resolve_paths(job, folder, db, work)
    if not db_path.exists():
        raise UnpdfError(f"No database at {db_path}.", exit_code=1)

    conn = sqlite3.connect(db_path)
    try:
        pipeline.ensure_schema(conn)
        for name, contract in job.contracts.items():
            _warn_if_changed(conn, name, contract)
            doc_ids = [
                row[0]
                for row in conn.execute("SELECT doc_id FROM docs WHERE format = ?", (name,))
            ]
            for doc_id in doc_ids:
                pipeline.validate_document(
                    conn, name, contract, doc_id, pipeline.stored_values(conn, doc_id)
                )
        conn.commit()
        summary = Summary()
        _fill_counts(conn, job, summary)
        return summary
    finally:
        conn.close()


class _Run:
    """One extraction pass: per-PDF work plus the summary it feeds."""

    def __init__(
        self, job: Job, work_root: Path, conn: sqlite3.Connection, summary: Summary
    ) -> None:
        self.job = job
        self.work_root = work_root
        self.conn = conn
        self.summary = summary

    def ingest(self, pdf: Path, digest: str) -> None:
        workdir = pipeline.temp_workdir()
        try:
            try:
                page_data = pipeline.words_for_pdf(pdf, workdir)
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the batch
                print(f"error    {pdf.name}: {type(exc).__name__}: {exc}")
                self.summary.failed += 1
                return

            outcome = _match(page_data, self.job.contracts)
            if isinstance(outcome, Failure):
                self._quarantine(pdf, digest, outcome)
            else:
                self._store(pdf, digest, outcome, page_data)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _quarantine(self, pdf: Path, digest: str, failure: Failure) -> None:
        pipeline.quarantine(
            self.conn,
            self.work_root,
            self.job.name,
            pdf,
            digest,
            failure.reason,
            failure.page,
            failure.details,
        )
        self.conn.commit()
        print(f"quarantine  {pdf.name}: {failure.reason}")

    def _store(self, pdf: Path, digest: str, match: Match, page_data) -> None:
        words = page_data[0]
        pipeline.write_evidence(self.work_root, pdf, words, match.values)
        doc_id = self.conn.execute(
            "INSERT INTO docs (format, file, sha256, added_at, rows) VALUES (?, ?, ?, ?, ?)",
            (
                match.name,
                pdf.name,
                digest,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                len(match.values),
            ),
        ).lastrowid
        pipeline.insert_fields(self.conn, doc_id, match.values)
        pipeline.validate_document(
            self.conn,
            match.name,
            match.contract,
            doc_id,
            pipeline.stored_values(self.conn, doc_id),
        )
        self.conn.commit()
        print(f"add         {pdf.name}: {len(match.values)} field(s)")
        self.summary.added += 1


def _match(
    page_data: pipeline.PageData,
    contracts: dict[str, LayoutProfile],
) -> Match | Failure:
    """Pick the one contract that describes this PDF."""
    words, ocr_pages, page_sizes = page_data
    if not words:
        return Failure("no text layer and OCR found no words")

    matches: list[Match] = []
    reasons: list[str] = []
    for name, contract in contracts.items():
        result = check_contract(contract, words, page_sizes)
        if not result.ok:
            if len(contracts) == 1:
                return Failure(result.reason, result.page, result.details)
            reasons.append(f"{name}: {result.reason}")
            continue
        values = extract_fields(contract, words, page_sizes, ocr_pages)
        rule = contract.raw.get("match") or {}
        field_name = str(rule.get("field") or "").strip()
        if field_name:
            value = values.get(field_name)
            terms = [str(term) for term in rule.get("contains_any") or [] if str(term)]
            if value is None or (terms and not any(term in value.value for term in terms)):
                if len(contracts) == 1:
                    return Failure("the profile's match rule did not hold")
                reasons.append(f"{name}: match rule did not hold")
                continue
        matches.append(Match(name, contract, values))

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(match.name for match in matches)
        return Failure(f"matched more than one profile: {names}", details=tuple(reasons))
    return Failure("no profile subtype matched", details=tuple(reasons))


def _pdfs(source: Path) -> list[Path]:
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise UnpdfError(f"No PDFs in {source}.", exit_code=1)
    duplicates = sorted(
        stem for stem, count in Counter(pdf.stem for pdf in pdfs).items() if count > 1
    )
    if duplicates:
        raise UnpdfError(
            f"Duplicate PDF file names in {source}: {', '.join(duplicates)}. "
            "Rename them and retry.",
            exit_code=1,
        )
    return pdfs


def _write_snapshot(job: Job, work_root: Path) -> None:
    folder = work_root / "profiles"
    folder.mkdir(parents=True, exist_ok=True)
    for name, contract in job.contracts.items():
        (folder / f"{name}.json").write_text(
            json.dumps(contract.raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _warn_if_changed(conn: sqlite3.Connection, name: str, contract: LayoutProfile) -> None:
    row = conn.execute(
        "SELECT value FROM _meta WHERE key = ?", (f"profile:{name}:fingerprint",)
    ).fetchone()
    if row and row[0] != contract.fingerprint:
        print(
            f"[warn] {name}: the database was built with a different profile. "
            "Existing documents are not re-extracted; use a new database to apply the change."
        )


def _record_contracts(conn: sqlite3.Connection, job: Job) -> None:
    for name, contract in job.contracts.items():
        _warn_if_changed(conn, name, contract)
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES (?, ?), (?, ?)",
            (
                f"profile:{name}:version",
                contract.version,
                f"profile:{name}:fingerprint",
                contract.fingerprint,
            ),
        )
    conn.commit()


def _database_state(job: Job, db_path: Path) -> Summary:
    """Summary for a database that already has every PDF in the folder."""
    conn = sqlite3.connect(db_path)
    try:
        pipeline.ensure_schema(conn)
        summary = Summary()
        _fill_counts(conn, job, summary)
        return summary
    finally:
        conn.close()


def _fill_counts(conn: sqlite3.Connection, job: Job, summary: Summary) -> None:
    keys = tuple(job.contracts)
    marks = ", ".join("?" * len(keys))
    summary.documents = conn.execute(
        f"SELECT COUNT(*) FROM docs WHERE format IN ({marks})", keys
    ).fetchone()[0]
    counts = dict(
        conn.execute(
            f"SELECT status, COUNT(*) FROM _field_status WHERE format IN ({marks}) GROUP BY status",
            keys,
        ).fetchall()
    )
    summary.accepted = counts.get("accepted", 0)
    summary.review = counts.get("review", 0)
    summary.missing = counts.get("missing", 0)
    summary.review_rows = [
        tuple(row)
        for row in conn.execute(
            f"""
            SELECT d.file, s.field, s.reason
            FROM _field_status s JOIN docs d USING (doc_id)
            WHERE s.format IN ({marks}) AND s.status = 'review'
            ORDER BY d.file, s.field
            """,
            keys,
        )
    ]
    summary.quarantine_rows = pipeline.quarantine_rows(conn, job.name)
    summary.quarantined = len(summary.quarantine_rows)


def _ensure_external(path: Path, label: str) -> None:
    resolved = path.resolve()
    for root in (PACKAGE_ROOT, _PROJECT_ROOT):
        if root is None:
            continue
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        raise UnpdfError(f"{label} must be outside the tool folder: {path}", exit_code=1)

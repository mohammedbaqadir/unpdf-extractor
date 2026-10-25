"""Public operations behind the unpdf command."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from unpdf_core import pipeline
from unpdf_core.contract import check_contract
from unpdf_core.errors import UnpdfError
from unpdf_core.extract import extract_fields
from unpdf_core.profile import LayoutProfile
from unpdf_core.profiles import family_profiles

PACKAGE_ROOT = Path(__file__).resolve().parent
_PROJECT_ROOT = PACKAGE_ROOT.parent.parent if PACKAGE_ROOT.parent.name == "src" else None


@dataclass
class Summary:
    documents: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    quarantined: int = 0
    accepted: int = 0
    review: int = 0
    missing: int = 0
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


def resolve_paths(
    profile,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> tuple[Path, Path, Path]:
    source = Path(folder).expanduser()
    if not source.exists() or not source.is_dir():
        raise UnpdfError(f"Folder not found: {source}", exit_code=1)
    source = source.resolve()

    db_path = Path(db).expanduser().resolve() if db else source / profile.db_name
    if work:
        work_root = Path(work).expanduser().resolve()
    elif db:
        work_root = db_path.parent / profile.work_name
    else:
        work_root = source / profile.work_name
    _ensure_external(db_path, "database")
    _ensure_external(work_root, "work folder")
    return source, db_path, work_root


def load_profile(profile) -> LayoutProfile:
    contract = LayoutProfile.load(profile.profile_path)
    contract.require_approved()
    return contract


def run_folder(
    profile,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    source, db_path, work_root = resolve_paths(profile, folder, db, work)
    contract = load_profile(profile)
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise UnpdfError(f"No PDFs in {source}.", exit_code=1)

    seen: set[str] = set()
    duplicates: set[str] = set()
    for pdf in pdfs:
        if pdf.stem in seen:
            duplicates.add(pdf.stem)
        seen.add(pdf.stem)
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise UnpdfError(
            f"Duplicate PDF file names in {source}: {names}. Rename them and retry.",
            exit_code=1,
        )

    fresh = pipeline.filter_new(pdfs, db_path)
    added = skipped = failed = quarantined = 0
    if fresh:
        print(f"stage: {profile.name} profile extraction")
        work_root.mkdir(parents=True, exist_ok=True)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        (work_root / "profile.json").write_bytes(Path(profile.profile_path).read_bytes())
        conn = sqlite3.connect(db_path)
        try:
            pipeline.ensure_schema(conn)
            profile.ensure(conn)
            conn.execute(
                "INSERT OR REPLACE INTO _meta (key, value) VALUES "
                "('profile_name', ?), ('profile_version', ?), ('profile_fingerprint', ?)",
                (contract.name, contract.version, contract.fingerprint),
            )
            conn.commit()

            for pdf in fresh:
                digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
                workdir = pipeline.temp_workdir()
                try:
                    try:
                        words, ocr_pages, page_sizes = pipeline.words_for_pdf(pdf, workdir)
                    except Exception as exc:  # noqa: BLE001 - one bad file must not kill the batch
                        print(f"[error] {pdf.name}: {type(exc).__name__}: {exc} — not added")
                        failed += 1
                        continue

                    if not words:
                        reason = "no text layer and OCR found no words"
                        pipeline.write_quarantine_artifact(work_root, profile, pdf, digest, reason)
                        pipeline.record_quarantine(conn, profile, pdf, digest, reason)
                        conn.commit()
                        print(f"quarantine  {pdf.name}: {reason}")
                        quarantined += 1
                        continue

                    result = check_contract(contract, words, page_sizes)
                    if not result.ok:
                        pipeline.write_quarantine_artifact(
                            work_root, profile, pdf, digest, result.reason,
                            page=result.page, details=result.details,
                        )
                        pipeline.record_quarantine(
                            conn, profile, pdf, digest, result.reason,
                            page=result.page, details=result.details,
                        )
                        conn.commit()
                        print(f"quarantine  {pdf.name}: {result.reason}")
                        quarantined += 1
                        continue

                    values = extract_fields(contract, words, page_sizes, method="ocr" if ocr_pages else "text")
                    if not values:
                        reason = "profile matched but no fields were found"
                        pipeline.write_quarantine_artifact(work_root, profile, pdf, digest, reason)
                        pipeline.record_quarantine(conn, profile, pdf, digest, reason)
                        conn.commit()
                        print(f"quarantine  {pdf.name}: {reason}")
                        quarantined += 1
                        continue

                    evidence = work_root / "documents"
                    evidence.mkdir(parents=True, exist_ok=True)
                    (evidence / f"{pdf.stem}_words.json").write_text(
                        json.dumps(words, ensure_ascii=False), encoding="utf-8"
                    )
                    (evidence / f"{pdf.stem}_fields.json").write_text(
                        json.dumps(
                            {
                                name: {
                                    "value": item.value,
                                    "page": item.page,
                                    "box": item.box,
                                    "method": item.method,
                                }
                                for name, item in values.items()
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )

                    doc_id = conn.execute(
                        "INSERT INTO docs (format, file, sha256, added_at, records, ocr) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            profile.name,
                            pdf.name,
                            digest,
                            datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            1,
                            1 if ocr_pages else 0,
                        ),
                    ).lastrowid
                    pipeline.insert_fields(conn, doc_id, values)
                    pipeline.validate_document(
                        conn,
                        profile,
                        contract,
                        doc_id,
                        pipeline.collect_doc_values(conn, doc_id),
                    )
                    conn.execute("UPDATE docs SET rows = ?, missing = ? WHERE doc_id = ?", (1, 0, doc_id))
                    profile.write_document(conn, doc_id, work_root)
                    conn.commit()
                    print(f"add   {pdf.name}: {len(values)} field(s), OCR={1 if ocr_pages else 0}")
                    added += 1
                finally:
                    shutil.rmtree(workdir, ignore_errors=True)

            conn.commit()
        finally:
            conn.close()
        skipped = len(pdfs) - len(fresh)
    else:
        print("All files in this batch are already in the database.")
        skipped = len(pdfs)

    if not db_path.exists():
        raise UnpdfError("No database was created (no usable documents).", exit_code=3)

    summary = check_database(profile, source, db=db_path, work=work_root)
    summary.added = added
    summary.skipped = skipped
    summary.failed = failed
    summary.quarantined = quarantined
    if not summary.documents and not quarantined:
        raise UnpdfError("No documents in the database.", exit_code=3 if failed else 1)
    return summary


def _merge_summary(total: Summary, part: Summary) -> None:
    total.documents += part.documents
    total.accepted += part.accepted
    total.review += part.review
    total.missing += part.missing
    total.added += part.added
    total.skipped += part.skipped
    total.failed += part.failed
    total.quarantined += part.quarantined
    total.review_rows.extend(part.review_rows)
    total.quarantine_rows.extend(part.quarantine_rows)


@dataclass(frozen=True)
class _FamilyHandle:
    name: str
    db_name: str
    work_name: str = ".unpdf"


def _classify_sample(pdf: Path, members) -> tuple[object | None, str]:
    workdir = pipeline.temp_workdir()
    try:
        words, _ocr_pages, sizes = pipeline.words_for_pdf(pdf, workdir)
        if not words:
            return None, "no text layer and OCR found no words"
        matches = []
        for profile, contract in members:
            result = check_contract(contract, words, sizes)
            if not result.ok:
                continue
            values = extract_fields(contract, words, sizes)
            rule = contract.raw.get("match") or {}
            field = str(rule.get("field", "")).strip()
            if field:
                value = values.get(field)
                if value is None:
                    continue
                terms = [str(term) for term in rule.get("contains_any") or [] if str(term)]
                if terms and not any(term in value.value for term in terms):
                    continue
            matches.append((profile, contract, values))
        if len(matches) == 1:
            return matches[0], ""
        if len(matches) > 1:
            return None, "matched multiple profile subtypes"
        return None, "no profile subtype matched"
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_family(
    family: str,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    members = family_profiles(family)
    if len(members) < 2:
        raise UnpdfError(f"Family '{family}' needs at least two approved profiles.", exit_code=1)
    candidates = [(profile, load_profile(profile)) for profile in members]
    handle = _FamilyHandle(family, f"{family}.db")
    source, db_path, work_root = resolve_paths(handle, folder, db, work)
    pdfs = sorted(source.glob("*.pdf"))
    if not pdfs:
        raise UnpdfError(f"No PDFs in {source}.", exit_code=1)

    groups: dict[str, list[Path]] = {profile.name: [] for profile in members}
    unmatched: list[tuple[Path, str]] = []
    for pdf in pdfs:
        match, reason = _classify_sample(pdf, candidates)
        if match is None:
            unmatched.append((pdf, reason))
            continue
        profile, _contract, _values = match
        groups[profile.name].append(pdf)

    total = Summary()
    temp_root = Path(tempfile.mkdtemp(prefix=f"unpdf-{family}-"))
    try:
        for profile, _contract in candidates:
            selected = groups[profile.name]
            if not selected:
                continue
            sample_dir = temp_root / profile.name
            sample_dir.mkdir()
            for pdf in selected:
                target = sample_dir / pdf.name
                try:
                    os.link(pdf, target)
                except OSError:
                    shutil.copy2(pdf, target)
            part = run_folder(profile, sample_dir, db_path, work_root)
            total.added += part.added
            total.skipped += part.skipped
            total.failed += part.failed
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    if unmatched:
        if not db_path.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(db_path)
            pipeline.ensure_schema(conn)
            conn.commit()
            conn.close()
        conn = sqlite3.connect(db_path)
        try:
            pipeline.ensure_schema(conn)
            for pdf, reason in unmatched:
                digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
                pipeline.write_quarantine_artifact(work_root, handle, pdf, digest, reason)
                pipeline.record_quarantine(conn, handle, pdf, digest, reason)
            conn.commit()
        finally:
            conn.close()
        total.quarantined += len(unmatched)
        total.quarantine_rows.extend((pdf.name, reason) for pdf, reason in unmatched)

    checked = check_family(family, source, db_path, work_root)
    _merge_summary(total, checked)
    if not total.documents and not total.quarantined:
        raise UnpdfError("No documents in the database.", exit_code=3 if total.failed else 1)
    return total


def check_family(
    family: str,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    members = family_profiles(family)
    if len(members) < 2:
        raise UnpdfError(f"Family '{family}' needs at least two approved profiles.", exit_code=1)
    total = Summary()
    for profile in members:
        _merge_summary(total, check_database(profile, folder, db, work))
    return total


def rebuild_family(
    family: str,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    members = family_profiles(family)
    if len(members) < 2:
        raise UnpdfError(f"Family '{family}' needs at least two approved profiles.", exit_code=1)
    total = Summary()
    for profile in members:
        _merge_summary(total, rebuild_database(profile, folder, db, work))
    return total


def check_database(
    profile,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    _source, db_path, work_root = resolve_paths(profile, folder, db, work)
    if not db_path.exists():
        raise UnpdfError(f"No database at {db_path}.", exit_code=1)

    contract = load_profile(profile)
    conn = sqlite3.connect(db_path)
    try:
        pipeline.ensure_schema(conn)
        profile.ensure(conn)
        docs = conn.execute(
            "SELECT doc_id, file FROM docs WHERE format = ? ORDER BY doc_id",
            (profile.name,),
        ).fetchall()
        for doc_id, _filename in docs:
            pipeline.validate_document(
                conn,
                profile,
                contract,
                doc_id,
                pipeline.collect_doc_values(conn, doc_id),
            )
        profile.rebuild(conn, work_root)
        conn.commit()
        return summarize(conn, profile.name, documents=len(docs))
    finally:
        conn.close()


def rebuild_database(
    profile,
    folder: str | Path = ".",
    db: str | Path | None = None,
    work: str | Path | None = None,
) -> Summary:
    _source, db_path, work_root = resolve_paths(profile, folder, db, work)
    if not db_path.exists():
        raise UnpdfError(f"No database at {db_path}.", exit_code=1)

    conn = sqlite3.connect(db_path)
    try:
        pipeline.ensure_schema(conn)
        profile.ensure(conn)
        result = profile.rebuild(conn, work_root)
        conn.commit()
        summary = summarize(conn, profile.name, documents=int(result.get("documents", 0)))
        return summary
    finally:
        conn.close()


def summarize(conn: sqlite3.Connection, profile_name: str, documents: int) -> Summary:
    counts = dict(
        conn.execute(
            "SELECT status, COUNT(*) FROM _field_status WHERE format = ? GROUP BY status",
            (profile_name,),
        ).fetchall()
    )
    review_rows = conn.execute(
        """
        SELECT d.file, s.field, s.reason
        FROM _field_status s JOIN docs d USING (doc_id)
        WHERE s.format = ? AND s.status = 'review'
        ORDER BY d.file, s.field
        """,
        (profile_name,),
    ).fetchall()
    return Summary(
        documents=documents,
        accepted=int(counts.get("accepted", 0)),
        review=int(counts.get("review", 0)),
        missing=int(counts.get("missing", 0)),
        review_rows=[tuple(row) for row in review_rows],
        quarantine_rows=pipeline.quarantine_rows(conn, profile_name),
    )


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

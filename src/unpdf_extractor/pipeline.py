"""Reading PDFs into words, validating values, and storing SQLite rows.

No document layout lives here.  A PDF becomes a flat list of words with
coordinates, a contract says what to check, and this module keeps one clean row
per field plus the review and quarantine evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .errors import UnpdfError
from .extract import check_value, clean
from .profile import LayoutProfile
from .version import __version__

SCHEMA_VERSION = "4"

PageData = tuple[list[dict], set[int], list[tuple[float, float]]]


# ------------------------------------------------------------------- words


def text_page_words(page, page_no: int) -> list[dict]:
    words = []
    for word in page.extract_words(split_at_punctuation=":"):
        text = clean(word["text"])
        if not text:
            continue
        words.append(
            {
                "text": text,
                "x0": word["x0"],
                "top": word["top"],
                "x1": word["x1"],
                "bottom": word["bottom"],
                "page": page_no,
            }
        )
    return words


def page_words(page, page_no: int, doc, workdir: Path) -> tuple[list[dict], bool]:
    """Return the words on one page and whether OCR produced them."""
    few_chars = 0 < len(page.chars) < 10
    if page.chars and not (few_chars and page.images):
        return text_page_words(page, page_no), False
    if shutil.which("tesseract") is None:
        raise UnpdfError(
            "This PDF needs OCR, but Tesseract is not installed. "
            "Install Tesseract with the ara and eng language packs, then retry.",
            exit_code=3,
        )
    from .ocr import ocr_page_words

    words = ocr_page_words(doc, page_no, (page.width, page.height), workdir)
    if words or not page.chars:
        return words, True
    return text_page_words(page, page_no), False


def words_for_pdf(path: Path, workdir: Path) -> PageData:
    """Return (words, OCR page numbers, page sizes) for one PDF."""
    import pdfplumber
    import pypdfium2 as pdfium

    words: list[dict] = []
    ocr_pages: set[int] = set()
    page_sizes: list[tuple[float, float]] = []
    doc = pdfium.PdfDocument(str(path))
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                found, used_ocr = page_words(page, page_no, doc, workdir)
                words.extend(found)
                page_sizes.append((float(page.width), float(page.height)))
                if used_ocr:
                    ocr_pages.add(page_no)
    finally:
        doc.close()
    return words, ocr_pages, page_sizes


def temp_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="unpdf_pages_"))


# -------------------------------------------------------------- validation


def validate_document(
    conn: sqlite3.Connection,
    profile_name: str,
    contract: LayoutProfile,
    doc_id: int,
    values: dict[str, list[str]],
) -> None:
    """Write one status row per field and refresh the document counters."""
    fields = {field.name: field for field in contract.fields}
    required = {field.name for field in contract.fields if field.required}
    statuses = []
    for name in sorted(set(values) | set(fields)):
        found = values.get(name, [])
        kind = fields[name].kind if name in fields else "text"
        if not found:
            if name in required:
                status, reason = "review", "required field is empty"
            else:
                status, reason = "missing", "no value"
        else:
            reason = None
            for value in found:
                reason = check_value(str(value), kind)
                if reason:
                    break
            status = "review" if reason else "accepted"
        statuses.append((doc_id, profile_name, name, status, reason or ""))

    conn.execute(
        "DELETE FROM _field_status WHERE doc_id = ? AND substr(field, 1, 2) <> '__'", (doc_id,)
    )
    conn.executemany("INSERT INTO _field_status VALUES (?, ?, ?, ?, ?)", statuses)
    conn.execute(
        "UPDATE docs SET review_count = ?, missing = ? WHERE doc_id = ?",
        (
            sum(1 for item in statuses if item[3] == "review"),
            sum(1 for item in statuses if item[3] == "missing"),
            doc_id,
        ),
    )


# ----------------------------------------------------------------- storage


def split_known(pdfs: list[Path], db_path: Path) -> tuple[list[tuple[Path, str]], list[Path]]:
    """Split PDFs into (new, digest) pairs and files already in the database."""
    known = _known_hashes(db_path)
    fresh: list[tuple[Path, str]] = []
    skipped: list[Path] = []
    for pdf in pdfs:
        digest = hashlib.sha256(Path(pdf).read_bytes()).hexdigest()
        if digest in known:
            skipped.append(pdf)
        else:
            fresh.append((pdf, digest))
    return fresh, skipped


def _known_hashes(db_path: Path) -> set[str]:
    if not Path(db_path).exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='docs'").fetchone():
            return set()
        return {row[0] for row in conn.execute("SELECT sha256 FROM docs")}
    finally:
        conn.close()


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs (
            doc_id INTEGER PRIMARY KEY,
            format TEXT, file TEXT, sha256 TEXT UNIQUE, added_at TEXT,
            rows INTEGER, missing INTEGER, review_count INTEGER, ocr INTEGER
        );
        CREATE TABLE IF NOT EXISTS _field_status (
            doc_id INTEGER, format TEXT, field TEXT, status TEXT, reason TEXT,
            PRIMARY KEY (doc_id, field)
        );
        CREATE TABLE IF NOT EXISTS extracted_fields (
            doc_id INTEGER, field TEXT, value TEXT, page INTEGER, bbox TEXT,
            method TEXT, confidence REAL,
            PRIMARY KEY (doc_id, field)
        );
        CREATE TABLE IF NOT EXISTS quarantine (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT, file TEXT, sha256 TEXT, reason TEXT, page INTEGER,
            details TEXT, created_at TEXT,
            UNIQUE(profile, sha256)
        );
        CREATE TABLE IF NOT EXISTS _meta (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE VIEW IF NOT EXISTS review AS
            SELECT d.file, s.format, s.field, s.status, s.reason
            FROM _field_status s JOIN docs d USING (doc_id)
            WHERE s.status = 'review';
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(docs)")}
    if "ocr" not in columns:
        conn.execute("ALTER TABLE docs ADD COLUMN ocr INTEGER")
    if "review_count" not in columns:
        conn.execute("ALTER TABLE docs ADD COLUMN review_count INTEGER")
    conn.execute(
        "INSERT OR REPLACE INTO _meta (key, value) VALUES ('tool_version', ?), ('schema_version', ?)",
        (__version__, SCHEMA_VERSION),
    )


def insert_fields(conn: sqlite3.Connection, doc_id: int, values: dict) -> None:
    for value in values.values():
        conn.execute(
            "INSERT OR REPLACE INTO extracted_fields (doc_id, field, value, page, bbox, method, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (doc_id, value.name, value.value, value.page, json.dumps(value.box), value.method, None),
        )


def stored_values(conn: sqlite3.Connection, doc_id: int) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    rows = conn.execute(
        "SELECT field, value FROM extracted_fields WHERE doc_id = ?", (doc_id,)
    ).fetchall()
    for field, value in rows:
        if value not in (None, ""):
            values.setdefault(field, []).append(value)
    return values


def quarantine(
    conn: sqlite3.Connection,
    work_root: Path,
    profile_name: str,
    pdf: Path,
    digest: str,
    reason: str,
    page: int | None = None,
    details: tuple[str, ...] = (),
) -> None:
    """Record why one PDF was rejected, in the database and as JSON evidence."""
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT OR REPLACE INTO quarantine
          (profile, file, sha256, reason, page, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (profile_name, pdf.name, digest, reason, page, json.dumps(list(details)), created),
    )
    folder = work_root / "quarantine"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pdf.stem}.json").write_text(
        json.dumps(
            {
                "profile": profile_name,
                "file": pdf.name,
                "sha256": digest,
                "reason": reason,
                "page": page,
                "details": list(details),
                "created_at": created,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def quarantine_rows(conn: sqlite3.Connection, profile_name: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT file, reason FROM quarantine WHERE profile = ? ORDER BY id",
        (profile_name,),
    )
    return [(row[0], row[1]) for row in rows]


# The work folder holds the profile snapshot and one evidence file per document.


def write_evidence(work_root: Path, pdf: Path, words: list[dict], values: dict) -> None:
    """Write the words and extracted fields for one accepted document."""
    folder = work_root / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{pdf.stem}_words.json").write_text(
        json.dumps(words, ensure_ascii=False), encoding="utf-8"
    )
    (folder / f"{pdf.stem}_fields.json").write_text(
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

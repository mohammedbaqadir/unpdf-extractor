"""PDF primitives, field validation, and the generic SQLite schema.

This module does not know any document layout. It turns a PDF into words with
coordinates, validates values supplied by a profile, and stores one clean row
per field. Structure comes from the profile contract.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .errors import UnpdfError
from .version import __version__

SCHEMA_VERSION = "4"

OCR_LANG = "ara+eng"
OCR_DPI = 400
OCR_PSM = 12
OCR_TILE_PSM = 6
OCR_TILES = (3, 4)
OCR_TILE_PAD = 60
OCR_MIN_CONF = 30.0


def norm_text(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.lower(), flags=re.UNICODE)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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
                "size": (word["x1"] - word["x0"]) / max(len(text), 1),
                "page": page_no,
            }
        )
    return words


def render_page(doc, page_no: int, prefix: Path, dpi: int = OCR_DPI) -> Path:
    image = doc[page_no - 1].render(scale=dpi / 72).to_pil()
    out = prefix.with_suffix(".jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, quality=90)
    return out


def tsv_words(image_path: Path, psm: int = OCR_PSM) -> list[tuple[str, float, float, float, float, float]]:
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", OCR_LANG, "--psm", str(psm), "-c", "tessedit_create_tsv=1"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    rows = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 12 or parts[0] != "5":
            continue
        text = clean(parts[11])
        if not text:
            continue
        try:
            confidence = float(parts[10])
            left, top, width, height = (float(value) for value in parts[6:10])
        except ValueError:
            continue
        if confidence < OCR_MIN_CONF:
            continue
        rows.append((text, left, top, width, height, confidence))
    return rows


def expand_token(text: str, left: float, top: float, width: float, height: float) -> list[tuple[str, float, float, float, float]]:
    parts = text.split()
    if len(parts) <= 1:
        return [(text, left, top, width, height)]
    total = sum(len(part) for part in parts) + (len(parts) - 1)
    out = []
    cursor = left
    for part in parts:
        piece = width * len(part) / total
        out.append((part, cursor, top, piece, height))
        cursor += piece + width / total
    return out


def normalize_ocr_words(words: list[dict]) -> list[dict]:
    expanded: list[dict] = []
    for word in words:
        width = word["x1"] - word["x0"]
        height = word["bottom"] - word["top"]
        for piece, px, py, pw, ph in expand_token(word["text"], word["x0"], word["top"], width, height):
            expanded.append(
                {
                    "text": piece,
                    "x0": px,
                    "top": py,
                    "x1": px + pw,
                    "bottom": py + ph,
                    "size": pw / max(len(piece), 1),
                    "page": word["page"],
                }
            )

    kept: list[dict] = []
    for word in expanded:
        norm = norm_text(word["text"])
        if not norm:
            continue
        duplicate = any(
            norm_text(other["text"]) == norm
            and abs(other["x0"] - word["x0"]) < 25
            and abs(other["top"] - word["top"]) < 6
            for other in kept
        )
        if not duplicate:
            kept.append(word)
    return kept


def ocr_page_words(doc, page_no: int, page_size: tuple[float, float], workdir: Path) -> list[dict]:
    if shutil.which("tesseract") is None:
        raise UnpdfError(
            "This PDF needs OCR, but Tesseract is not installed. "
            "Install Tesseract with the ara and eng language packs, then retry.",
            exit_code=3,
        )
    try:
        from .ocr import ocr_page_words as improved_ocr
    except ImportError:
        improved_ocr = None
    if improved_ocr is not None:
        try:
            return normalize_ocr_words(improved_ocr(doc, page_no, page_size, workdir))
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the batch
            print(f"[warn] dense OCR failed ({type(exc).__name__}: {exc}) — using built-in OCR")
    from PIL import Image

    image_path = render_page(doc, page_no, workdir / f"p{page_no}")
    with Image.open(image_path) as handle:
        image = handle.convert("L")
        img_w, img_h = image.size

    raw = tsv_words(image_path)
    collected: list[tuple[str, float, float, float, float, float]] = []
    for text, left, top, width, height, confidence in raw:
        for piece, px, py, pw, ph in expand_token(text, left, top, width, height):
            collected.append((piece, px, py, pw, ph, confidence))

    cols, rows = OCR_TILES
    tile_w, tile_h = img_w // cols, img_h // rows
    for cy in range(rows):
        for cx in range(cols):
            box = (
                max(0, cx * tile_w - OCR_TILE_PAD),
                max(0, cy * tile_h - OCR_TILE_PAD),
                min(img_w, (cx + 1) * tile_w + OCR_TILE_PAD),
                min(img_h, (cy + 1) * tile_h + OCR_TILE_PAD),
            )
            tile_path = workdir / f"p{page_no}_t{cx}_{cy}.jpg"
            image.crop(box).save(tile_path, quality=90)
            for text, left, top, width, height, confidence in tsv_words(tile_path, OCR_TILE_PSM):
                for piece, px, py, pw, ph in expand_token(text, left, top, width, height):
                    collected.append((piece, px + box[0], py + box[1], pw, ph, confidence))

    kept: list[tuple[str, float, float, float, float, float]] = []
    for text, left, top, width, height, confidence in collected:
        norm = re.sub(r"\W+", "", text.lower())
        duplicate = False
        for index, (other, ox, oy, _ow, _oh, other_confidence) in enumerate(kept):
            if re.sub(r"\W+", "", other.lower()) == norm and abs(left - ox) < 60 and abs(top - oy) < 40:
                if confidence > other_confidence:
                    kept[index] = (text, left, top, width, height, confidence)
                duplicate = True
                break
        if not duplicate:
            kept.append((text, left, top, width, height, confidence))

    page_w, page_h = page_size
    if not img_w or not img_h:
        return []
    sx, sy = page_w / img_w, page_h / img_h

    words = []
    for text, left, top, width, height, _confidence in kept:
        x0, y0 = left * sx, top * sy
        x1, y1 = (left + width) * sx, (top + height) * sy
        words.append(
            {
                "text": text,
                "x0": x0,
                "top": y0,
                "x1": x1,
                "bottom": y1,
                "size": (x1 - x0) / max(len(text), 1),
                "page": page_no,
            }
        )
    return words


def page_words(page, page_no: int, doc, workdir: Path) -> tuple[list[dict], str]:
    few_chars = 0 < len(page.chars) < 10
    if page.chars and not (few_chars and page.images):
        return text_page_words(page, page_no), "text"
    ocr = ocr_page_words(doc, page_no, (page.width, page.height), workdir)
    if ocr or not page.chars:
        return ocr, "ocr"
    return text_page_words(page, page_no), "text"


def words_for_pdf(path: Path, workdir: Path) -> tuple[list[dict], int, list[tuple[float, float]]]:
    import pdfplumber
    import pypdfium2 as pdfium

    words: list[dict] = []
    ocr_pages = 0
    page_sizes: list[tuple[float, float]] = []
    doc = pdfium.PdfDocument(str(path))
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page_no, page in enumerate(pdf.pages, start=1):
                found, source = page_words(page, page_no, doc, workdir)
                words.extend(found)
                page_sizes.append((float(page.width), float(page.height)))
                if source == "ocr":
                    ocr_pages += 1
    finally:
        doc.close()
    return words, ocr_pages, page_sizes


# ---------------------------------------------------------------- text repair


ARABIC_RANGES = ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))


def is_arabic(ch: str) -> bool:
    code = ord(ch)
    return any(start <= code <= end for start, end in ARABIC_RANGES)


def has_presentation_forms(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if 0xFB50 <= code <= 0xFDFF or 0xFE70 <= code <= 0xFEFF:
            if unicodedata.normalize("NFKC", ch) != ch:
                return True
    return False


def repair_arabic(text: str) -> str:
    """Turn visually-ordered, shaped Arabic into logical order."""
    if not has_presentation_forms(text):
        return text

    presentation = 0
    for ch in text:
        code = ord(ch)
        if (0xFB50 <= code <= 0xFDFF or 0xFE70 <= code <= 0xFEFF) and unicodedata.normalize("NFKC", ch) != ch:
            presentation += 1
    base_letters = sum(1 for ch in text if 0x0600 <= ord(ch) <= 0x06FF and ch.isalpha())
    if base_letters > presentation:
        return text

    runs: list[tuple[str, str]] = []
    current = ""
    current_kind: str | None = None
    for ch in text:
        if unicodedata.category(ch).startswith("M"):
            kind = current_kind or "rtl"
        elif ch.isdigit():
            kind = "ltr"
        elif not ch.isalnum():
            kind = "neutral"
        else:
            kind = "rtl" if is_arabic(ch) else "ltr"
        if current_kind == kind:
            current += ch
        else:
            if current:
                runs.append((current_kind, current))
            current, current_kind = ch, kind
    if current:
        runs.append((current_kind, current))

    resolved: list[list[str]] = []
    for index, (kind, chunk) in enumerate(runs):
        if kind != "neutral":
            resolved.append([kind, chunk])
            continue
        previous = next((runs[i][0] for i in range(index - 1, -1, -1) if runs[i][0] != "neutral"), None)
        following = next((runs[i][0] for i in range(index + 1, len(runs)) if runs[i][0] != "neutral"), None)
        resolved.append([previous if previous == following and previous else "neutral", chunk])

    merged: list[list[str]] = []
    for kind, chunk in resolved:
        if merged and merged[-1][0] == kind:
            merged[-1][1] += chunk
        else:
            merged.append([kind, chunk])

    logical = "".join(chunk[::-1] if kind == "rtl" else chunk for kind, chunk in reversed(merged))
    return unicodedata.normalize("NFKC", logical)


# ---------------------------------------------------------------- validation


def parse_date(value: str):
    value = re.sub(r"\s*:\s*", ":", str(value).strip())
    for pattern in (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(value, pattern)
        except (ValueError, TypeError):
            continue
    return None


def check_value(value: str, kind: str) -> str | None:
    kind = (kind or "text").strip().lower()
    if kind == "digits":
        if not re.fullmatch(r"\d+", value):
            return "not digits"
    elif kind in {"number", "decimal"}:
        try:
            float(value.replace(",", ""))
        except ValueError:
            return "not a number"
    elif kind == "integer":
        if not re.fullmatch(r"\d+", value):
            return "not an integer"
    elif kind == "date":
        if not parse_date(value):
            return "invalid date"
    return None


def validate_document(
    conn: sqlite3.Connection,
    profile,
    contract,
    doc_id: int,
    values: dict,
) -> None:
    fmt = profile.name
    fields = {field.name: field for field in contract.fields}
    required = {field.name for field in contract.fields if field.required}
    names = set(values) | set(fields)
    statuses = []
    for name in sorted(names):
        found = values.get(name, [])
        field = fields.get(name)
        kind = field.kind if field else "text"
        if not found:
            if name in required:
                status, reason = "review", "required field is empty"
            else:
                status, reason = "missing", "no value"
        else:
            reason = None
            unique = {str(value) for value in found}
            if len(unique) > 1:
                reason = "inconsistent values: " + " | ".join(sorted(unique)[:3])
            if not reason:
                for value in found:
                    reason = check_value(str(value), kind)
                    if reason:
                        break
            status = "review" if reason else "accepted"
        statuses.append((doc_id, fmt, name, status, reason or ""))

    conn.execute(
        "DELETE FROM _field_status WHERE doc_id = ? AND substr(field, 1, 2) <> '__'", (doc_id,)
    )
    conn.executemany("INSERT INTO _field_status VALUES (?, ?, ?, ?, ?)", statuses)
    review_count = sum(1 for item in statuses if item[3] == "review")
    missing_count = sum(1 for item in statuses if item[3] == "missing")
    conn.execute(
        "UPDATE docs SET review_count = ?, missing = ? WHERE doc_id = ?",
        (review_count, missing_count, doc_id),
    )


# ---------------------------------------------------------------- storage


def known_hashes(db_path: Path) -> set[str]:
    if not Path(db_path).exists():
        return set()
    conn = sqlite3.connect(db_path)
    try:
        if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='docs'").fetchone():
            return set()
        return {row[0] for row in conn.execute("SELECT sha256 FROM docs")}
    finally:
        conn.close()


def filter_new(pdfs: list[Path], db_path: Path) -> list[Path]:
    known = known_hashes(db_path)
    fresh = []
    for pdf in pdfs:
        if hashlib.sha256(Path(pdf).read_bytes()).hexdigest() in known:
            print(f"skip  {Path(pdf).name} (already in database)")
        else:
            fresh.append(pdf)
    return fresh


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS docs (
            doc_id INTEGER PRIMARY KEY,
            format TEXT, file TEXT, sha256 TEXT UNIQUE, added_at TEXT,
            records INTEGER, rows INTEGER, missing INTEGER, review_count INTEGER
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
            (
                doc_id,
                value.name,
                value.value,
                value.page,
                json.dumps(value.box),
                value.method,
                1.0,
            ),
        )


def collect_doc_values(conn: sqlite3.Connection, doc_id: int) -> dict:
    values: dict[str, list] = {}
    try:
        rows = conn.execute(
            "SELECT field, value FROM extracted_fields WHERE doc_id = ?", (doc_id,)
        ).fetchall()
    except sqlite3.OperationalError:
        return values
    for field, value in rows:
        if value not in (None, ""):
            values.setdefault(field, []).append(value)
    return values


def record_quarantine(
    conn: sqlite3.Connection,
    profile,
    pdf: Path,
    digest: str,
    reason: str,
    page: int | None = None,
    details: tuple[str, ...] = (),
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO quarantine
          (profile, file, sha256, reason, page, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            profile.name,
            pdf.name,
            digest,
            reason,
            page,
            json.dumps(list(details), ensure_ascii=False),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )


def write_quarantine_artifact(
    work_root: Path,
    profile,
    pdf: Path,
    digest: str,
    reason: str,
    page: int | None = None,
    details: tuple[str, ...] = (),
) -> Path:
    folder = Path(work_root) / "quarantine"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pdf.stem}.json"
    path.write_text(
        json.dumps(
            {
                "profile": profile.name,
                "file": pdf.name,
                "sha256": digest,
                "reason": reason,
                "page": page,
                "details": list(details),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def quarantine_rows(conn: sqlite3.Connection, profile_name: str) -> list[tuple[str, str]]:
    try:
        return [
            (row[0], row[1])
            for row in conn.execute(
                "SELECT file, reason FROM quarantine WHERE profile = ? ORDER BY id",
                (profile_name,),
            )
        ]
    except sqlite3.OperationalError:
        return []


def temp_workdir() -> Path:
    return Path(tempfile.mkdtemp(prefix="unpdf_pages_"))

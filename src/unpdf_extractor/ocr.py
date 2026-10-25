"""OCR a scanned PDF page into words with coordinates, tuned for dense forms.

Dense forms (tables, ruled cells, Arabic + English) lose columns when a page is
upscaled too far or OCR'd with sparse-text layout analysis. This module uses:

  * render at 300 DPI
  * remove long horizontal/vertical table rules before OCR (scipy.ndimage)
  * run Tesseract twice on the cleaned image, PSM 3, ``ara+eng``:
      - grayscale cleaned (keeps antialiasing)
      - binary cleaned (crisper small digits)
  * union the words, split multi-word TSV tokens, drop confidence < 40,
    dedupe by normalized text + position, then resolve overlapping readings,
    preferring a whole word over split pieces and then higher confidence.

Contract: each word is ``{text, x0, top, x1, bottom, size, page}`` in page
points with a top-left origin and a 1-based page number.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from scipy import ndimage

OCR_DPI = 300
OCR_PSM = 3
OCR_LANG = "ara+eng"
OCR_MIN_CONF = 40.0
OCR_RULE_THRESHOLD = 160
OCR_RULE_MIN_LEN = 68  # pixels at 300 DPI (~16 pt)
OCR_RULE_THICKNESS = 3
OCR_DEDUPE_FRAC = 0.004  # of page width, in pixels


def _render(doc, page_no: int, dpi: int) -> Image.Image:
    page = doc[page_no - 1]
    image = page.render(scale=dpi / 72).to_pil()
    if image.mode not in ("L", "RGB"):
        image = image.convert("RGB")
    return image


def _clean_variants(image: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Return (grayscale, binary) copies with long table rules whitened out."""
    gray = ImageOps.grayscale(image)
    array = np.asarray(gray)
    dark = array < OCR_RULE_THRESHOLD

    horizontal = ndimage.binary_opening(
        dark, structure=np.ones((OCR_RULE_THICKNESS, OCR_RULE_MIN_LEN), dtype=bool)
    )
    vertical = ndimage.binary_opening(
        dark, structure=np.ones((OCR_RULE_MIN_LEN, OCR_RULE_THICKNESS), dtype=bool)
    )
    rules = ndimage.binary_dilation(horizontal | vertical, structure=np.ones((3, 3), dtype=bool))

    soft = array.copy()
    soft[rules] = 255
    clean_gray = Image.fromarray(soft)

    hard = dark & ~rules
    clean_binary = Image.fromarray(np.where(hard, 0, 255).astype(np.uint8))
    return clean_gray, clean_binary


def _clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # Cell rules sometimes stick to a value ("809331527,"); keep the value.
    return text.strip(",;|").strip()


def _tesseract_words(image_path: Path, psm: int, lang: str) -> list[dict]:
    result = subprocess.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            lang,
            "--psm",
            str(psm),
            "-c",
            "tessedit_create_tsv=1",
            "-c",
            "preserve_interword_spaces=1",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    words = []
    for line in result.stdout.splitlines():
        if not line.startswith("5\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        text = _clean_text(parts[11])
        if not text:
            continue
        try:
            confidence = float(parts[10])
            left, top, width, height = (float(value) for value in parts[6:10])
        except ValueError:
            continue
        if confidence < OCR_MIN_CONF or width <= 0 or height <= 0:
            continue
        words.append(
            {
                "text": text,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
                "conf": confidence,
            }
        )
    return words


def _split_token(word: dict) -> list[dict]:
    """Tesseract sometimes emits a whole cell as one token; make real words."""
    parts = word["text"].split()
    if len(parts) <= 1:
        return [word]

    total = sum(len(part) for part in parts) + (len(parts) - 1)
    cursor = word["left"]
    out = []
    for part in parts:
        piece = word["width"] * len(part) / total
        out.append({**word, "text": part, "left": cursor, "width": piece})
        cursor += piece + word["width"] / total
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", "", text.lower(), flags=re.UNICODE)


def _dedupe(words: list[dict], distance: float) -> list[dict]:
    """Overlapping passes and split tokens rediscover words; keep the best copy."""
    kept: list[dict] = []
    for word in words:
        key = _norm(word["text"])
        if not key:
            continue
        duplicate = False
        for index, other in enumerate(kept):
            if (
                _norm(other["text"]) == key
                and abs(word["left"] - other["left"]) < distance
                and abs(word["top"] - other["top"]) < distance
            ):
                if word["conf"] > other["conf"]:
                    kept[index] = word
                duplicate = True
                break
        if not duplicate:
            kept.append(word)
    return kept


def _resolve_overlaps(words: list[dict]) -> list[dict]:
    """Two passes can read the same ink differently; keep one reading per box.

    Exact duplicates are already merged.  This step drops a token whose box is
    mostly inside a longer token from another pass ("Shi" / "p" inside "Ship",
    or a low-confidence misread of the same cell).  Longer text wins over a
    fragment, then confidence decides between equal-length readings.
    """
    ordered = sorted(words, key=lambda word: (len(_norm(word["text"])), word["conf"]), reverse=True)
    kept: list[dict] = []
    for word in ordered:
        left, top = word["left"], word["top"]
        right, bottom = left + word["width"], top + word["height"]
        area = max(word["width"] * word["height"], 1.0)
        conflict = None
        for index, other in enumerate(kept):
            o_left, o_top = other["left"], other["top"]
            o_right, o_bottom = o_left + other["width"], o_top + other["height"]
            inter_w = max(0.0, min(right, o_right) - max(left, o_left))
            inter_h = max(0.0, min(bottom, o_bottom) - max(top, o_top))
            if not inter_w or not inter_h:
                continue
            inter = inter_w * inter_h
            other_area = max(other["width"] * other["height"], 1.0)
            contained = inter / min(area, other_area)
            iou = inter / (area + other_area - inter)
            if contained >= 0.8 or iou >= 0.5:
                conflict = index
                break
        if conflict is None:
            kept.append(word)
        else:
            other = kept[conflict]
            if len(_norm(word["text"])) > len(_norm(other["text"])) or (
                len(_norm(word["text"])) == len(_norm(other["text"])) and word["conf"] > other["conf"]
            ):
                kept[conflict] = word
    return kept


def ocr_page_words(doc, page_no: int, page_size: tuple[float, float], workdir: Path) -> list[dict]:
    """OCR one page into words; see the module docstring for the configuration."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    image = _render(doc, page_no, OCR_DPI)
    image_w, image_h = image.size
    if not image_w or not image_h:
        return []

    clean_gray, clean_binary = _clean_variants(image)
    sources = [
        (clean_gray, f"p{page_no}_clean_gray.png"),
        (clean_binary, f"p{page_no}_clean_bin.png"),
    ]

    collected: list[dict] = []
    for variant, name in sources:
        path = workdir / name
        variant.save(path)
        for word in _tesseract_words(path, OCR_PSM, OCR_LANG):
            collected.extend(_split_token(word))

    distance = max(6.0, image_w * OCR_DEDUPE_FRAC)
    kept = _resolve_overlaps(_dedupe(collected, distance))

    page_w, page_h = page_size
    sx, sy = page_w / image_w, page_h / image_h
    words = []
    for word in kept:
        x0 = min(max(word["left"] * sx, 0.0), page_w)
        top = min(max(word["top"] * sy, 0.0), page_h)
        x1 = min(max((word["left"] + word["width"]) * sx, 0.0), page_w)
        bottom = min(max((word["top"] + word["height"]) * sy, 0.0), page_h)
        if not (0 <= x0 < x1 <= page_w and 0 <= top < bottom <= page_h):
            continue
        text = word["text"]
        words.append(
            {
                "text": text,
                "x0": x0,
                "top": top,
                "x1": x1,
                "bottom": bottom,
                "size": (x1 - x0) / max(len(text), 1),
                "page": page_no,
            }
        )
    words.sort(key=lambda word: (word["top"], word["x0"]))
    return words

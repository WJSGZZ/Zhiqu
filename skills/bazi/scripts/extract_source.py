#!/usr/bin/env python3
"""Inspect/extract PDF text and optionally OCR image-only pages on macOS.

OCR output is a search aid, never a citable edition. Preserve the PDF hash and
page markers so every consequential quotation can be checked against the page.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pdfplumber
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pdfplumber is required; use the bundled Codex Python runtime") from exc


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_pdf(path: Path) -> dict:
    pages = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            pages.append({"page": index, "characters": len(text.strip()), "has_text": bool(text.strip())})
    text_pages = sum(1 for p in pages if p["has_text"])
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "pages": len(pages),
        "text_pages": text_pages,
        "image_only_pages": len(pages) - text_pages,
        "text_layer_status": "complete" if text_pages == len(pages) else "partial" if text_pages else "absent",
        "page_details": pages,
    }


def extract_text_layer(path: Path) -> str:
    chunks = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, 1):
            chunks.append(f"\n\n<<<PAGE {index}>>>\n")
            chunks.append(page.extract_text() or "")
    return "".join(chunks).lstrip()


def ocr_pdf(path: Path, dpi: int) -> str:
    renderer = shutil.which("pdftoppm")
    swift = shutil.which("swift")
    helper = Path(__file__).with_name("ocr_image.swift")
    if not renderer or not swift:
        raise RuntimeError("OCR requires pdftoppm and swift on macOS")
    chunks = []
    with tempfile.TemporaryDirectory(prefix="bazi-ocr-") as temp:
        prefix = Path(temp) / "page"
        subprocess.run([renderer, "-r", str(dpi), "-png", str(path), str(prefix)], check=True)
        images = sorted(Path(temp).glob("page-*.png"))
        if not images:
            raise RuntimeError("pdftoppm produced no page images")
        for index, image in enumerate(images, 1):
            proc = subprocess.run([swift, str(helper), str(image)], check=True, text=True, capture_output=True)
            chunks.extend((f"\n\n<<<PAGE {index} OCR_UNVERIFIED>>>\n", proc.stdout.strip()))
    return "".join(chunks).lstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description="检测 PDF 文字层并提取或 OCR")
    parser.add_argument("pdf")
    parser.add_argument("--mode", choices=("inspect", "text", "ocr", "auto"), default="inspect")
    parser.add_argument("--output", help="text/ocr/auto 的输出文件；不传则写 stdout")
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()
    path = Path(args.pdf)
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    try:
        report = inspect_pdf(path)
        if args.mode == "inspect":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        mode = args.mode
        if mode == "auto":
            mode = "text" if report["text_layer_status"] == "complete" else "ocr"
        text = extract_text_layer(path) if mode == "text" else ocr_pdf(path, args.dpi)
        header = (
            f"SOURCE_SHA256: {report['sha256']}\n"
            f"EXTRACTION_MODE: {mode}\n"
            f"TEXT_STATUS: {'SEARCH_AID_UNVERIFIED' if mode == 'ocr' else 'EXTRACTED_TEXT_REQUIRES_PAGE_CHECK'}\n\n"
        )
        result = header + text
        if args.output:
            Path(args.output).write_text(result, encoding="utf-8")
        else:
            print(result, end="")
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

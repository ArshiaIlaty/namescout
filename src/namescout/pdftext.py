"""Pluggable PDF -> text engines.

- pdfminer  : built-in, fast, good for normal text PDFs (the default fallback).
- docling   : IBM's document understanding - great structure on complex/scientific
              PDFs.  `pip install "namescout[docling]"`
- marker    : high-quality PDF -> markdown.  `pip install "namescout[marker]"`

Both docling and marker download models on first use, so they only work where
HuggingFace is reachable (e.g. your laptop, not a locked-down box).
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional


def resolve_pdf_engine(engine: Optional[str] = None) -> str:
    """Effective PDF engine, verifying the backend is importable."""
    requested = (engine or os.environ.get("NAMESCOUT_PDF_ENGINE") or "auto").lower()
    if requested == "pdfminer":
        return "pdfminer"
    if requested in ("docling", "auto") and _has("docling"):
        return "docling"
    if requested in ("marker", "auto") and _has("marker"):
        return "marker"
    return "pdfminer"


def pdf_to_text(path: str, max_pages: Optional[int] = None, engine: Optional[str] = None) -> str:
    """Extract text from a PDF using the selected engine (falls back to pdfminer).

    max_pages is honoured by pdfminer only; docling/marker convert the whole
    document (callers still region-cut at the Abstract afterwards).
    """
    eng = resolve_pdf_engine(engine)
    if eng == "docling":
        text = _docling_text(path)
        if text:
            return text
    elif eng == "marker":
        text = _marker_text(path)
        if text:
            return text
    return _pdfminer_text(path, max_pages)


def _has(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def _pdfminer_text(path: str, max_pages: Optional[int]) -> str:
    from pdfminer.high_level import extract_text

    return extract_text(path, maxpages=max_pages or 0)


@lru_cache(maxsize=1)
def _docling_converter():
    from docling.document_converter import DocumentConverter  # type: ignore

    return DocumentConverter()


def _docling_text(path: str) -> Optional[str]:
    try:
        result = _docling_converter().convert(path)
        return result.document.export_to_markdown()
    except Exception:
        return None


@lru_cache(maxsize=1)
def _marker_converter():
    # marker's API moves between versions; import lazily and tolerate failure.
    from marker.converters.pdf import PdfConverter  # type: ignore
    from marker.models import create_model_dict  # type: ignore

    return PdfConverter(artifact_dict=create_model_dict())


def _marker_text(path: str) -> Optional[str]:
    try:
        from marker.output import text_from_rendered  # type: ignore

        rendered = _marker_converter()(path)
        text, _, _ = text_from_rendered(rendered)
        return text
    except Exception:
        return None

"""Route an input (file path, URL, arXiv id, DOI or raw text) to a reader."""
from __future__ import annotations

import os
import re
import sys
from typing import List, Optional

from .models import Extraction
from . import readers, web

# A loose "looks like an arXiv id or DOI on its own" test for bare CLI args.
_BARE_ARXIV = re.compile(r"^(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?$", re.I)
_BARE_DOI = re.compile(r"^(?:doi:)?10\.\d{4,9}/\S+$", re.I)


def classify(arg: str) -> str:
    """Return one of: url, arxiv, doi, pdf, docx, csv, textfile, raw."""
    s = arg.strip()
    if os.path.isfile(s):
        ext = os.path.splitext(s)[1].lower()
        return {
            ".pdf": "pdf",
            ".docx": "docx",
            ".csv": "csv",
            ".html": "html",
            ".htm": "html",
        }.get(ext, "textfile")
    if s.lower().startswith(("http://", "https://")):
        if "arxiv.org" in s.lower():
            return "arxiv"
        if "doi.org" in s.lower() or web.DOI_RE.search(s):
            return "doi"
        return "url"
    if _BARE_ARXIV.match(s):
        return "arxiv"
    if _BARE_DOI.match(s):
        return "doi"
    return "raw"


def _process_link_list(links: List[str], source: str, mailto: Optional[str]) -> Extraction:
    """Process a list of links, merging authors and warning about any failures."""
    merged = Extraction(source=source)
    for link in links:
        try:
            ex = process(link, mailto=mailto)
            merged.authors.extend(ex.authors)
        except Exception as e:
            print(f"  ! skipped {link}: {e}", file=sys.stderr)
    return merged


def process(arg: str, mailto: Optional[str] = None) -> Extraction:
    """Extract authors from a single input, dispatching on its detected type."""
    kind = classify(arg)
    s = arg.strip()

    if kind == "pdf":
        return readers.read_pdf(s)
    if kind == "docx":
        return readers.read_docx(s)
    if kind == "csv":
        return readers.read_csv(s)
    if kind == "html":
        return readers.read_html_file(s)
    if kind == "textfile":
        # A .txt that is mostly URLs/DOIs/ids is a link list -> process each line.
        with open(s, encoding="utf-8", errors="replace") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        link_lines = [ln for ln in lines if classify(ln) in ("url", "arxiv", "doi")]
        if lines and len(link_lines) >= max(1, len(lines) // 2):
            return _process_link_list(link_lines, source=s, mailto=mailto)
        return readers.read_text_file(s)
    if kind == "arxiv":
        arxiv_id = web.find_arxiv_id(s) or re.sub(r"^arxiv:", "", s, flags=re.I)
        return web.fetch_arxiv(arxiv_id)
    if kind == "doi":
        doi = web.find_doi(s) or re.sub(r"^doi:", "", s, flags=re.I)
        return web.fetch_doi(doi, mailto=mailto)
    if kind == "url":
        return web.fetch_webpage(s)
    return readers.read_raw_text(s)

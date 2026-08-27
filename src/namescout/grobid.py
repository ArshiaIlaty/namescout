"""GROBID client for research-paper header extraction.

GROBID (https://github.com/kermitt2/grobid) is the gold standard for pulling the
*exact* author block out of a scholarly PDF - names, affiliations and emails -
even when the paper has no arXiv id / DOI to look up.

It runs as a separate service.  The easiest way is Docker:

    docker run --rm -t -p 8070:8070 lfoppiano/grobid:0.8.0

Then point namescout at it:

    export NAMESCOUT_GROBID_URL=http://localhost:8070      # or --grobid-url

If no URL is configured (or the server is unreachable) every function here
returns None and the caller falls back to arXiv/DOI/heuristic extraction, so
nothing breaks when GROBID isn't running.
"""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from .models import Author, Extraction

_TEI = {"t": "http://www.tei-c.org/ns/1.0"}


def grobid_url() -> Optional[str]:
    """Configured GROBID base URL, if any (env NAMESCOUT_GROBID_URL / GROBID_URL)."""
    url = os.environ.get("NAMESCOUT_GROBID_URL") or os.environ.get("GROBID_URL")
    return url.rstrip("/") if url else None


def fetch_grobid_authors(pdf_path: str, url: Optional[str] = None, timeout: int = 60) -> Optional[Extraction]:
    """POST a PDF to GROBID's header endpoint and parse the author block.

    Returns None (no exception) when GROBID isn't configured or is unreachable,
    so callers can simply try it and move on.
    """
    base = url.rstrip("/") if url else grobid_url()
    if not base:
        return None
    endpoint = f"{base}/api/processHeaderDocument"
    try:
        with open(pdf_path, "rb") as f:
            resp = requests.post(
                endpoint,
                files={"input": (os.path.basename(pdf_path), f, "application/pdf")},
                data={"consolidateHeader": "1"},
                timeout=timeout,
            )
        resp.raise_for_status()
    except Exception:
        return None
    try:
        return _parse_tei(resp.text, source=f"{pdf_path} (GROBID)")
    except Exception:
        return None


def _text(el: Optional[ET.Element]) -> Optional[str]:
    if el is None or not el.text:
        return None
    return " ".join(el.text.split()) or None


def _parse_tei(tei_xml: str, source: str) -> Extraction:
    root = ET.fromstring(tei_xml)

    title = _text(root.find(".//t:titleStmt/t:title", _TEI))

    authors: List[Author] = []
    # Header authors live under the analytic block of the source biblStruct.
    for author_el in root.findall(".//t:sourceDesc//t:biblStruct//t:author", _TEI):
        pers = author_el.find("t:persName", _TEI)
        if pers is None:
            continue
        forenames = [
            _text(fn) for fn in pers.findall("t:forename", _TEI) if _text(fn)
        ]
        surname = _text(pers.find("t:surname", _TEI))
        parts = [p for p in (forenames + [surname]) if p]
        name = " ".join(parts).strip()
        if not name:
            continue

        email = _text(author_el.find("t:email", _TEI))
        affil = _affiliation(author_el)
        authors.append(Author(name=name, affiliation=affil, email=email, source=source))

    return Extraction(authors=authors, title=title, source=source)


def _affiliation(author_el: ET.Element) -> Optional[str]:
    """Best-effort readable affiliation string for an <author> element."""
    aff = author_el.find("t:affiliation", _TEI)
    if aff is None:
        return None
    # Prefer named org units (institution/department); fall back to any orgName.
    names = [_text(o) for o in aff.findall("t:orgName", _TEI) if _text(o)]
    if names:
        # De-dup while preserving order.
        seen = []
        for n in names:
            if n not in seen:
                seen.append(n)
        return ", ".join(seen)
    settlement = _text(aff.find(".//t:settlement", _TEI))
    return settlement

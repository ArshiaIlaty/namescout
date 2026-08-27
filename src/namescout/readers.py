"""Read author names out of local files: PDF, DOCX, CSV and plain text."""
from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import List, Optional

from .models import Author, Extraction
from .names import extract_names, name_from_email
from . import web, grobid, pdftext


# --- PDF ---------------------------------------------------------------------

def _pdf_text(path: str, max_pages: Optional[int] = None) -> str:
    # Delegates to the selected PDF engine (docling/marker/pdfminer).
    return pdftext.pdf_to_text(path, max_pages=max_pages)


def read_pdf(path: str) -> Extraction:
    """Extract authors from a PDF.

    Strategy, best to worst:
      1. Find an embedded arXiv id / DOI -> fetch the exact author list online.
      2. Ask a running GROBID server for the parsed author block (if configured).
      3. Parse the "author region" (text before the Abstract) heuristically.
    """
    first_pages = _pdf_text(path, max_pages=2)

    # 1. Embedded identifier -> authoritative metadata.
    arxiv_id = web.find_arxiv_id(first_pages)
    if arxiv_id:
        try:
            ex = web.fetch_arxiv(arxiv_id)
            if ex.authors:
                ex.source = f"{path} ({ex.source})"
                return ex
        except Exception:
            pass
    doi = web.find_doi(first_pages)
    if doi:
        try:
            ex = web.fetch_doi(doi)
            if ex.authors:
                ex.source = f"{path} ({ex.source})"
                return ex
        except Exception:
            pass

    # 2. GROBID (if a server is configured/reachable) -> exact author block.
    ex = grobid.fetch_grobid_authors(path)
    if ex is not None and ex.authors:
        return ex

    # 3. Heuristic: authors live between the title and the Abstract.
    region = first_pages
    m = re.search(r"\babstract\b", first_pages, re.I)
    if m:
        region = first_pages[: m.start()]
    # Drop the first line (usually the title) to reduce noise, keep the rest.
    lines = [ln.strip() for ln in region.splitlines() if ln.strip()]
    byline = "\n".join(lines[1:]) if len(lines) > 1 else region

    names = extract_names(byline, prefer_author_list=True)
    if not names:  # nothing in the region - fall back to the whole first page
        names = extract_names(first_pages, prefer_author_list=True)

    # Pull any author emails as an extra signal / contact detail.
    emails = re.findall(r"[\w.\-+]+@[\w.\-]+\.\w+", first_pages)

    authors = [Author(name=n, source=path) for n in names]
    _attach_emails(authors, emails)
    return Extraction(authors=authors, source=path)


def _attach_emails(authors: List[Author], emails: List[str]) -> None:
    """Best-effort match of emails to authors by surname/given-name in local-part."""
    for email in emails:
        local = email.split("@", 1)[0].lower()
        for a in authors:
            if a.email:
                continue
            parts = [p.lower() for p in a.name.replace(".", "").split()]
            if any(len(p) > 2 and p in local for p in parts):
                a.email = email
                break


# --- DOCX --------------------------------------------------------------------

def read_docx(path: str) -> Extraction:
    """Read a .docx. Uses python-docx if available, else a stdlib zip fallback."""
    try:
        import docx  # type: ignore

        document = docx.Document(path)
        text = "\n".join(p.text for p in document.paragraphs)
    except Exception:
        text = _docx_text_stdlib(path)
    names = extract_names(text, prefer_author_list=True)
    return Extraction(authors=[Author(name=n, source=path) for n in names], source=path)


def _docx_text_stdlib(path: str) -> str:
    """Extract text from word/document.xml without python-docx."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    # Insert breaks for paragraph/tab tags so words don't run together.
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", " ", xml)
    return re.sub(r"<[^>]+>", "", xml)


# --- CSV ---------------------------------------------------------------------

_NAME_COLS = ("name", "author", "authors", "full name", "fullname", "researcher")
_FIRST_COLS = ("first", "first name", "firstname", "given", "given name")
_LAST_COLS = ("last", "last name", "lastname", "family", "surname", "family name")
_EMAIL_COLS = ("email", "e-mail", "mail", "email address")


def read_csv(path: str) -> Extraction:
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample)
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        rows = list(reader)
        fieldnames = [h.strip() for h in (reader.fieldnames or [])]

    return _extraction_from_rows(rows, fieldnames, path)


def _find_col(fieldnames: List[str], candidates) -> Optional[str]:
    lower = {h.lower(): h for h in fieldnames}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def _extraction_from_rows(rows, fieldnames: List[str], source: str) -> Extraction:
    authors: List[Author] = []

    name_col = _find_col(fieldnames, _NAME_COLS)
    first_col = _find_col(fieldnames, _FIRST_COLS)
    last_col = _find_col(fieldnames, _LAST_COLS)
    email_col = _find_col(fieldnames, _EMAIL_COLS)

    structured = bool(name_col or (first_col and last_col))

    for row in rows:
        email = (row.get(email_col) or "").strip() if email_col else ""
        name = ""
        if name_col:
            name = (row.get(name_col) or "").strip()
        elif first_col and last_col:
            name = f"{(row.get(first_col) or '').strip()} {(row.get(last_col) or '').strip()}".strip()
        if not name and email:
            name = name_from_email(email) or ""
        if name:
            authors.append(Author(name=name, email=email or None, source=source))

    if not structured:
        # No obvious columns - scan every cell for names.
        blob = "\n".join(
            str(v) for row in rows for v in row.values() if v
        )
        for n in extract_names(blob):
            authors.append(Author(name=n, source=source))

    return Extraction(authors=authors, source=source)


# --- plain text / raw --------------------------------------------------------

def read_html_file(path: str) -> Extraction:
    """Extract authors from a saved .html/.htm file (no network needed).

    Lets you work around a locked-down network: save the page in your browser
    (Cmd/Ctrl+S) and point namescout at the file.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        html = f.read()
    ex = web.extract_from_html(html, source=path)
    return ex


def read_text_file(path: str) -> Extraction:
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return read_raw_text(text, source=path)


def read_raw_text(text: str, source: str = "text input") -> Extraction:
    authors: List[Author] = []
    # Handle bare email lines specially so we still get a name from them.
    for line in text.splitlines():
        line = line.strip()
        if line and "@" in line and " " not in line:
            n = name_from_email(line)
            if n:
                authors.append(Author(name=n, email=line, source=source))
    for n in extract_names(text, prefer_author_list=True):
        authors.append(Author(name=n, source=source))
    return Extraction(authors=authors, source=source)

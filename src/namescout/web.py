"""Fetch author metadata from the web: arXiv, Crossref (DOI) and generic pages.

For scholarly sources we prefer structured APIs that return exact author lists
rather than scraping - this is the single biggest reliability win over guessing
from text.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional
from urllib.parse import quote

import requests

from .models import Author, Extraction
from .names import extract_names

USER_AGENT = "namescout/0.1 (https://github.com/ArshiaIlaty/namescout)"

# --- pattern detection -------------------------------------------------------

# arXiv ids: new style "2401.12345" (optional vN) or old style "math.GT/0309136".
ARXIV_ID_RE = re.compile(r"\b(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})\b")
# DOIs: 10.<registrant>/<suffix>.
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]+)\b", re.I)


def find_arxiv_id(text: str) -> Optional[str]:
    m = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+)", text, re.I)
    if m:
        return m.group(1).replace(".pdf", "")
    m = ARXIV_ID_RE.search(text)
    return m.group(1) if m else None


def find_doi(text: str) -> Optional[str]:
    m = DOI_RE.search(text)
    if not m:
        return None
    # Strip trailing punctuation that commonly clings to inline DOIs.
    return m.group(1).rstrip(".,);]")


def _trafilatura_text(html: str) -> Optional[str]:
    """Clean main-content text via trafilatura, or None if it's not installed."""
    try:
        import trafilatura  # type: ignore
    except Exception:
        return None
    try:
        return trafilatura.extract(html, include_comments=False, include_tables=True)
    except Exception:
        return None


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


# --- arXiv -------------------------------------------------------------------

def fetch_arxiv(arxiv_id: str, timeout: int = 15) -> Extraction:
    """Look up an arXiv id via the Atom API and return its exact author list."""
    arxiv_id = arxiv_id.strip().replace(".pdf", "")
    url = f"http://export.arxiv.org/api/query?id_list={quote(arxiv_id)}"
    resp = _session().get(url, timeout=timeout)
    resp.raise_for_status()

    ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(resp.content)
    entry = root.find("a:entry", ns)
    if entry is None:
        raise ValueError(f"arXiv returned no entry for id {arxiv_id!r}")

    title_el = entry.find("a:title", ns)
    title = re.sub(r"\s+", " ", title_el.text).strip() if title_el is not None and title_el.text else None

    authors: List[Author] = []
    for a in entry.findall("a:author", ns):
        name_el = a.find("a:name", ns)
        if name_el is None or not name_el.text:
            continue
        affil_el = a.find("arxiv:affiliation", ns)
        authors.append(
            Author(
                name=name_el.text.strip(),
                affiliation=affil_el.text.strip() if affil_el is not None and affil_el.text else None,
                source=f"arXiv:{arxiv_id}",
            )
        )
    return Extraction(authors=authors, title=title, source=f"arXiv:{arxiv_id}")


# --- Crossref / DOI ----------------------------------------------------------

def fetch_doi(doi: str, mailto: Optional[str] = None, timeout: int = 15) -> Extraction:
    """Resolve a DOI via the Crossref REST API for an exact author list."""
    doi = doi.strip()
    url = f"https://api.crossref.org/works/{quote(doi)}"
    params = {"mailto": mailto} if mailto else None  # Crossref "polite pool"
    resp = _session().get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    msg = resp.json().get("message", {})

    titles = msg.get("title") or []
    title = titles[0] if titles else None

    authors: List[Author] = []
    for a in msg.get("author", []):
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        name = (a.get("name") or f"{given} {family}").strip()
        if not name:
            continue
        affils = a.get("affiliation") or []
        affil = affils[0].get("name") if affils and isinstance(affils[0], dict) else None
        orcid = a.get("ORCID")
        if orcid:
            orcid = orcid.rstrip("/").split("/")[-1]  # keep the bare id
        authors.append(
            Author(name=name, affiliation=affil, orcid=orcid, source=f"doi:{doi}")
        )
    return Extraction(authors=authors, title=title, source=f"doi:{doi}")


# --- generic web page --------------------------------------------------------

def fetch_webpage(url: str, timeout: int = 20) -> Extraction:
    """Fetch a generic page and extract names.

    We first look for an embedded arXiv id / DOI and delegate to the structured
    APIs; only if that fails do we fall back to reading names out of the text.
    """
    # Browser-like headers help with sites that reject bare clients (WAF/Cloudflare).
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = _session().get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        # A reset/timeout is usually a network egress block (e.g. a locked-down
        # dev box) rather than a bad URL - make that actionable.
        raise ConnectionError(
            f"could not reach {url} ({e.__class__.__name__}). "
            "If you are on a restricted network/VPN, run namescout from a machine "
            "with internet, or save the page (Cmd/Ctrl+S) and pass the local .html file."
        ) from e
    return extract_from_html(resp.text, source=url)


def extract_from_html(html: str, source: str) -> Extraction:
    """Extract authors from an HTML string (from the web or a saved .html file).

    Prefers citation metadata / embedded identifiers, then falls back to names in
    the visible text.
    """
    # Prefer citation metadata / embedded identifiers when present.
    arxiv_id = find_arxiv_id(html)
    if arxiv_id:
        try:
            return fetch_arxiv(arxiv_id)
        except Exception:
            pass
    doi = find_doi(html)
    if doi:
        try:
            return fetch_doi(doi)
        except Exception:
            pass

    # citation_author meta tags (used by many journal/repository pages).
    meta_authors = re.findall(
        r'<meta[^>]+name=["\']citation_author["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    title_m = re.search(
        r'<meta[^>]+name=["\']citation_title["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.I,
    )
    title = title_m.group(1).strip() if title_m else None

    if meta_authors:
        authors = [Author(name=a.strip(), source=source) for a in meta_authors if a.strip()]
        return Extraction(authors=authors, title=title, source=source)

    # Prefer trafilatura's main-content extraction when available - it strips
    # nav/menus/logos/footers, which removes a lot of false-positive fodder.
    text = _trafilatura_text(html)
    if text:
        authors = [Author(name=n, source=source) for n in extract_names(text)]
        return Extraction(authors=authors, title=title, source=source)

    # Last resort: strip tags and run name detection over the visible text.
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    # Turn block-level boundaries into line breaks so names in separate elements
    # don't run together (and get merged with neighbouring headings/words).
    text = re.sub(
        r"(?i)</?(?:br|p|div|li|ul|ol|h[1-6]|tr|td|th|table|section|article|header|footer|dd|dt|span)\s*/?>",
        "\n",
        text,
    )
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"[ \t ]+", " ", text)  # collapse horizontal space, keep newlines
    text = re.sub(r"\n\s*\n+", "\n", text)
    names = extract_names(text)
    authors = [Author(name=n, source=source) for n in names]
    return Extraction(authors=authors, title=title, source=source)

"""Core data types shared across the package."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Author:
    """A single person extracted from a document or fetched from an API."""

    name: str
    affiliation: Optional[str] = None
    email: Optional[str] = None
    orcid: Optional[str] = None
    # Free-text note about where this author came from (e.g. "arXiv:2401.12345").
    source: str = ""

    def key(self) -> str:
        """Normalised key used to de-duplicate authors across sources."""
        return " ".join(self.name.lower().replace(".", "").split())


@dataclass
class Extraction:
    """The result of processing one input (a file, URL, DOI or raw text)."""

    authors: List[Author] = field(default_factory=list)
    # Title of the paper/page when we could determine it (nice context in the report).
    title: Optional[str] = None
    # Human-readable description of the input we processed.
    source: str = ""


def dedupe_authors(authors: List[Author]) -> List[Author]:
    """Merge authors that resolve to the same normalised name, preferring the
    richest record (one that carries an affiliation / email / orcid)."""
    merged: "dict[str, Author]" = {}
    for a in authors:
        if not a.name.strip():
            continue
        k = a.key()
        existing = merged.get(k)
        if existing is None:
            merged[k] = a
            continue
        # Fill in any fields the earlier record was missing.
        existing.affiliation = existing.affiliation or a.affiliation
        existing.email = existing.email or a.email
        existing.orcid = existing.orcid or a.orcid
        if a.source and a.source not in existing.source:
            existing.source = f"{existing.source}; {a.source}".strip("; ")
    return list(merged.values())

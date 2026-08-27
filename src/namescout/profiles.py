"""Build search / profile URLs for an author across platforms.

There is no public API to auto-follow or auto-invite on LinkedIn or X, so the
most reliable thing we can do is open a well-targeted *search* for each person.
Where we know an affiliation we fold it into the query to disambiguate common
names (e.g. two "Wei Zhang"s).
"""
from __future__ import annotations

from typing import Dict, List
from urllib.parse import quote_plus

from .models import Author

# Order matters: this is the order links appear in the dashboard and CSV.
ALL_PLATFORMS: List[str] = [
    "google",
    "scholar",
    "semanticscholar",
    "linkedin",
    "twitter",
    "researchgate",
    "orcid",
    "dblp",
    "homepage",
]

# Sensible default set for the "find and connect with paper authors" workflow.
DEFAULT_PLATFORMS: List[str] = [
    "google",
    "scholar",
    "linkedin",
    "twitter",
    "orcid",
]

# Pretty labels for the UI / CSV headers.
LABELS: Dict[str, str] = {
    "google": "Google",
    "scholar": "Google Scholar",
    "semanticscholar": "Semantic Scholar",
    "linkedin": "LinkedIn",
    "twitter": "X / Twitter",
    "researchgate": "ResearchGate",
    "orcid": "ORCID",
    "dblp": "DBLP",
    "homepage": "Homepage",
}


def _affil_terms(author: Author) -> str:
    """A short, query-friendly slice of the affiliation (drop addresses/emails)."""
    if not author.affiliation:
        return ""
    first = author.affiliation.split(",")[0].strip()
    return first if len(first) <= 60 else first[:60]


def profile_links(author: Author, platforms: List[str] = None) -> Dict[str, str]:
    """Return an ordered {platform: url} map for the given author."""
    platforms = platforms or DEFAULT_PLATFORMS
    name = author.name.strip()
    affil = _affil_terms(author)
    name_affil = f"{name} {affil}".strip()

    # If we already have an exact ORCID, link straight to the record.
    orcid_url = (
        f"https://orcid.org/{author.orcid}"
        if author.orcid
        else f"https://orcid.org/orcid-search/search?searchQuery={quote_plus(name)}"
    )

    builders = {
        "google": f"https://www.google.com/search?q={quote_plus(name_affil)}",
        "scholar": f"https://scholar.google.com/scholar?q={quote_plus(name)}",
        "semanticscholar": f"https://www.semanticscholar.org/search?q={quote_plus(name)}&sort=relevance",
        "linkedin": f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(name_affil)}",
        # f=user restricts X search to people/accounts rather than posts.
        "twitter": f"https://x.com/search?q={quote_plus(name)}&f=user",
        "researchgate": f"https://www.researchgate.net/search/researcher?q={quote_plus(name)}",
        "orcid": orcid_url,
        "dblp": f"https://dblp.org/search?q={quote_plus(name)}",
        "homepage": f'https://www.google.com/search?q={quote_plus(name + " (homepage OR website OR personal page)")}',
    }
    return {p: builders[p] for p in platforms if p in builders}

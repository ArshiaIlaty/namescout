"""namescout — extract authors from papers/documents/links and open their
LinkedIn / Google Scholar / X / ORCID profiles for research and outreach."""
from __future__ import annotations

__version__ = "0.1.0"

from .models import Author, Extraction  # noqa: E402,F401
from .dispatch import process  # noqa: E402,F401
from .profiles import profile_links  # noqa: E402,F401

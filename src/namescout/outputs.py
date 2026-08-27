"""Side outputs: open browser tabs, export CSV / JSON."""
from __future__ import annotations

import csv
import json
import os
import sys
import webbrowser
from typing import List, Optional

from .models import Author
from .profiles import LABELS, profile_links


def browser_available() -> bool:
    """True if we can plausibly open a browser here (i.e. not a headless box)."""
    if os.environ.get("NAMESCOUT_NO_BROWSER"):
        return False
    if os.name == "nt" or sys.platform == "darwin":
        return True
    # Linux: need a display or a usable BROWSER entry.
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True
    if os.environ.get("BROWSER"):
        return True
    try:
        webbrowser.get()
        return True
    except webbrowser.Error:
        return False


def open_urls(urls: List[str], max_open: int = 20) -> int:
    """Open up to *max_open* URLs as browser tabs. Returns how many were opened."""
    opened = 0
    for url in urls[:max_open]:
        try:
            if webbrowser.open_new_tab(url):
                opened += 1
        except webbrowser.Error:
            break
    return opened


def open_file(path: str) -> bool:
    try:
        return webbrowser.open_new_tab("file://" + os.path.abspath(path))
    except webbrowser.Error:
        return False


def export_csv(authors: List[Author], path: str, platforms: List[str]) -> None:
    header = ["name", "affiliation", "email", "orcid", "source"] + [
        LABELS.get(p, p) for p in platforms
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for a in authors:
            links = profile_links(a, platforms)
            w.writerow(
                [a.name, a.affiliation or "", a.email or "", a.orcid or "", a.source]
                + [links.get(p, "") for p in platforms]
            )


def export_json(authors: List[Author], path: str, platforms: List[str], title: Optional[str] = None) -> None:
    data = {
        "title": title,
        "count": len(authors),
        "authors": [
            {
                "name": a.name,
                "affiliation": a.affiliation,
                "email": a.email,
                "orcid": a.orcid,
                "source": a.source,
                "links": profile_links(a, platforms),
            }
            for a in authors
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

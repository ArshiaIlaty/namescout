"""Command-line entry point for namescout."""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import dispatch, outputs, report
from .dedup import dedupe
from .models import Author
from .profiles import ALL_PLATFORMS, DEFAULT_PLATFORMS, LABELS, profile_links


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="namescout",
        description="Extract author names from papers, documents and links, then "
        "open their LinkedIn / Google Scholar / X / ORCID profiles.",
        epilog="Examples:\n"
        "  namescout paper.pdf\n"
        "  namescout https://arxiv.org/abs/2401.12345 --tabs linkedin\n"
        "  namescout 10.1038/nature14539 attendees.csv --csv out.csv\n"
        '  namescout "Jane A. Smith, John Doe and Alice B. Carter"\n',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help="One or more files (.pdf/.docx/.csv/.txt), URLs, arXiv ids, DOIs, or raw text.",
    )
    p.add_argument(
        "--platforms",
        default=",".join(DEFAULT_PLATFORMS),
        help="Comma list of platforms to link. Available: %s (default: %s)"
        % (", ".join(ALL_PLATFORMS), ",".join(DEFAULT_PLATFORMS)),
    )
    p.add_argument(
        "--tabs",
        metavar="PLATFORMS",
        help="Immediately open browser tabs for these platforms, one per author "
        "(e.g. --tabs linkedin,scholar). Great for the 'invite everyone' workflow.",
    )
    p.add_argument("-o", "--out", default="namescout-report.html", help="Dashboard HTML path.")
    p.add_argument("--no-dashboard", action="store_true", help="Do not write the HTML dashboard.")
    p.add_argument("--open", action="store_true", help="Open the dashboard in a browser after writing it.")
    p.add_argument("--csv", metavar="PATH", help="Also export results to a CSV file.")
    p.add_argument("--json", metavar="PATH", help="Also export results to a JSON file.")
    p.add_argument(
        "--engine",
        choices=["auto", "gliner", "spacy", "heuristic"],
        help="Name-extraction engine (default: auto = gliner > spacy > heuristic). "
        "Also settable via NAMESCOUT_ENGINE.",
    )
    p.add_argument(
        "--labels",
        metavar="LIST",
        help="Comma list of entity labels for GLiNER (default: person). "
        'e.g. --labels "person,organization".',
    )
    p.add_argument(
        "--pdf-engine",
        choices=["auto", "docling", "marker", "pdfminer"],
        help="PDF text extractor (default: auto = docling > marker > pdfminer). "
        "Also settable via NAMESCOUT_PDF_ENGINE.",
    )
    p.add_argument(
        "--dedup",
        choices=["fuzzy", "exact", "splink"],
        help="Author de-duplication (default: fuzzy). 'exact' merges identical "
        "names only; 'splink' uses probabilistic linkage. Also NAMESCOUT_DEDUP.",
    )
    p.add_argument(
        "--grobid-url",
        metavar="URL",
        help="Base URL of a running GROBID server for exact paper-author "
        "extraction (e.g. http://localhost:8070). Also NAMESCOUT_GROBID_URL.",
    )
    p.add_argument("--mailto", metavar="EMAIL", help="Contact email for the Crossref polite pool (recommended for DOIs).")
    p.add_argument("--max-open", type=int, default=20, help="Safety cap on tabs opened by --tabs (default 20).")
    p.add_argument("--quiet", action="store_true", help="Only print the dashboard path and warnings.")
    return p


def _resolve_platforms(spec: str) -> List[str]:
    chosen = [x.strip().lower() for x in spec.split(",") if x.strip()]
    unknown = [x for x in chosen if x not in ALL_PLATFORMS]
    if unknown:
        raise SystemExit(
            f"Unknown platform(s): {', '.join(unknown)}. Available: {', '.join(ALL_PLATFORMS)}"
        )
    return chosen or list(DEFAULT_PLATFORMS)


def _print_table(authors: List[Author]) -> None:
    if not authors:
        return
    width = max(len(a.name) for a in authors)
    for i, a in enumerate(authors, 1):
        affil = f"  — {a.affiliation}" if a.affiliation else ""
        print(f"  {i:>2}. {a.name:<{width}}{affil}")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    platforms = _resolve_platforms(args.platforms)

    # Thread engine/labels to every extractor via env (read at call time).
    if args.engine:
        os.environ["NAMESCOUT_ENGINE"] = args.engine
    if args.labels:
        os.environ["NAMESCOUT_LABELS"] = args.labels
    if args.pdf_engine:
        os.environ["NAMESCOUT_PDF_ENGINE"] = args.pdf_engine
    if args.dedup:
        os.environ["NAMESCOUT_DEDUP"] = args.dedup
    if args.grobid_url:
        os.environ["NAMESCOUT_GROBID_URL"] = args.grobid_url
    from .names import resolve_engine

    effective = resolve_engine()
    if args.engine and args.engine != "auto" and effective != args.engine:
        print(
            f"! '{args.engine}' engine not available (not installed / model not "
            f"downloaded) — using '{effective}' instead.",
            file=sys.stderr,
        )
    if not args.quiet:
        print(f"engine: {effective}")

    all_authors: List[Author] = []
    titles: List[str] = []
    sources: List[str] = []

    for item in args.inputs:
        try:
            ex = dispatch.process(item, mailto=args.mailto)
        except Exception as e:  # keep going across multiple inputs
            print(f"! Could not process {item!r}: {e}", file=sys.stderr)
            continue
        all_authors.extend(ex.authors)
        if ex.title:
            titles.append(ex.title)
        sources.append(ex.source or item)
        if not args.quiet:
            label = ex.title or ex.source or item
            print(f"• {label}: {len(ex.authors)} authors")

    authors = dedupe(all_authors, strategy=args.dedup)
    if not authors:
        print("No author names found.", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"\nFound {len(authors)} unique authors:")
        _print_table(authors)
        print()

    title = titles[0] if len(titles) == 1 else None

    # Optional exports.
    if args.csv:
        outputs.export_csv(authors, args.csv, platforms)
        print(f"CSV written: {args.csv}")
    if args.json:
        outputs.export_json(authors, args.json, platforms, title=title)
        print(f"JSON written: {args.json}")

    # Dashboard (default on).
    if not args.no_dashboard:
        html_doc = report.build_dashboard(authors, platforms, title=title, sources=sources)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(html_doc)
        print(f"Dashboard written: {args.out}")
        if args.open:
            if outputs.browser_available() and outputs.open_file(args.out):
                print("Opened dashboard in your browser.")
            else:
                print("No browser available here — open the file above from a machine that has one.")

    # Direct tab opening.
    if args.tabs:
        tab_platforms = _resolve_platforms(args.tabs)
        if not outputs.browser_available():
            print(
                "\nNo browser detected (headless?). URLs to open manually:",
                file=sys.stderr,
            )
            for a in authors:
                links = profile_links(a, tab_platforms)
                for p in tab_platforms:
                    if p in links:
                        print(f"  [{LABELS.get(p, p)}] {a.name}: {links[p]}")
        else:
            urls = []
            for a in authors:
                links = profile_links(a, tab_platforms)
                urls.extend(links[p] for p in tab_platforms if p in links)
            opened = outputs.open_urls(urls, max_open=args.max_open)
            print(f"Opened {opened} tab(s) across {len(authors)} authors.")
            if len(urls) > args.max_open:
                print(
                    f"(Capped at --max-open={args.max_open}; {len(urls)} were requested. "
                    "Use the dashboard's bulk buttons for the rest.)"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

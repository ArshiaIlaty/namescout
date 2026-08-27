"""Author de-duplication / entity resolution strategies.

Extracting the same person from several sources (a PDF byline, a Crossref
record, a web page) yields near-duplicate records: ``A. Ilaty`` vs
``Arshia Ilaty`` vs ``Arshia M. Ilaty``.  This module merges them.

Strategies (``--dedup`` / ``NAMESCOUT_DEDUP``):
  exact   - merge only on identical normalised name (the safe, original behaviour).
  fuzzy   - name-aware: also merges initials into the matching full name
            (default). Conservative: refuses to merge when an initial is
            ambiguous between two different full first names (J. Smith when both
            John Smith and Jane Smith are present).
  splink  - probabilistic record linkage via Splink for large lists
            (`pip install "namescout[splink]"`); falls back to fuzzy if Splink
            isn't installed.
"""
from __future__ import annotations

import os
from typing import List, Optional

from .models import Author, dedupe_authors


def resolve_dedup(strategy: Optional[str] = None) -> str:
    return (strategy or os.environ.get("NAMESCOUT_DEDUP") or "fuzzy").lower()


def dedupe(authors: List[Author], strategy: Optional[str] = None) -> List[Author]:
    strat = resolve_dedup(strategy)
    if strat == "exact":
        return dedupe_authors(authors)
    if strat == "splink":
        merged = _splink_dedupe(authors)
        if merged is not None:
            return merged
        # Splink not available -> fuzzy is the next-best thing.
    return _fuzzy_dedupe(authors)


# --- fuzzy (name-aware) ------------------------------------------------------

def _tokens(name: str) -> List[str]:
    return [t for t in name.lower().replace(".", " ").split() if t]


def _surname(name: str) -> str:
    toks = _tokens(name)
    return toks[-1] if toks else ""


def _firsts(name: str) -> List[str]:
    toks = _tokens(name)
    return toks[:-1]


def _first_compatible(a: str, b: str) -> bool:
    """True if two given-name tokens could be the same person.

    Equal, or one is an initial that begins the other ("j" ~ "john").
    Two *different full* names ("john" vs "jane") are NOT compatible.
    """
    if a == b:
        return True
    if len(a) == 1 and b.startswith(a):
        return True
    if len(b) == 1 and a.startswith(b):
        return True
    return False


def _compatible(name_a: str, name_b: str) -> bool:
    """Whether two full names can refer to the same person (same surname +
    compatible first given name)."""
    if not name_a or not name_b:
        return False
    if _surname(name_a) != _surname(name_b):
        return False
    fa, fb = _firsts(name_a), _firsts(name_b)
    if not fa or not fb:
        # One is a mononym / surname only - too risky to merge automatically.
        return False
    return _first_compatible(fa[0], fb[0])


def _richness(a: Author) -> int:
    """How much metadata a record carries (used to pick the cluster representative)."""
    return sum(bool(x) for x in (a.affiliation, a.email, a.orcid))


def _fuzzy_dedupe(authors: List[Author]) -> List[Author]:
    # First collapse exact duplicates (also merges their fields).
    base = dedupe_authors(authors)

    # Seed clusters with the *fullest* names first so initials attach to them,
    # not the other way around.
    order = sorted(
        range(len(base)),
        key=lambda i: (-len(_firsts(base[i].name)), -_richness(base[i]), i),
    )

    clusters: List[List[Author]] = []
    reps: List[str] = []
    for i in order:
        a = base[i]
        matches = [c for c, rep in enumerate(reps) if _compatible(rep, a.name)]
        if len(matches) == 1:
            clusters[matches[0]].append(a)
        else:
            # 0 matches -> new cluster.  >1 match -> ambiguous, keep separate
            # rather than guess (don't fold J. Smith into John *or* Jane).
            clusters.append([a])
            reps.append(a.name)

    return [_merge_cluster(c) for c in clusters]


def _merge_cluster(cluster: List[Author]) -> Author:
    # Representative = the record with the most name tokens, then most metadata.
    rep = max(cluster, key=lambda a: (len(_tokens(a.name)), _richness(a)))
    out = Author(name=rep.name, affiliation=rep.affiliation, email=rep.email,
                 orcid=rep.orcid, source=rep.source)
    for a in cluster:
        if a is rep:
            continue
        out.affiliation = out.affiliation or a.affiliation
        out.email = out.email or a.email
        out.orcid = out.orcid or a.orcid
        if a.source and a.source not in out.source:
            out.source = f"{out.source}; {a.source}".strip("; ")
    return out


# --- splink (optional, heavy) ------------------------------------------------

def _splink_dedupe(authors: List[Author]) -> Optional[List[Author]]:
    """Probabilistic linkage with Splink; None if Splink isn't installed.

    Splink shines on large, messy record sets.  We use it to *cluster* the
    author names, then merge each cluster's fields with the shared logic.
    """
    try:
        import pandas as pd  # type: ignore
        from splink.duckdb.linker import DuckDBLinker  # type: ignore
        import splink.duckdb.comparison_library as cl  # type: ignore
    except Exception:
        return None

    try:
        base = dedupe_authors(authors)
        if len(base) < 3:
            return _fuzzy_dedupe(authors)

        df = pd.DataFrame(
            {
                "unique_id": list(range(len(base))),
                "full_name": [a.name for a in base],
                "surname": [_surname(a.name) for a in base],
            }
        )
        settings = {
            "link_type": "dedupe_only",
            "blocking_rules_to_generate_predictions": ["l.surname = r.surname"],
            "comparisons": [cl.jaro_winkler_at_thresholds("full_name", [0.9, 0.7])],
        }
        linker = DuckDBLinker(df, settings)
        linker.estimate_u_using_random_sampling(max_pairs=1e5)
        preds = linker.predict(threshold_match_probability=0.9)
        clusters_df = linker.cluster_pairwise_predictions_at_threshold(
            preds, threshold_match_probability=0.9
        ).as_pandas_dataframe()

        groups: "dict[object, List[Author]]" = {}
        for _, row in clusters_df.iterrows():
            groups.setdefault(row["cluster_id"], []).append(base[int(row["unique_id"])])
        return [_merge_cluster(c) for c in groups.values()]
    except Exception:
        # Any Splink/runtime hiccup -> safe fallback.
        return _fuzzy_dedupe(authors)

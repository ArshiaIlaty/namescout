"""Detect person names in free text via a pluggable NER engine.

namescout is the personalisation layer (input handling, profile links, dedup,
dashboard); the actual entity extraction is delegated to a best-in-class model
when one is installed. Engines, in order of preference for engine="auto":

  1. GLiNER   - zero-shot NER, custom entity labels, great on messy pages.
                `pip install "namescout[gliner]"`  (downloads a model on first use)
  2. spaCy    - solid production NER.  `pip install "namescout[ner]"`
  3. heuristic - no dependencies; a capitalisation + author-list parser tuned to
                cut the usual false positives. The only option on an offline box.

Pick explicitly with the NAMESCOUT_ENGINE env var or the CLI --engine flag.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import List, Optional

# Entity labels asked of the NER engines. "person" is what we turn into search
# targets; override with NAMESCOUT_LABELS (comma-separated) to experiment.
def _default_labels() -> List[str]:
    return [x.strip() for x in os.environ.get("NAMESCOUT_LABELS", "person").split(",") if x.strip()] or ["person"]


def _gliner_model_name() -> str:
    return os.environ.get("NAMESCOUT_GLINER_MODEL", "urchade/gliner_medium-v2.1")

# Words that are Capitalised in documents but are never a person's given name.
# Kept broad on purpose - these are the usual false positives from headings,
# calendars and paper boilerplate.
STOPWORDS = {
    # calendar
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    # meeting / document boilerplate
    "meeting", "agenda", "conference", "call", "discussion", "project", "team",
    "overview", "session", "track", "panel", "report", "summary", "analysis",
    "review", "schedule", "program", "event", "workshop", "seminar", "class",
    "course", "office", "home", "figure", "table", "section", "chapter",
    "appendix", "references", "bibliography", "acknowledgements",
    "acknowledgments", "introduction", "conclusion", "conclusions", "methods",
    "method", "results", "discussion", "abstract", "keywords", "background",
    "related", "work", "experiments", "evaluation", "dataset", "datasets",
    "university", "institute", "department", "laboratory", "college", "school",
    "corporation", "company", "inc", "ltd", "llc", "group", "center", "centre",
    "national", "international", "journal", "proceedings", "volume", "issue",
    "copyright", "license", "abstract", "email", "author", "authors",
    "corresponding", "equal", "contribution", "preprint", "arxiv",
    # conference / program-page boilerplate (safe: none are common surnames)
    "logo", "papers", "online", "chair", "chairs", "cochair", "co-chair",
    "keynote", "keynotes", "poster", "posters", "oral", "plenary", "tutorial",
    "tutorials", "symposium", "roundtable", "moderator", "speaker", "speakers",
    "presenter", "presenters", "welcome", "opening", "closing", "committee",
    "sponsor", "sponsors", "exhibitor", "exhibitors", "registration",
    "submission", "submissions", "venue",
}

# Lowercase particles allowed *inside* a multi-word name (van der Berg, de la Cruz).
PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "das",
    "la", "le", "el", "al", "bin", "ibn", "san", "st", "mac", "mc", "ter", "ten",
}

TITLE_RE = re.compile(r"^(mr|mrs|ms|miss|dr|prof|professor|sir|madam)\.?\s+", re.I)

# A single name token: "John", "O'Neil", "Muller-Lyer", or an initial "J." / "J".
_TOKEN = r"[A-Z][A-Za-z'’\-]*\.?"
_INITIAL = r"[A-Z]\.?"
# Whitespace *within* a name - spaces/tabs but never a line break, so the sweep
# can't merge a heading on one line with a name on the next.
_WS = r"[ \t ]+"
# A full personal name: 2-4 tokens, initials allowed, optional lowercase particle.
NAME_RE = re.compile(
    r"\b(?:"
    + r"(?:%s|%s)" % (_TOKEN, _INITIAL)
    + r"(?:%s(?:%s|%s|%s))" % (_WS, _TOKEN, _INITIAL, "|".join(PARTICLES))
    + r"{1,3}"
    + r")\b"
)


def _clean(fragment: str) -> str:
    fragment = TITLE_RE.sub("", fragment.strip())
    # Trim trailing affiliation markers / footnote symbols often glued to names.
    fragment = re.sub(r"[\d\*†‡§¶,;].*$", "", fragment).strip()
    return re.sub(r"\s+", " ", fragment)


def _looks_like_name(fragment: str) -> bool:
    fragment = _clean(fragment)
    if not fragment:
        return False
    tokens = fragment.split()
    if not (2 <= len(tokens) <= 4):
        return False
    # Reject if any *significant* (non-particle) token is a stopword.
    real = [t for t in tokens if t.lower().rstrip(".") not in PARTICLES]
    if not real:
        return False
    for t in real:
        low = t.lower().rstrip(".")
        if low in STOPWORDS:
            return False
    # An all-caps acronym mixed with a normal word is almost never a name
    # ("Deep ECG", "Novel RNA") - reject that pattern.
    acronyms = [t for t in real if t.rstrip(".").isupper() and len(t.rstrip(".")) >= 2]
    normals = [t for t in real if not (t.rstrip(".").isupper() and len(t.rstrip(".")) >= 2)]
    if acronyms and normals:
        return False
    # Need at least one multi-letter token (all-initials "J. K." isn't a person).
    if not any(len(t.rstrip(".")) > 1 for t in real):
        return False
    # Every real token must start uppercase (already implied, but guards particles-only).
    return all(t[0].isupper() for t in real)


def _spacy_names(text: str) -> Optional[List[str]]:
    """Return PERSON entities via spaCy, or None if spaCy/model is unavailable."""
    nlp = _load_spacy()
    if nlp is None:
        return None
    doc = nlp(text[:1_000_000])  # guard against pathological inputs
    out: List[str] = []
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            acc = _accept_ner(ent.text)
            if acc:
                out.append(acc)
    return out


@lru_cache(maxsize=1)
def _load_spacy():
    try:
        import spacy  # type: ignore
    except Exception:
        return None
    for model in ("en_core_web_trf", "en_core_web_lg", "en_core_web_sm"):
        try:
            return spacy.load(model)
        except Exception:
            continue
    return None


@lru_cache(maxsize=1)
def _load_gliner():
    try:
        from gliner import GLiNER  # type: ignore
    except Exception:
        return None
    try:
        return GLiNER.from_pretrained(_gliner_model_name())
    except Exception:
        return None


def _chunks(text: str, words_per_chunk: int = 300):
    """Yield word-window chunks so long pages fit GLiNER's context limit."""
    words = text.split()
    for i in range(0, len(words), words_per_chunk):
        yield " ".join(words[i : i + words_per_chunk])


def _gliner_names(text: str, labels: List[str], threshold: float = 0.5) -> Optional[List[str]]:
    """Return person-like entities via GLiNER, or None if GLiNER is unavailable."""
    model = _load_gliner()
    if model is None:
        return None
    out: List[str] = []
    for chunk in _chunks(text):
        try:
            ents = model.predict_entities(chunk, labels, threshold=threshold)
        except Exception:
            continue
        for e in ents:
            out.append(e.get("text", ""))
    return out


def _accept_ner(name: str) -> Optional[str]:
    """Light validation for NER output - trust the model, just tidy and sanity-check.

    Unlike the heuristic we do NOT enforce the 2-4 capitalised-token rule, so real
    single-token or longer names the model finds are kept.
    """
    name = _clean(name)
    if not name or not re.search(r"[A-Za-z]", name):
        return None
    tokens = name.split()
    if not (1 <= len(tokens) <= 6):
        return None
    # Drop entities that are entirely boilerplate words.
    if all(t.lower().rstrip(".") in STOPWORDS for t in tokens):
        return None
    return name


def resolve_engine(engine: Optional[str] = None) -> str:
    """Resolve the *effective* engine, verifying the backend is actually usable.

    Falls back to the heuristic when a requested/preferred engine can't load, so
    the returned name always reflects what will really run.
    """
    requested = (engine or os.environ.get("NAMESCOUT_ENGINE") or "auto").lower()
    if requested == "heuristic":
        return "heuristic"
    if requested in ("gliner", "auto") and _load_gliner() is not None:
        return "gliner"
    if requested in ("spacy", "auto") and _load_spacy() is not None:
        return "spacy"
    return "heuristic"


def split_author_list(text: str) -> List[str]:
    """Split a byline like "Jane A. Smith, John Doe and Alice B. Carter" into
    candidate names. Handles comma-, 'and'- and newline-separated lists."""
    # Normalise separators to commas, then split.
    normalised = re.sub(r"\s+and\s+|\s*&\s*|\n", ", ", text)
    parts = [p.strip() for p in normalised.split(",")]
    return [p for p in parts if p]


def extract_names(
    text: str,
    prefer_author_list: bool = False,
    engine: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> List[str]:
    """Extract person names from arbitrary text using the selected engine.

    - GLiNER / spaCy results are trusted (light tidy + sanity check only).
    - The heuristic path additionally uses *prefer_author_list* (byline splitting)
      and a conservative capitalisation sweep.
    Returns display-form names, de-duplicated, in order of first appearance.
    """
    if not text or not text.strip():
        return []

    resolved = resolve_engine(engine)
    seen: "dict[str, str]" = {}  # normalised -> display form (preserve order)

    def add(name: str, validated: bool = False) -> None:
        name = name if validated else _clean(name)
        if name:
            key = " ".join(name.lower().replace(".", "").split())
            seen.setdefault(key, name)

    # --- NER engines: trust the model, apply only light validation ---
    if resolved == "gliner":
        hits = _gliner_names(text, labels or _default_labels())
        if hits is not None:
            for n in hits:
                acc = _accept_ner(n)
                if acc:
                    add(acc, validated=True)
            return list(seen.values())
    if resolved == "spacy":
        hits = _spacy_names(text)
        if hits is not None:
            for n in hits:
                add(n, validated=True)
            return list(seen.values())

    # --- heuristic (no-dependency fallback / explicit engine="heuristic") ---
    def add_heuristic(name: str) -> None:
        name = _clean(name)
        if _looks_like_name(name):
            add(name, validated=True)

    if prefer_author_list:
        for frag in split_author_list(text):
            add_heuristic(frag)
    for m in NAME_RE.finditer(text):
        add_heuristic(m.group(0))
    return list(seen.values())


def name_from_email(email: str) -> Optional[str]:
    """Best-effort human name from an email local-part (john.doe@ -> John Doe)."""
    email = email.strip()
    if "@" not in email:
        return None
    local = email.split("@", 1)[0]
    # Drop trailing digits some addresses carry (jdoe2 -> jdoe).
    local = re.sub(r"\d+$", "", local)
    if "." in local or "_" in local or "-" in local:
        parts = re.split(r"[._\-]+", local)
    else:
        # camelCase -> split; otherwise a single opaque token, not usable.
        camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
        parts = camel.split()
    parts = [p for p in parts if len(p) > 1]  # drop lone initials like "j"
    if len(parts) < 2:
        return None
    name = " ".join(p.capitalize() for p in parts)
    return name if _looks_like_name(name) else None

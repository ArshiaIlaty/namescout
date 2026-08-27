"""Offline unit tests (no network)."""
from namescout import names, dispatch, web, grobid, pdftext, dedup
from namescout.profiles import profile_links
from namescout.models import Author, dedupe_authors


def test_byline_extraction():
    text = "Jane A. Smith, John Doe and Alice B. Carter"
    got = names.extract_names(text, prefer_author_list=True)
    assert "Jane A. Smith" in got
    assert "John Doe" in got
    assert "Alice B. Carter" in got


def test_rejects_section_headings():
    text = "Related Work\nIntroduction\nExperimental Results\nJohn Doe"
    got = names.extract_names(text)
    assert "John Doe" in got
    for bad in ("Related Work", "Experimental Results", "Introduction"):
        assert bad not in got


def test_particle_names():
    got = names.extract_names("Ludwig van Beethoven wrote this.")
    assert "Ludwig van Beethoven" in got


def test_name_from_email():
    assert names.name_from_email("john.doe@x.com") == "John Doe"
    assert names.name_from_email("janeSmith@x.com") == "Jane Smith"
    assert names.name_from_email("info@x.com") is None  # not a person


def test_classify():
    assert dispatch.classify("https://arxiv.org/abs/2401.12345") == "arxiv"
    assert dispatch.classify("2401.12345") == "arxiv"
    assert dispatch.classify("10.1038/nature14539") == "doi"
    assert dispatch.classify("https://doi.org/10.1/x") == "doi"
    assert dispatch.classify("Some random text about people") == "raw"


def test_profile_links_uses_affiliation():
    a = Author(name="Wei Zhang", affiliation="MIT, Cambridge")
    links = profile_links(a, ["linkedin", "scholar", "orcid"])
    assert "MIT" in links["linkedin"]
    assert "MIT" not in links["scholar"]  # scholar uses bare name
    assert "orcid-search" in links["orcid"]


def test_orcid_direct_link():
    a = Author(name="Wei Zhang", orcid="0000-0002-1825-0097")
    links = profile_links(a, ["orcid"])
    assert links["orcid"] == "https://orcid.org/0000-0002-1825-0097"


def test_html_separates_block_elements():
    html = "<ul><li>Maria Gonzalez</li><li>Wei Zhang</li></ul><footer>Related Work</footer>"
    ex = web.extract_from_html(html, source="x")
    got = [a.name for a in ex.authors]
    assert "Maria Gonzalez" in got
    assert "Wei Zhang" in got
    assert "Related Work" not in got  # heading in its own element, not merged


def test_acronym_plus_word_rejected():
    # "Deep ECG" looks name-shaped but is an acronym + word, not a person.
    assert "Deep ECG" not in names.extract_names("Deep ECG models by Wei Zhang")
    assert "Wei Zhang" in names.extract_names("Deep ECG models by Wei Zhang")


def test_engine_resolves_to_heuristic_without_models(monkeypatch):
    monkeypatch.delenv("NAMESCOUT_ENGINE", raising=False)
    # No gliner/spacy installed in CI -> heuristic.
    assert names.resolve_engine() == "heuristic"
    assert names.resolve_engine("gliner") == "heuristic"  # requested but unavailable


def test_conference_boilerplate_filtered():
    text = "CinC Logo\nPAPERS ONLINE\nCHAIR CO-CHAIR\nKeynote Speaker: John D. Smith\nPoster Session"
    got = names.extract_names(text, prefer_author_list=True)
    assert "John D. Smith" in got
    for junk in ("CinC Logo", "Papers Online", "Chair", "Poster Session", "Keynote Speaker"):
        assert junk not in got


def test_dedupe_merges_fields():
    merged = dedupe_authors([
        Author(name="John Doe", source="a"),
        Author(name="john doe", affiliation="MIT", source="b"),
    ])
    assert len(merged) == 1
    assert merged[0].affiliation == "MIT"


def test_fuzzy_dedup_merges_initial_into_full_name():
    merged = dedup.dedupe([
        Author(name="A. Ilaty", source="a"),
        Author(name="Arshia Ilaty", affiliation="UCSC", source="b"),
        Author(name="Arshia M. Ilaty", source="c"),
    ], strategy="fuzzy")
    assert len(merged) == 1
    # Keeps the fullest name and inherits the affiliation.
    assert merged[0].name == "Arshia M. Ilaty"
    assert merged[0].affiliation == "UCSC"


def test_fuzzy_dedup_keeps_ambiguous_initials_separate():
    # J. Smith is ambiguous between John and Jane -> must NOT collapse them.
    merged = dedup.dedupe([
        Author(name="John Smith"),
        Author(name="Jane Smith"),
        Author(name="J. Smith"),
    ], strategy="fuzzy")
    names_out = sorted(a.name for a in merged)
    assert "John Smith" in names_out
    assert "Jane Smith" in names_out
    assert len(merged) == 3  # John, Jane, and the un-mergeable J. Smith


def test_fuzzy_dedup_does_not_merge_different_people():
    merged = dedup.dedupe([
        Author(name="Wei Zhang"),
        Author(name="Lei Zhang"),
    ], strategy="fuzzy")
    assert len(merged) == 2  # same surname, different first names


def test_exact_dedup_leaves_initials_separate():
    merged = dedup.dedupe([
        Author(name="A. Ilaty"),
        Author(name="Arshia Ilaty"),
    ], strategy="exact")
    assert len(merged) == 2


def test_splink_falls_back_when_unavailable():
    # Splink isn't installed in CI -> dedupe still works via fuzzy fallback.
    merged = dedup.dedupe([
        Author(name="Arshia Ilaty"),
        Author(name="A. Ilaty"),
    ], strategy="splink")
    assert len(merged) == 1


def test_pdf_engine_resolves_to_pdfminer_without_models():
    assert pdftext.resolve_pdf_engine() == "pdfminer"
    assert pdftext.resolve_pdf_engine("docling") == "pdfminer"  # not installed


def test_grobid_returns_none_without_server(monkeypatch):
    monkeypatch.delenv("NAMESCOUT_GROBID_URL", raising=False)
    monkeypatch.delenv("GROBID_URL", raising=False)
    assert grobid.grobid_url() is None
    assert grobid.fetch_grobid_authors("/nonexistent.pdf") is None


def test_grobid_parses_tei_authors():
    tei = """<?xml version="1.0"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader><fileDesc>
        <titleStmt><title>Deep Nets for ECG</title></titleStmt>
        <sourceDesc><biblStruct><analytic>
          <author><persName><forename>Arshia</forename><surname>Ilaty</surname></persName>
            <email>arshia@ucsc.edu</email>
            <affiliation><orgName>UC Santa Cruz</orgName></affiliation></author>
          <author><persName><forename>Wei</forename><surname>Zhang</surname></persName></author>
        </analytic></biblStruct></sourceDesc>
      </fileDesc></teiHeader>
    </TEI>"""
    ex = grobid._parse_tei(tei, source="x")
    got = {a.name: a for a in ex.authors}
    assert ex.title == "Deep Nets for ECG"
    assert "Arshia Ilaty" in got
    assert got["Arshia Ilaty"].email == "arshia@ucsc.edu"
    assert got["Arshia Ilaty"].affiliation == "UC Santa Cruz"
    assert "Wei Zhang" in got

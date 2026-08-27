# namescout

Give it **any document, PDF, link, CSV or blob of text** — it extracts the
**people's names** in it and opens their **LinkedIn / Google Scholar / X / ORCID**
(and more) so you can research each person and reach out.

It works on anything with names in it — a general web page, a report, a meeting
attendee list — and has a **fast path for research papers**, where arXiv/DOI links
give it the exact author list. There is no public API to auto-follow or auto-invite
on LinkedIn or X, so namescout automates the *finding* part: it turns a source into
a set of well-targeted profile searches, one click each.

The original motivation was academic papers ("10 authors → check them all → connect
on LinkedIn"), but the tool is general-purpose name extraction + people search.

> Renamed from `name-extractor`. The old single-file browser tool is kept as
> `legacy-name-extractor-ui.html`.

## Why it's more reliable than guessing

- **Papers → exact author lists.** arXiv links/ids and DOIs are resolved through the
  arXiv and Crossref APIs, so you get the *real* author list (with affiliations /
  ORCIDs) instead of names guessed from capitalisation.
- **PDFs** are sniffed for an embedded arXiv-id/DOI first (→ exact metadata); only if
  none is found does it parse the *author region* (the text before "Abstract"), which
  avoids scraping section headings like "Related Work".
- **General text / CSV / web pages** are handled by a pluggable NER engine (below).

## Extraction engines (don't reinvent the wheel)

namescout is the *personalisation layer* — input handling, profile-link generation,
dedup, dashboard, portability — wrapped around best-in-class extractors. It picks the
best engine available (override with `--engine` or `NAMESCOUT_ENGINE`):

| Engine | Install | Notes |
|---|---|---|
| **GLiNER** (recommended) | `pip install "namescout[gliner]"` | Zero-shot NER, custom entity labels; correctly rejects "CinC Logo" / "Deep Learning" as non-persons. Downloads a model on first use. |
| **spaCy** | `pip install "namescout[ner]"` + `python -m spacy download en_core_web_sm` | Solid production NER. |
| **heuristic** | built-in, no deps | Capitalisation + author-list parser; the only option on an offline box. Understands initials (`J. K.`), particles (`van`/`de`/`der`), comma/"and" lists; filters headings/months/program boilerplate. Will still miss topic-like phrases ("Deep Learning") — use GLiNER for messy pages. |

`auto` (default) = GLiNER → spaCy → heuristic, using whatever is installed. Related
tools it also uses when present: **trafilatura** (`[web]` extra) to strip
nav/menus/logos from fetched pages before extraction.

For research papers namescout still short-circuits to **exact author lists** via the
arXiv/Crossref APIs regardless of engine.

### PDF parsing (`--pdf-engine`)

Before names are extracted, a PDF has to become text. The engine is pluggable:

| PDF engine | Install | Notes |
|---|---|---|
| **pdfminer** | built-in | Fast, good on normal text PDFs. The default fallback. |
| **docling** | `pip install "namescout[docling]"` | IBM's document understanding — much better on multi-column / scientific / scanned-ish PDFs. Downloads models on first use. |
| **marker** | `pip install "namescout[marker]"` | High-quality PDF→markdown. Also downloads models. |

`--pdf-engine auto` (default) = docling → marker → pdfminer, using whatever is installed
(`NAMESCOUT_PDF_ENGINE` also works).

### GROBID for paper headers (`--grobid-url`)

For a scholarly PDF **with no arXiv id / DOI**, [GROBID](https://github.com/kermitt2/grobid)
parses the exact author block — names, affiliations *and* emails. It runs as a
separate service (easiest via Docker):

```bash
docker run --rm -t -p 8070:8070 lfoppiano/grobid:0.8.0
namescout paper.pdf --grobid-url http://localhost:8070      # or export NAMESCOUT_GROBID_URL
```

namescout tries, in order: embedded arXiv/DOI → GROBID (if configured) → heuristic
author-region parsing. If GROBID isn't running it's silently skipped.

### De-duplication (`--dedup`)

The same person often shows up as `A. Ilaty`, `Arshia Ilaty` and `Arshia M. Ilaty`
across sources. namescout merges them:

| Strategy | Notes |
|---|---|
| **fuzzy** (default) | Name-aware: folds initials into the matching full name, keeps the fullest name and inherits affiliation/email/ORCID. Conservative — an initial that's ambiguous between two full first names (`J. Smith` when both *John* and *Jane* Smith are present) is left alone rather than guessed. |
| **exact** | Merge only identical (normalised) names — the safe original behaviour. |
| **splink** | Probabilistic record linkage via [Splink](https://github.com/moj-analytical-services/splink) for large/messy lists (`pip install "namescout[splink]"`); falls back to fuzzy if Splink isn't installed. |

## Install

```bash
pip install -e .                # from this repo (heuristic engine, no ML deps)
# recommended for messy pages/PDFs — SOTA zero-shot NER:
pip install -e ".[gliner]"
# other optional extras:
pip install -e ".[ner]"         # spaCy NER (then: python -m spacy download en_core_web_sm)
pip install -e ".[web]"         # trafilatura: clean main-content extraction from URLs
pip install -e ".[docx]"        # cleaner .docx parsing (a stdlib fallback works without it)
pip install -e ".[docling]"     # docling: better PDF -> text on complex/scientific PDFs
pip install -e ".[marker]"      # marker: high-quality PDF -> markdown
pip install -e ".[splink]"      # splink: probabilistic author de-duplication
```

Requires Python 3.9+. Core deps: `requests`, `pdfminer.six`.

## Usage

```bash
namescout paper.pdf                              # extract + write a dashboard
namescout https://arxiv.org/abs/1706.03762       # arXiv link → exact authors
namescout 10.1038/nature14539 --mailto you@x.com # DOI via Crossref
namescout attendees.csv --csv contacts.csv       # CSV in, enriched CSV out
namescout "Jane A. Smith, John Doe and Alice B. Carter"   # raw text byline

# mix inputs, and open LinkedIn + Scholar tabs for every author at once:
namescout paper.pdf extra.csv --tabs linkedin,scholar
```

Accepted inputs (any mix): `.pdf` · `.docx` · `.csv` · `.txt`/`.md` · `.html` · a URL ·
an arXiv id · a DOI · raw text. A `.txt` file that is mostly links is treated as a
**list of links** (one per line) and each is fetched.

### When a link can't be fetched (restricted network / firewall)

If you're on a locked-down box or VPN, outbound requests to arbitrary sites may be
reset (`Connection reset by peer`) — that's the *network* blocking it, not namescout.
Three ways around it:

1. **Run namescout from a machine with internet** (e.g. your laptop) — simplest.
2. **Save the page and process it offline:** in your browser, `Cmd/Ctrl+S` → "Web
   Page, HTML only", then `namescout saved-page.html`. No network needed.
3. **Copy-paste the visible text** into the web UI's text box (or quote it on the CLI).

> Extraction on general/messy web pages is best with spaCy NER installed
> (`pip install -e ".[ner]" && python -m spacy download en_core_web_sm`). Without it,
> the no-dependency heuristic still works but may include the occasional
> non-name on complex pages.

### What you get

- **A self-contained HTML dashboard** (`namescout-report.html` by default) — one
  card per author with profile links, plus **"Open all LinkedIn" / "Open all Scholar"**
  bulk buttons for the invite workflow. It has no external dependencies, so you can
  copy it to any machine and open it offline.
- `--csv PATH` / `--json PATH` exports (name, affiliation, email, ORCID, source, and a
  column/field per platform link).
- `--tabs PLATFORMS` opens tabs directly when a browser is available.

## Web UI

Prefer clicking to typing? There's a local web app (standard-library only, nothing
extra to install):

```bash
namescout-web                    # then open http://localhost:8765
namescout-web --port 9000        # pick another port
```

Upload files, paste links/DOIs, or paste text; you get back the same clickable
dashboard (with the "Open all LinkedIn / Scholar" bulk buttons). It binds to
`127.0.0.1` (local only) by default.

**Running the web UI on a remote/headless server (e.g. a dev box):** the browser is
on your laptop, not the server, so use an SSH tunnel — no need to expose any port
publicly:

```bash
# on your laptop:
ssh -L 8765:localhost:8765 you@your-server
# then on the server:
namescout-web
# then open http://localhost:8765 in your laptop browser
```

### Portable / headless behaviour

On a machine with a browser (your Mac), `--open` opens the dashboard and `--tabs`
opens tabs. On a **headless box** (no display), namescout detects this and instead
just writes the files and **prints the URLs** so you can open them from your laptop.
Set `NAMESCOUT_NO_BROWSER=1` to force this behaviour.

### Platforms

`google`, `scholar`, `semanticscholar`, `linkedin`, `twitter`, `researchgate`,
`orcid`, `dblp`, `homepage`. Choose with `--platforms`; default is
`google,scholar,linkedin,twitter,orcid`. Known affiliations are folded into
Google/LinkedIn queries to disambiguate common names.

## Options

```
--platforms LIST   platforms to link (default: google,scholar,linkedin,twitter,orcid)
--tabs PLATFORMS   open browser tabs for these platforms, one per author
-o, --out PATH     dashboard path (default: namescout-report.html)
--no-dashboard     don't write the dashboard
--open             open the dashboard after writing it
--csv PATH         export CSV
--json PATH        export JSON
--pdf-engine ENG   PDF text extractor: auto|docling|marker|pdfminer (default auto)
--dedup STRATEGY   author de-dup: fuzzy|exact|splink (default fuzzy)
--grobid-url URL   GROBID server for exact paper-author extraction (e.g. :8070)
--mailto EMAIL     contact email for the Crossref polite pool (recommended for DOIs)
--max-open N       cap on tabs opened by --tabs (default 20)
--quiet            minimal output
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT

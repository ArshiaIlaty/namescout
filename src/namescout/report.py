"""Generate a self-contained, clickable HTML dashboard of authors + profile links.

The file has no external dependencies (all CSS/JS inline) so it works offline and
can be copied to any machine - which is what makes the CLI portable: on a
headless box we just write this file and you open it from your laptop.
"""
from __future__ import annotations

import html
import json
from typing import List, Optional

from .models import Author
from .profiles import LABELS, profile_links

_STYLE = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
  margin: 0; background: #f4f5f7; color: #1a1a1a; }
@media (prefers-color-scheme: dark) { body { background:#15171c; color:#e6e6e6; } }
header { padding: 20px 24px; background: #0b5cff; color: #fff; }
header h1 { margin: 0 0 4px; font-size: 20px; }
header .sub { opacity: .9; font-size: 13px; }
.toolbar { position: sticky; top: 0; z-index: 5; display: flex; flex-wrap: wrap;
  gap: 8px; align-items: center; padding: 12px 24px; background: #fff;
  border-bottom: 1px solid #e0e0e0; }
@media (prefers-color-scheme: dark) { .toolbar { background:#1e2128; border-color:#2b2f38; } }
.toolbar input { flex: 1 1 200px; min-width: 160px; padding: 8px 10px;
  border: 1px solid #ccc; border-radius: 6px; font-size: 14px; background:transparent; color:inherit; }
button { border: 0; border-radius: 6px; padding: 8px 12px; font-size: 13px;
  cursor: pointer; background: #eef1f6; color: #1a1a1a; }
button:hover { filter: brightness(.95); }
button.bulk { background: #0b5cff; color: #fff; }
@media (prefers-color-scheme: dark) { button { background:#2b2f38; color:#e6e6e6; } }
.grid { display: grid; gap: 14px; padding: 20px 24px;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.card { background: #fff; border: 1px solid #e4e4e4; border-radius: 10px; padding: 16px; }
@media (prefers-color-scheme: dark) { .card { background:#1e2128; border-color:#2b2f38; } }
.card h3 { margin: 0 0 2px; font-size: 16px; }
.card .meta { font-size: 12px; opacity: .75; margin-bottom: 10px; word-break: break-word; }
.links { display: flex; flex-wrap: wrap; gap: 6px; }
.links a { text-decoration: none; font-size: 12px; padding: 5px 9px; border-radius: 999px;
  background: #eef1f6; color: #0b5cff; border: 1px solid #dbe3f0; }
.links a:hover { background: #dbe6ff; }
@media (prefers-color-scheme: dark) { .links a { background:#242833; color:#7aa2ff; border-color:#33384a; } }
.card .openall { margin-top: 10px; }
.count { font-size: 13px; opacity:.8; padding: 0 24px; }
footer { padding: 16px 24px; font-size: 12px; opacity: .6; }
"""

_SCRIPT = """
function openAll(urls) {
  if (urls.length > 8 &&
      !confirm('Open ' + urls.length + ' tabs? Your browser may block some as pop-ups.')) return;
  urls.forEach(function(u, i){ setTimeout(function(){ window.open(u, '_blank'); }, i*350); });
}
function filterCards(q) {
  q = q.toLowerCase();
  document.querySelectorAll('.card').forEach(function(c){
    c.style.display = c.dataset.search.indexOf(q) >= 0 ? '' : 'none';
  });
}
"""


def _card(index: int, author: Author, platforms: List[str]) -> str:
    links = profile_links(author, platforms)
    name = html.escape(author.name)
    meta_bits = []
    if author.affiliation:
        meta_bits.append(html.escape(author.affiliation))
    if author.email:
        meta_bits.append(html.escape(author.email))
    if author.source:
        meta_bits.append(html.escape(author.source))
    meta = " · ".join(meta_bits)

    link_html = "".join(
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(LABELS.get(p, p))}</a>'
        for p, url in links.items()
    )
    urls_js = html.escape(json.dumps(list(links.values())))
    search_blob = html.escape(
        f"{author.name} {author.affiliation or ''} {author.email or ''}".lower()
    )
    return f"""
    <div class="card" data-search="{search_blob}">
      <h3>{name}</h3>
      <div class="meta">{meta}</div>
      <div class="links">{link_html}</div>
      <div class="openall"><button onclick='openAll({urls_js})'>Open all profiles</button></div>
    </div>"""


def build_dashboard(
    authors: List[Author],
    platforms: List[str],
    title: Optional[str] = None,
    sources: Optional[List[str]] = None,
) -> str:
    """Return a complete HTML document as a string."""
    # Bulk "open all X" buttons, one per platform present.
    bulk_buttons = []
    for p in platforms:
        urls = [profile_links(a, [p]).get(p) for a in authors]
        urls = [u for u in urls if u]
        urls_js = html.escape(json.dumps(urls))
        bulk_buttons.append(
            f'<button class="bulk" onclick=\'openAll({urls_js})\'>Open all {html.escape(LABELS.get(p, p))}</button>'
        )
    bulk_html = "".join(bulk_buttons)

    cards = "".join(_card(i, a, platforms) for i, a in enumerate(authors))
    subtitle = html.escape(title) if title else "Extracted authors"
    src_line = ""
    if sources:
        src_line = f'<div class="sub">Sources: {html.escape(", ".join(sources))}</div>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>namescout — {subtitle}</title>
<style>{_STYLE}</style></head>
<body>
<header>
  <h1>{subtitle}</h1>
  <div class="sub">{len(authors)} authors · generated by namescout</div>
  {src_line}
</header>
<div class="toolbar">
  <input type="text" placeholder="Filter authors…" oninput="filterCards(this.value)">
  {bulk_html}
</div>
<div class="count">{len(authors)} authors</div>
<div class="grid">{cards}</div>
<footer>Tip: bulk buttons open one tab per author with a small delay — allow pop-ups for this file.
There is no API to auto-follow/invite on LinkedIn or X, so these open targeted searches for you to action.</footer>
<script>{_SCRIPT}</script>
</body></html>"""

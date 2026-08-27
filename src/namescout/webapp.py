"""A tiny, dependency-free web UI for namescout.

Upload files / paste a link / paste text in the browser; get back the same
clickable dashboard the CLI produces. Built on the standard library only
(http.server) so it runs anywhere Python does, with nothing extra to install.

Run:  namescout-web            # then open http://localhost:8765
      namescout-web --port 9000 --host 127.0.0.1
"""
from __future__ import annotations

import argparse
import html
import os
import re
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Tuple

from . import dispatch, report
from .dedup import dedupe
from .models import Author
from .profiles import ALL_PLATFORMS, DEFAULT_PLATFORMS, LABELS

MAX_UPLOAD = 40 * 1024 * 1024  # 40 MB total request cap


# --- multipart/form-data parsing (stdlib only) -------------------------------

def _parse_multipart(body: bytes, boundary: bytes) -> Tuple[Dict[str, str], List[Tuple[str, bytes]]]:
    """Return (text_fields, files) from a multipart body.

    Kept deliberately small; handles exactly the shape browsers send for our
    form (text inputs, checkboxes and file uploads).
    """
    fields: Dict[str, str] = {}
    files: List[Tuple[str, bytes]] = []
    for part in body.split(b"--" + boundary):
        if not part or part in (b"--\r\n", b"--"):
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        if b"\r\n\r\n" not in part:
            continue
        raw_headers, content = part.split(b"\r\n\r\n", 1)
        headers = raw_headers.decode("utf-8", "ignore")
        name_m = re.search(r'name="([^"]*)"', headers)
        file_m = re.search(r'filename="([^"]*)"', headers)
        if not name_m:
            continue
        if file_m and file_m.group(1):
            files.append((file_m.group(1), content))
        else:
            # multiple checkboxes share a name -> keep them all, comma-joined.
            val = content.decode("utf-8", "ignore")
            key = name_m.group(1)
            fields[key] = f"{fields[key]},{val}" if key in fields else val
    return fields, files


# --- request handling --------------------------------------------------------

def _collect_inputs(fields: Dict[str, str], files: List[Tuple[str, bytes]], tmpdir: str) -> List[str]:
    inputs: List[str] = []
    # 1. uploaded files -> temp paths (preserve extension so dispatch can classify)
    for i, (filename, data) in enumerate(files):
        if not data:
            continue
        ext = os.path.splitext(filename)[1] or ".txt"
        path = os.path.join(tmpdir, f"upload_{i}{ext}")
        with open(path, "wb") as f:
            f.write(data)
        inputs.append(path)
    # 2. links / ids: one per line or whitespace-separated
    for token in re.split(r"\s+", fields.get("links", "").strip()):
        if token:
            inputs.append(token)
    # 3. free text: processed as a single raw-text input
    text = fields.get("text", "").strip()
    if text:
        inputs.append(text)
    return inputs


def _resolve_platforms(fields: Dict[str, str]) -> List[str]:
    chosen = [p for p in fields.get("platforms", "").split(",") if p in ALL_PLATFORMS]
    return chosen or list(DEFAULT_PLATFORMS)


class Handler(BaseHTTPRequestHandler):
    server_version = "namescout"

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(form_page())
        else:
            self._send_html("<h1>404</h1>", status=404)

    def do_POST(self):
        if self.path != "/extract":
            self._send_html("<h1>404</h1>", status=404)
            return
        ctype = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_UPLOAD:
            self._send_html("<h1>Request too large</h1>", status=413)
            return
        body = self.rfile.read(length)

        m = re.search(r"boundary=([^;]+)", ctype)
        if "multipart/form-data" not in ctype or not m:
            self._send_html("<h1>Expected a form submission</h1>", status=400)
            return
        boundary = m.group(1).strip('"').encode()
        fields, files = _parse_multipart(body, boundary)
        platforms = _resolve_platforms(fields)

        authors: List[Author] = []
        titles: List[str] = []
        sources: List[str] = []
        errors: List[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for item in _collect_inputs(fields, files, tmp):
                try:
                    ex = dispatch.process(item)
                except Exception as e:
                    errors.append(f"{item[:60]}: {e}")
                    continue
                authors.extend(ex.authors)
                if ex.title:
                    titles.append(ex.title)
                sources.append(ex.source or item)

        authors = dedupe(authors)
        if not authors:
            note = "No names found."
            if errors:
                note += " Errors: " + "; ".join(errors)
            self._send_html(form_page(message=note))
            return

        title = titles[0] if len(titles) == 1 else None
        page = report.build_dashboard(authors, platforms, title=title, sources=sources)
        # Add a "start over" link at the top of the results dashboard.
        page = page.replace(
            "<body>",
            '<body><div style="padding:10px 24px"><a href="/">← New extraction</a></div>',
            1,
        )
        self._send_html(page)


# --- the input form ----------------------------------------------------------

def form_page(message: str = "") -> str:
    checks = "".join(
        f'<label class="chk"><input type="checkbox" name="platforms" value="{p}"'
        f'{" checked" if p in DEFAULT_PLATFORMS else ""}> {html.escape(LABELS[p])}</label>'
        for p in ALL_PLATFORMS
    )
    banner = f'<div class="msg">{html.escape(message)}</div>' if message else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>namescout</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif; max-width:760px;
  margin:0 auto; padding:24px; }}
h1 {{ margin-bottom:2px; }} .tag {{ opacity:.7; margin-top:0; }}
fieldset {{ border:1px solid #ccc; border-radius:10px; margin:16px 0; padding:14px 16px; }}
legend {{ font-weight:600; padding:0 6px; }}
input[type=text], textarea {{ width:100%; padding:9px 10px; border:1px solid #bbb;
  border-radius:6px; font-size:14px; background:transparent; color:inherit; }}
textarea {{ min-height:120px; }}
.chk {{ display:inline-block; margin:4px 12px 4px 0; font-size:14px; }}
button {{ background:#0b5cff; color:#fff; border:0; border-radius:8px; padding:11px 20px;
  font-size:15px; cursor:pointer; }}
.msg {{ background:#fff3cd; color:#664d03; border:1px solid #ffe69c; padding:10px 12px;
  border-radius:8px; margin:10px 0; }}
small {{ opacity:.7; }}
</style></head>
<body>
<h1>namescout</h1>
<p class="tag">Extract people's names from any document, link or PDF — then open their profiles.</p>
{banner}
<form method="POST" action="/extract" enctype="multipart/form-data">
  <fieldset>
    <legend>Files</legend>
    <input type="file" name="files" multiple accept=".pdf,.docx,.csv,.txt,.md,.html,.htm">
    <div><small>PDF, DOCX, CSV, TXT, or a saved .html page — multiple allowed.</small></div>
  </fieldset>
  <fieldset>
    <legend>Links / arXiv IDs / DOIs</legend>
    <input type="text" name="links" placeholder="https://arxiv.org/abs/1706.03762   10.1038/nature14539   https://a-page.com/team">
    <div><small>One or more, separated by spaces or new lines. Papers use exact author lists.</small></div>
  </fieldset>
  <fieldset>
    <legend>Or paste text</legend>
    <textarea name="text" placeholder="Paste any text containing names…"></textarea>
  </fieldset>
  <fieldset>
    <legend>Profiles to link</legend>
    {checks}
  </fieldset>
  <button type="submit">Extract names →</button>
</form>
<p><small>There's no API to auto-invite on LinkedIn/X — namescout opens targeted searches you can action in one click.</small></p>
</body></html>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="namescout-web", description="Local web UI for namescout.")
    ap.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1 — local only).")
    ap.add_argument("--port", type=int, default=8765, help="Port (default 8765).")
    args = ap.parse_args(argv)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"namescout web UI running at {url}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared pieces of the paste-a-list-of-membership-numbers lookup tools
(`officer_lookup/`, `member_society_lookup/`): number normalization, CLI
number parsing, and the self-contained local HTML page shell."""
from __future__ import annotations

import argparse
from pathlib import Path

_CSS_TOP = """  :root {
    --bg: #f7f7f8; --surface: #ffffff; --border: #dcdde1;
    --text: #1c1e21; --text-muted: #6b7280; --accent: #0057b8;
  }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #16181c; --surface: #1f2226; --border: #33363b; --text: #e8e9eb; --text-muted: #9aa0a8; --accent: #6ea8fe; }
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
"""

_CSS_MID = """  h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
  .subtitle { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.5rem; }
  textarea { width: 100%; min-height: 140px; padding: 0.75rem; border: 1px solid var(--border);
    border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; resize: vertical; }
  .controls { margin-top: 0.75rem; display: flex; gap: 0.5rem; align-items: center; }
  button { background: var(--accent); color: white; border: none; padding: 0.6rem 1.1rem;
    border-radius: 6px; font-size: 0.95rem; cursor: pointer; }
  button:hover { opacity: 0.9; }
  .status { color: var(--text-muted); font-size: 0.85rem; }
  table { width: 100%; border-collapse: collapse; margin-top: 1.5rem; }
  th, td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); }
  th { color: var(--text-muted); font-weight: 600; font-size: 0.85rem; }
"""

_CSS_BOTTOM = """  .not-found { margin-top: 1.25rem; font-size: 0.85rem; color: var(--text-muted); }
  .not-found code { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0.1rem 0.35rem; }
"""

_JS_NORMALIZE = """  function normalize(n) {
    n = n.trim();
    return /^\\d+$/.test(n) ? String(parseInt(n, 10)) : n;
  }
"""

# Reads the textarea, resets the results table, bails out on empty input.
# Defines: numbers, statusEl, table, body, notFoundEl.
_JS_HANDLER_HEAD = """  document.getElementById('run').addEventListener('click', () => {
    const raw = document.getElementById('input').value;
    const numbers = raw.split(/[\\s,]+/).map(s => s.trim()).filter(Boolean);
    const statusEl = document.getElementById('status');
    const table = document.getElementById('results');
    const body = document.getElementById('results-body');
    const notFoundEl = document.getElementById('not-found');
    body.innerHTML = '';
    notFoundEl.hidden = true;
    table.hidden = true;

    if (!numbers.length) {
      statusEl.textContent = 'Paste at least one membership number.';
      return;
    }
"""


def normalize(number: str) -> str:
    number = number.strip()
    return str(int(number)) if number.isdigit() else number


def parse_cli_numbers(doc: str | None) -> list[str]:
    """Membership numbers from positional args and/or `--file`."""
    parser = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("numbers", nargs="*", help="Membership numbers")
    parser.add_argument("--file", type=Path, help="Text file with one membership number per line")
    args = parser.parse_args()
    numbers = list(args.numbers)
    if args.file:
        numbers += [line.strip() for line in args.file.read_text().splitlines() if line.strip()]
    return numbers


def write_lookup_page(
    path: Path,
    *,
    title: str,
    wrap_px: int,
    extra_css: str,
    subtitle: str,
    button_label: str,
    content_html: str,
    data_js: str,
    handler_body_js: str,
) -> None:
    """`extra_css` goes between the shared table rules and `.not-found`;
    `handler_body_js` runs after the shared click-handler preamble (see
    `_JS_HANDLER_HEAD`) and must not close the handler."""
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
{_CSS_TOP}  .wrap {{ max-width: {wrap_px}px; margin: 0 auto; }}
{_CSS_MID}{extra_css}{_CSS_BOTTOM}</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <p class="subtitle">{subtitle}</p>
  <textarea id="input" placeholder="0001&#10;0002&#10;0003"></textarea>
  <div class="controls">
    <button id="run">{button_label}</button>
    <span class="status" id="status"></span>
  </div>
{content_html}  <div class="not-found" id="not-found" hidden></div>
</div>
<script>
{data_js}
{_JS_NORMALIZE}
{_JS_HANDLER_HEAD}{handler_body_js}  }});
</script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")

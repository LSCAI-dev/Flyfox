"""
Scans docs/archive/ for dated report snapshots (created by the workflow
after each run) and builds docs/archive/index.html -- a simple browsable
list linking to every past watchlist and backtest report, most recent
first, so nothing gets silently overwritten and lost.

Usage:
    python build_archive_index.py --archive-dir docs/archive
"""
import argparse
import os
import re
from pathlib import Path

COLOR_BG = "#0A0E14"
COLOR_SURFACE = "#121824"
COLOR_BORDER = "#212A38"
COLOR_TEXT = "#E9EDF2"
COLOR_MUTED = "#7C8899"
COLOR_GOLD = "#E8B45C"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SGX Screener — Report Archive</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  :root {{ --bg: {bg}; --surface: {surface}; --border: {border}; --text: {text}; --muted: {muted}; --gold: {gold}; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 48px 24px 80px;
    background: radial-gradient(1200px 600px at 50% -10%, #141C2A 0%, var(--bg) 55%);
    color: var(--text); font-family: 'Inter', sans-serif;
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  .eyebrow {{
    font-family: 'IBM Plex Mono', monospace; color: var(--gold); font-size: 13px;
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px;
  }}
  h1 {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 30px; margin: 0 0 8px; }}
  .subtitle {{ color: var(--muted); font-size: 14px; margin: 0 0 32px; }}
  h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 16px; margin: 32px 0 12px; }}
  .back-link {{ display: inline-block; margin-bottom: 28px; color: var(--muted); font-size: 13px; text-decoration: none; }}
  .back-link:hover {{ color: var(--gold); }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 16px; margin-bottom: 8px;
  }}
  a.report-link {{ color: var(--text); text-decoration: none; font-family: 'IBM Plex Mono', monospace; font-size: 14px; }}
  a.report-link:hover {{ color: var(--gold); }}
  .empty {{ color: var(--muted); font-size: 13px; font-style: italic; }}
</style>
</head>
<body>
<div class="wrap">
  <a class="back-link" href="../index.html">&larr; Back to latest watchlist</a>
  <div class="eyebrow">SGX Screener</div>
  <h1>Report Archive</h1>
  <p class="subtitle">Every past run, kept -- nothing here gets overwritten.</p>

  <h2>Watchlist Reports</h2>
  {watchlist_items}

  <h2>Backtest Reports</h2>
  {backtest_items}
</div>
</body>
</html>
"""


def _list_items(files, label_fn):
    if not files:
        return '<p class="empty">No archived reports yet.</p>'
    items = []
    for f in files:
        items.append(f'<li><a class="report-link" href="{f.name}">{label_fn(f.name)}</a></li>')
    return f"<ul>{''.join(items)}</ul>"


def _label_from_filename(name: str, prefix: str) -> str:
    # e.g. "watchlist-2026-08-24.html" -> "2026-08-24"
    # e.g. "backtest-2026-08-24_2003.html" -> "2026-08-24 20:03 UTC"
    m = re.match(rf"{prefix}-(\d{{4}}-\d{{2}}-\d{{2}})(?:_(\d{{2}})(\d{{2}}))?\.html", name)
    if not m:
        return name
    date_part, hh, mm = m.groups()
    if hh:
        return f"{date_part} {hh}:{mm} UTC"
    return date_part


def build_archive_index(archive_dir: str):
    path = Path(archive_dir)
    path.mkdir(parents=True, exist_ok=True)

    watchlist_files = sorted(path.glob("watchlist-*.html"), reverse=True)
    backtest_files = sorted(path.glob("backtest-*.html"), reverse=True)

    html = PAGE_TEMPLATE.format(
        bg=COLOR_BG, surface=COLOR_SURFACE, border=COLOR_BORDER, text=COLOR_TEXT,
        muted=COLOR_MUTED, gold=COLOR_GOLD,
        watchlist_items=_list_items(watchlist_files, lambda n: _label_from_filename(n, "watchlist")),
        backtest_items=_list_items(backtest_files, lambda n: _label_from_filename(n, "backtest")),
    )
    out_path = path / "index.html"
    out_path.write_text(html)
    return str(out_path)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--archive-dir", default="docs/archive")
    args = p.parse_args()
    out = build_archive_index(args.archive_dir)
    print(f"Archive index written to {out}")

"""
Generates sgx_report.html from a watchlist DataFrame/CSV produced by
sgx_screener.py. Run standalone against sgx_watchlist.csv, or import
build_report(df) and call it directly after run_screen().
"""
import datetime as dt
import html
import json
from zoneinfo import ZoneInfo
import pandas as pd

import chart_generator as cg

CARD_TEMPLATE = """
<div class="card">
  <div class="card-head">
    <div class="ticker-block">
      <span class="ticker">{ticker}</span>
      <span class="name">{name}</span>
      <span class="sector">{sector}</span>
    </div>
    <div class="rr-badge">{rr:.1f}R</div>
  </div>

  <div class="stats-row">
    <div class="stat"><span class="stat-label">Price</span><span class="stat-value">{price}</span></div>
    <div class="stat"><span class="stat-label">VWAP(20)</span><span class="stat-value">{vwap}</span></div>
    <div class="stat"><span class="stat-label">Price/VWAP</span><span class="stat-value">{price_vwap_ratio}</span></div>
    <div class="stat"><span class="stat-label">Rel Vol</span><span class="stat-value">{rel_vol}</span></div>
    <div class="stat"><span class="stat-label">Ask/Bid<sup>*</sup></span><span class="stat-value">{ask_bid_ratio}</span></div>
  </div>

  <div class="gauge">
    <div class="gauge-track">
      <div class="gauge-risk" style="width:{risk_pct:.2f}%"></div>
      <div class="gauge-reward" style="width:{reward_pct:.2f}%"></div>
      <div class="gauge-marker" style="left:{entry_pct:.2f}%"></div>
    </div>
    <div class="gauge-labels">
      <span class="lbl-stop">Stop {stop:.3f}</span>
      <span class="lbl-entry">Entry {entry:.3f}</span>
      <span class="lbl-target">Target {target:.3f}</span>
    </div>
  </div>

  <div class="reasons">
    <div class="reason-row"><span class="reason-tag stop">Stop</span> {stop_reason}</div>
    <div class="reason-row"><span class="reason-tag entry">Entry</span> {entry_reason}</div>
    <div class="reason-row"><span class="reason-tag target">Target</span> {target_reason}</div>
  </div>

  <div class="chart-wrap">
    {chart_html}
  </div>

  <div class="signals">
    <div class="signal-group">
      <span class="signal-label fa">FA</span>
      {fa_chips}
    </div>
    <div class="signal-group">
      <span class="signal-label ta">TA</span>
      {ta_chips}
    </div>
  </div>

  <div class="news-section">
    <div class="news-heading">Recent News<sup>†</sup></div>
    {news_html}
  </div>
</div>
"""

CHIP = '<span class="chip {cls}">{text}</span>'


def _chips(text_list, cls):
    if not text_list:
        return '<span class="chip none">—</span>'
    return " ".join(CHIP.format(cls=cls, text=t) for t in text_list)


def _chart_embed(ticker, entry, stop, target, demo=False, period="9mo") -> str:
    """Builds the interactive candlestick+indicators chart for one ticker and
    returns an embeddable HTML snippet (Plotly div + script). Plotly's JS
    library itself is loaded once via CDN in the page <head>, not per-chart,
    to keep the report from repeating it for every stock."""
    try:
        hist = cg.load_data(ticker, period=period, demo=demo)
        return cg.generate_chart_html(ticker, hist, entry=entry, stop=stop, target=target, include_js=False)
    except Exception as e:
        return f'<div class="chart-fallback">Chart unavailable for {ticker}: {e}</div>'


def _news_html(news_field) -> str:
    """Renders the JSON-encoded news list (from the 'News' CSV column) as a
    small list of headline links. Titles/publishers come from an external
    feed, so everything is HTML-escaped before insertion."""
    if news_field is None or (isinstance(news_field, float) and pd.isna(news_field)):
        return '<div class="news-empty">No recent news found for this ticker.</div>'
    try:
        items = json.loads(news_field) if isinstance(news_field, str) else news_field
    except (json.JSONDecodeError, TypeError):
        items = []
    if not items:
        return '<div class="news-empty">No recent news found for this ticker.</div>'

    rows_html = []
    for item in items:
        title = html.escape(str(item.get("title", "")).strip())
        publisher = html.escape(str(item.get("publisher", "Unknown")).strip())
        published = html.escape(str(item.get("published", "")).strip())
        link = html.escape(str(item.get("link", "")).strip())
        meta = " · ".join(x for x in [publisher, published] if x)
        if link:
            rows_html.append(
                f'<div class="news-item"><a href="{link}" target="_blank" rel="noopener noreferrer">{title}</a>'
                f'<div class="news-meta">{meta}</div></div>'
            )
        else:
            rows_html.append(f'<div class="news-item">{title}<div class="news-meta">{meta}</div></div>')
    return "\n".join(rows_html)


def _card_html(row, demo=False) -> str:
    entry, stop, target = row["Entry"], row["Stop"], row["Target"]
    span = target - stop
    risk_pct = ((entry - stop) / span) * 100 if span else 0
    reward_pct = ((target - entry) / span) * 100 if span else 0
    entry_pct = risk_pct

    fa_list = [s.strip() for s in str(row["FA Signals"]).split(",") if s.strip()]
    ta_list = [s.strip() for s in str(row["TA Signals"]).split(",") if s.strip()]

    chart_html = _chart_embed(row["Ticker"], entry, stop, target, demo=demo)

    entry_reason = row["Entry Reason"] if "Entry Reason" in row and pd.notna(row["Entry Reason"]) else "Last closing price"
    stop_reason = row["Stop Reason"] if "Stop Reason" in row and pd.notna(row["Stop Reason"]) else "—"
    target_reason = row["Target Reason"] if "Target Reason" in row and pd.notna(row["Target Reason"]) else "—"

    rel_vol = f"{row['Rel Vol']:.2f}x" if "Rel Vol" in row and pd.notna(row["Rel Vol"]) else "—"
    ask_bid_ratio = f"{row['Ask/Bid Ratio (approx)']:.2f}" if "Ask/Bid Ratio (approx)" in row and pd.notna(row["Ask/Bid Ratio (approx)"]) else "—"

    price = f"{row['Price']:.3f}" if "Price" in row and pd.notna(row["Price"]) else "—"
    vwap = f"{row['VWAP']:.3f}" if "VWAP" in row and pd.notna(row["VWAP"]) else "—"
    price_vwap_ratio = f"{row['Price/VWAP']:.3f}" if "Price/VWAP" in row and pd.notna(row["Price/VWAP"]) else "—"

    news_html = _news_html(row.get("News") if "News" in row else None)

    return CARD_TEMPLATE.format(
        ticker=row["Ticker"], name=row["Name"], sector=row["Sector"],
        rel_vol=rel_vol, ask_bid_ratio=ask_bid_ratio,
        price=price, vwap=vwap, price_vwap_ratio=price_vwap_ratio,
        rr=row["R:R"], risk_pct=risk_pct, reward_pct=reward_pct, entry_pct=entry_pct,
        stop=stop, entry=entry, target=target, chart_html=chart_html,
        entry_reason=entry_reason, stop_reason=stop_reason, target_reason=target_reason,
        fa_chips=_chips(fa_list, "fa"), ta_chips=_chips(ta_list, "ta"),
        news_html=news_html,
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>SGX Swing Watchlist — {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
{plotly_cdn_tag}
<style>
  :root {{
    --bg: #0A0E14;
    --surface: #121824;
    --border: #212A38;
    --text: #E9EDF2;
    --muted: #7C8899;
    --bull: #35D48C;
    --risk: #FF5C6A;
    --gold: #E8B45C;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 48px 24px 80px;
    background: radial-gradient(1200px 600px at 50% -10%, #141C2A 0%, var(--bg) 55%);
    color: var(--text);
    font-family: 'Inter', sans-serif;
  }}
  .wrap {{ max-width: 880px; margin: 0 auto; }}
  header {{ margin-bottom: 40px; }}
  .eyebrow {{
    font-family: 'IBM Plex Mono', monospace;
    color: var(--gold); font-size: 13px; letter-spacing: 0.08em;
    text-transform: uppercase; margin-bottom: 10px;
  }}
  h1 {{
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700; font-size: 34px; margin: 0 0 8px;
    letter-spacing: -0.01em;
  }}
  .subtitle {{ color: var(--muted); font-size: 15px; margin: 0; }}
  .summary-row {{ display: flex; gap: 28px; margin-top: 24px; }}
  .summary-item {{ }}
  .summary-num {{ font-family: 'Space Grotesk', sans-serif; font-size: 26px; font-weight: 700; }}
  .summary-lbl {{ font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }}

  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 22px 24px; margin-bottom: 16px;
  }}
  .card-head {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }}
  .ticker-block {{ display: flex; flex-direction: column; gap: 2px; }}
  .ticker {{ font-family: 'IBM Plex Mono', monospace; font-weight: 600; font-size: 18px; }}
  .name {{ font-size: 15px; font-weight: 500; }}
  .sector {{ font-size: 12px; color: var(--muted); }}
  .rr-badge {{
    font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 15px;
    color: var(--bg); background: var(--bull); padding: 6px 14px; border-radius: 999px;
    height: fit-content;
  }}

  .stats-row {{ display: flex; gap: 20px; margin-bottom: 18px; }}
  .stat {{
    display: flex; flex-direction: column; gap: 2px; padding: 8px 14px;
    background: rgba(255,255,255,0.03); border: 1px solid var(--border); border-radius: 8px;
  }}
  .stat-label {{
    font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.05em;
  }}
  .stat-value {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 16px; }}

  .gauge {{ margin-bottom: 18px; }}
  .gauge-track {{
    position: relative; height: 8px; border-radius: 999px;
    background: var(--border); overflow: visible; display: flex;
  }}
  .gauge-risk {{ background: var(--risk); border-radius: 999px 0 0 999px; opacity: 0.55; }}
  .gauge-reward {{ background: var(--bull); border-radius: 0 999px 999px 0; opacity: 0.85; }}
  .gauge-marker {{
    position: absolute; top: -4px; width: 3px; height: 16px;
    background: var(--text); border-radius: 2px; transform: translateX(-50%);
  }}
  .gauge-labels {{
    display: flex; justify-content: space-between; margin-top: 8px;
    font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--muted);
  }}
  .lbl-stop {{ color: var(--risk); }}
  .lbl-target {{ color: var(--bull); }}

  .reasons {{ margin-bottom: 16px; }}
  .reason-row {{
    font-size: 12.5px; color: var(--muted); line-height: 1.7;
  }}
  .reason-tag {{
    font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; font-weight: 600;
    letter-spacing: 0.04em; padding: 1px 6px; border-radius: 4px; margin-right: 6px;
    display: inline-block; min-width: 46px; text-align: center;
  }}
  .reason-tag.stop {{ background: rgba(255,92,106,0.15); color: var(--risk); }}
  .reason-tag.entry {{ background: rgba(233,237,242,0.1); color: var(--text); }}
  .reason-tag.target {{ background: rgba(53,212,140,0.15); color: var(--bull); }}

  .signals {{ display: flex; gap: 28px; flex-wrap: wrap; }}
  .signal-group {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .signal-label {{
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600;
    letter-spacing: 0.06em; padding: 3px 7px; border-radius: 5px;
  }}
  .signal-label.fa {{ background: rgba(232,180,92,0.15); color: var(--gold); }}
  .signal-label.ta {{ background: rgba(53,212,140,0.15); color: var(--bull); }}
  .chip {{
    font-size: 12.5px; padding: 4px 10px; border-radius: 999px;
    border: 1px solid var(--border); color: var(--text);
  }}
  .chip.none {{ color: var(--muted); border-style: dashed; }}

  .chart-wrap {{
    border-radius: 10px; border: 1px solid var(--border); margin-bottom: 18px;
    overflow: hidden; background: var(--bg);
  }}
  .chart-fallback {{
    color: var(--muted); font-size: 12.5px; font-style: italic;
    padding: 10px 0; margin-bottom: 12px;
  }}

  .empty-state {{ text-align: center; padding: 48px 24px; }}
  .empty-icon {{ font-size: 28px; color: var(--muted); margin-bottom: 12px; }}
  .empty-title {{
    font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 18px;
    margin-bottom: 10px;
  }}
  .empty-body {{ color: var(--muted); font-size: 13.5px; line-height: 1.6; max-width: 480px; margin: 0 auto; }}
  .empty-body code {{
    font-family: 'IBM Plex Mono', monospace; font-size: 12px;
    background: rgba(255,255,255,0.06); padding: 2px 5px; border-radius: 4px;
  }}

  .news-section {{ margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--border); }}
  .news-heading {{
    font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600;
    letter-spacing: 0.05em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px;
  }}
  .news-item {{ font-size: 13px; margin-bottom: 10px; }}
  .news-item a {{ color: var(--text); text-decoration: none; }}
  .news-item a:hover {{ text-decoration: underline; color: var(--gold); }}
  .news-meta {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; }}
  .news-empty {{ font-size: 12.5px; color: var(--muted); font-style: italic; }}

  footer {{ margin-top: 36px; color: var(--muted); font-size: 12.5px; line-height: 1.6; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="eyebrow">SGX · Swing Screen</div>
    <h1>Swing Watchlist</h1>
    <p class="subtitle">Fundamental strength × technical entry timing — generated {date}</p>
    <div class="summary-row">
      <div class="summary-item"><div class="summary-num">{count}</div><div class="summary-lbl">Candidates</div></div>
      <div class="summary-item"><div class="summary-num">{avg_rr:.1f}</div><div class="summary-lbl">Avg R:R</div></div>
      <div class="summary-item"><div class="summary-num">2:1</div><div class="summary-lbl">Min R:R filter</div></div>
    </div>
  </header>

  {cards}

  <footer>
    Entry = breakout trigger above resistance, pullback at support, or trend-continuation (see each
    stock's Entry reason). Stop = recent swing low (capped ~3% risk). Target = greater of 2R or nearest
    resistance. FA filters: P/E below sector median, revenue growth, debt/equity &lt; 100%, 5yr dividend
    consistency. Every candidate must be in a confirmed uptrend (20-EMA above 50-EMA, both sloping
    upward) with MACD at or above its signal line. Additional TA triggers: RSI turn from oversold,
    MACD cross, volume surge. Rel Vol = today's volume ÷ average volume of the prior 20 sessions.
    VWAP on the chart is a rolling 20-day volume-weighted average (not an intraday session VWAP,
    since this system uses daily bars).
    <br><sup>*</sup>Ask/Bid is an approximation, not real order-flow data — Yahoo Finance has no
    bid/ask trade classification, so this proxies buy vs. sell pressure using volume on up-closing
    days vs. down-closing days over the last 20 sessions.
    Charts are interactive — hover to see price/VWAP/volume/RSI/MACD together, scroll to zoom, drag to pan.
    <br><sup>†</sup>Recent News is Yahoo Finance's own aggregated headline feed (wire services, press
    releases, analyst notes) — not an AI-generated summary. Coverage for smaller SGX names can be thin,
    and Yahoo's news feed has occasionally been known to surface items for the wrong ticker, so treat
    it as a pointer to check further rather than a verified summary.
    This is a screening tool, not investment advice — verify before sizing any position.
  </footer>
</div>
</body>
</html>
"""


EMPTY_STATE_HTML = """
<div class="card empty-state">
  <div class="empty-icon">—</div>
  <div class="empty-title">No candidates cleared every filter today</div>
  <p class="empty-body">
    That's normal — the screen requires fundamental strength AND a live technical
    trigger AND a 2:1 reward-to-risk at the same time, so some days nothing qualifies.
    Check back tomorrow, or loosen <code>min_fa_score</code> / <code>min_ta_score</code> /
    <code>MIN_RR</code> in <code>sgx_screener.py</code> to see near-misses.
  </p>
</div>
"""


def build_report(df: pd.DataFrame, out_path: str = "sgx_report.html", demo: bool = False):
    if len(df) == 0:
        cards = EMPTY_STATE_HTML
        avg_rr = 0
    else:
        card_list = []
        for _, row in df.iterrows():
            print(f"  building chart for {row['Ticker']}...")
            card_list.append(_card_html(row, demo=demo))
        cards = "\n".join(card_list)
        avg_rr = df["R:R"].mean()
    sgt_now = dt.datetime.now(ZoneInfo("Asia/Singapore"))
    generated_str = sgt_now.strftime("%d %b %Y, %I:%M %p SGT").replace(", 0", ", ")
    html = PAGE_TEMPLATE.format(
        date=generated_str,
        count=len(df), avg_rr=avg_rr, cards=cards,
        plotly_cdn_tag=cg.get_plotly_cdn_script_tag(),
    )
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="use synthetic price data instead of live fetch")
    p.add_argument("--out", default="sgx_report.html", help="output HTML path")
    p.add_argument("--csv", default="sgx_watchlist.csv", help="input watchlist CSV path")
    args = p.parse_args()

    try:
        df = pd.read_csv(args.csv)
    except pd.errors.EmptyDataError:
        df = pd.DataFrame(columns=["Ticker", "Name", "Sector", "Price", "Entry",
                                    "Stop", "Target", "R:R", "FA Score", "TA Score",
                                    "FA Signals", "TA Signals"])
    path = build_report(df, out_path=args.out, demo=args.demo)
    print(f"Report written to {path}")

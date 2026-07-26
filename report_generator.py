"""
Generates sgx_report.html from a watchlist DataFrame/CSV produced by
sgx_screener.py. Run standalone against sgx_watchlist.csv, or import
build_report(df) and call it directly after run_screen().
"""
import base64
import datetime as dt
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

  {chart_html}

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
</div>
"""

CHIP = '<span class="chip {cls}">{text}</span>'


def _chips(text_list, cls):
    if not text_list:
        return '<span class="chip none">—</span>'
    return " ".join(CHIP.format(cls=cls, text=t) for t in text_list)


def _chart_data_uri(ticker, entry, stop, target, demo=False, period="9mo") -> str:
    """Builds the candlestick+indicators chart for one ticker and returns it
    as a base64 data URI so the report stays a single portable HTML file."""
    try:
        hist = cg.load_data(ticker, period=period, demo=demo)
        tmp_path = f"/tmp/_chart_{ticker.replace('.', '_')}.png"
        cg.plot(ticker, hist, entry=entry, stop=stop, target=target, out=tmp_path)
        with open(tmp_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        return f'<img class="chart-img" src="data:image/png;base64,{b64}" alt="{ticker} candlestick chart">'
    except Exception as e:
        return f'<div class="chart-fallback">Chart unavailable for {ticker}: {e}</div>'


def _card_html(row, demo=False) -> str:
    entry, stop, target = row["Entry"], row["Stop"], row["Target"]
    span = target - stop
    risk_pct = ((entry - stop) / span) * 100 if span else 0
    reward_pct = ((target - entry) / span) * 100 if span else 0
    entry_pct = risk_pct

    fa_list = [s.strip() for s in str(row["FA Signals"]).split(",") if s.strip()]
    ta_list = [s.strip() for s in str(row["TA Signals"]).split(",") if s.strip()]

    chart_html = _chart_data_uri(row["Ticker"], entry, stop, target, demo=demo)

    return CARD_TEMPLATE.format(
        ticker=row["Ticker"], name=row["Name"], sector=row["Sector"],
        rr=row["R:R"], risk_pct=risk_pct, reward_pct=reward_pct, entry_pct=entry_pct,
        stop=stop, entry=entry, target=target, chart_html=chart_html,
        fa_chips=_chips(fa_list, "fa"), ta_chips=_chips(ta_list, "ta"),
    )


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SGX Swing Watchlist — {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
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

  .chart-img {{
    width: 100%; display: block; border-radius: 10px;
    border: 1px solid var(--border); margin-bottom: 18px;
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
    Entry = last close · Stop = recent swing low (capped ~3% risk) · Target = greater of 2R or nearest
    swing high. FA filters: P/E below sector median, revenue growth, debt/equity &lt; 100%, 5yr dividend
    consistency. Every candidate must be in a confirmed uptrend (20-EMA above 50-EMA,
    both sloping upward). Additional TA triggers: RSI turn from oversold, MACD cross, volume surge.
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
    html = PAGE_TEMPLATE.format(
        date=dt.date.today().strftime("%d %b %Y"),
        count=len(df), avg_rr=avg_rr, cards=cards,
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

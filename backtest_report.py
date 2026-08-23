"""
Builds backtest_report.html from the trades DataFrame produced by
backtest.py -- summary stats, an equity curve, and a per-stock breakdown,
in the same dark dashboard style as the daily watchlist report.
"""
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import chart_generator as cg  # reuse get_plotly_cdn_script_tag()

COLOR_BG = "#0A0E14"
COLOR_SURFACE = "#121824"
COLOR_BORDER = "#212A38"
COLOR_TEXT = "#E9EDF2"
COLOR_MUTED = "#7C8899"
COLOR_BULL = "#35D48C"
COLOR_BEAR = "#FF5C6A"
COLOR_GOLD = "#E8B45C"


def _summary_stats(df: pd.DataFrame) -> dict:
    open_count = int((df["exit_reason"] == "Still Open").sum()) if len(df) else 0
    closed = df[df["exit_reason"] != "Still Open"].copy()
    if len(closed) == 0:
        return dict(total=0, win_rate=0, avg_r=0, total_r=0, max_dd=0, profit_factor=0, open_count=open_count)
    wins = closed["r_achieved"] > 0
    win_rate = wins.mean()
    avg_r = closed["r_achieved"].mean()
    total_r = closed["r_achieved"].sum()
    cum_r = closed["r_achieved"].cumsum()
    running_max = cum_r.cummax()
    drawdown = cum_r - running_max
    max_dd = drawdown.min()
    gross_win = closed.loc[closed["r_achieved"] > 0, "r_achieved"].sum()
    gross_loss = -closed.loc[closed["r_achieved"] < 0, "r_achieved"].sum()
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    return dict(total=len(closed), win_rate=win_rate, avg_r=avg_r, total_r=total_r,
                max_dd=max_dd, profit_factor=profit_factor, open_count=open_count)


def _equity_curve_html(df: pd.DataFrame) -> str:
    df = df[df["exit_reason"] != "Still Open"]
    cum_r = df["r_achieved"].cumsum()
    colors = [COLOR_BULL if v >= 0 else COLOR_BEAR for v in df["r_achieved"]]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(1, len(df) + 1)), y=cum_r, mode="lines",
        line=dict(color=COLOR_GOLD, width=2), name="Cumulative R",
        hovertemplate="Trade #%{x}<br>Cumulative R: %{y:.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color=COLOR_MUTED, dash="dash", width=1))
    fig.update_layout(
        paper_bgcolor=COLOR_BG, plot_bgcolor=COLOR_BG,
        font=dict(color=COLOR_TEXT, size=11),
        margin=dict(l=50, r=30, t=20, b=40), height=320,
        xaxis=dict(title="Trade #", showgrid=True, gridcolor=COLOR_BORDER,
                    showspikes=True, spikemode="across", spikesnap="cursor", spikecolor=COLOR_TEXT),
        yaxis=dict(title="Cumulative R", showgrid=True, gridcolor=COLOR_BORDER),
        hovermode="x unified", hoverlabel=dict(bgcolor=COLOR_SURFACE, bordercolor=COLOR_BORDER),
        showlegend=False,
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, config={"displaylogo": False})


def _per_stock_rows(df: pd.DataFrame) -> str:
    df = df[df["exit_reason"] != "Still Open"]
    rows = []
    grouped = df.groupby("ticker")
    summary = grouped.agg(
        trades=("r_achieved", "count"),
        win_rate=("r_achieved", lambda x: (x > 0).mean()),
        avg_r=("r_achieved", "mean"),
        total_r=("r_achieved", "sum"),
    ).sort_values("total_r", ascending=False)
    for ticker, row in summary.iterrows():
        color = "pos" if row["total_r"] >= 0 else "neg"
        rows.append(
            f'<tr><td>{ticker}</td><td>{int(row["trades"])}</td>'
            f'<td>{row["win_rate"]:.0%}</td><td>{row["avg_r"]:.2f}</td>'
            f'<td class="{color}">{row["total_r"]:+.1f}</td></tr>'
        )
    return "\n".join(rows)


def _per_setup_rows(df: pd.DataFrame) -> str:
    df = df[df["exit_reason"] != "Still Open"]
    rows = []
    grouped = df.groupby("entry_reason")
    summary = grouped.agg(
        trades=("r_achieved", "count"),
        win_rate=("r_achieved", lambda x: (x > 0).mean()),
        avg_r=("r_achieved", "mean"),
        total_r=("r_achieved", "sum"),
    ).sort_values("total_r", ascending=False)
    for setup, row in summary.iterrows():
        color = "pos" if row["total_r"] >= 0 else "neg"
        rows.append(
            f'<tr><td>{setup}</td><td>{int(row["trades"])}</td>'
            f'<td>{row["win_rate"]:.0%}</td><td>{row["avg_r"]:.2f}</td>'
            f'<td class="{color}">{row["total_r"]:+.1f}</td></tr>'
        )
    return "\n".join(rows)


def _trade_rows(df: pd.DataFrame, max_rows=200) -> str:
    rows = []
    for _, r in df.tail(max_rows).iloc[::-1].iterrows():
        if r["exit_reason"] == "Still Open":
            r_display = f'{r["r_achieved"]:+.2f} (unrealized)' if pd.notna(r["r_achieved"]) else "—"
            color = "open"
        else:
            color = "pos" if r["r_achieved"] >= 0 else "neg"
            r_display = f'{r["r_achieved"]:+.2f}'
        rows.append(
            f'<tr><td>{r["entry_date"].date() if hasattr(r["entry_date"], "date") else r["entry_date"]}</td>'
            f'<td>{r["ticker"]}</td><td>{r["entry_reason"]}</td>'
            f'<td>{r["entry"]:.3f}</td><td>{r["stop"]:.3f}</td><td>{r["target"]:.3f}</td>'
            f'<td>{r["exit_reason"]}</td><td class="{color}">{r_display}</td></tr>'
        )
    return "\n".join(rows)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>SGX Screener Backtest — {date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
{plotly_cdn_tag}
<style>
  :root {{
    --bg: #0A0E14; --surface: #121824; --border: #212A38;
    --text: #E9EDF2; --muted: #7C8899; --bull: #35D48C; --risk: #FF5C6A; --gold: #E8B45C;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 48px 24px 80px;
    background: radial-gradient(1200px 600px at 50% -10%, #141C2A 0%, var(--bg) 55%);
    color: var(--text); font-family: 'Inter', sans-serif;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; }}
  .eyebrow {{
    font-family: 'IBM Plex Mono', monospace; color: var(--gold); font-size: 13px;
    letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 10px;
  }}
  h1 {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 32px; margin: 0 0 8px; }}
  .subtitle {{ color: var(--muted); font-size: 15px; margin: 0 0 28px; }}

  .stat-grid {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 28px; }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 20px; min-width: 130px; flex: 1;
  }}
  .stat-num {{ font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 24px; }}
  .stat-lbl {{ font-size: 11.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }}
  .pos {{ color: var(--bull); }}
  .neg {{ color: var(--risk); }}
  .open {{ color: var(--gold); }}

  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 22px 24px; margin-bottom: 20px; }}
  .card h2 {{ font-family: 'Space Grotesk', sans-serif; font-size: 16px; margin: 0 0 14px; }}

  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{
    text-align: left; font-family: 'IBM Plex Mono', monospace; font-size: 10.5px;
    color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em;
    padding: 8px 10px; border-bottom: 1px solid var(--border);
  }}
  td {{ padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.04); }}
  .trade-table-wrap {{ max-height: 480px; overflow-y: auto; }}

  footer {{ margin-top: 8px; color: var(--muted); font-size: 12px; line-height: 1.7; }}
  footer code {{ font-family: 'IBM Plex Mono', monospace; background: rgba(255,255,255,0.06); padding: 1px 5px; border-radius: 4px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="eyebrow">SGX Screener · Backtest</div>
  <h1>Technical Rules Backtest</h1>
  <p class="subtitle">EMA uptrend + MACD gate + entry/stop/target logic, replayed against historical price data — generated {date}</p>
  <p class="subtitle" style="margin-top:-18px;">{open_note}</p>
  <a href="archive/index.html" style="display:inline-block; margin-bottom:24px; color:var(--muted); font-size:12.5px; text-decoration:none;">View past runs &rarr;</a>

  <div class="stat-grid">
    <div class="stat-card"><div class="stat-num">{total}</div><div class="stat-lbl">Total Trades</div></div>
    <div class="stat-card"><div class="stat-num">{win_rate:.0%}</div><div class="stat-lbl">Win Rate</div></div>
    <div class="stat-card"><div class="stat-num {avg_r_class}">{avg_r:+.2f}R</div><div class="stat-lbl">Avg R / Trade</div></div>
    <div class="stat-card"><div class="stat-num {total_r_class}">{total_r:+.1f}R</div><div class="stat-lbl">Total R</div></div>
    <div class="stat-card"><div class="stat-num neg">{max_dd:.1f}R</div><div class="stat-lbl">Max Drawdown</div></div>
    <div class="stat-card"><div class="stat-num">{profit_factor}</div><div class="stat-lbl">Profit Factor</div></div>
  </div>

  <div class="card">
    <h2>Equity Curve (Cumulative R)</h2>
    {equity_html}
  </div>

  <div class="card">
    <h2>Breakdown by Setup Type</h2>
    <table>
      <tr><th>Setup</th><th>Trades</th><th>Win Rate</th><th>Avg R</th><th>Total R</th></tr>
      {per_setup_rows}
    </table>
  </div>

  <div class="card">
    <h2>Per-Stock Breakdown</h2>
    <table>
      <tr><th>Ticker</th><th>Trades</th><th>Win Rate</th><th>Avg R</th><th>Total R</th></tr>
      {per_stock_rows}
    </table>
  </div>

  <div class="card">
    <h2>Trade Log (most recent first)</h2>
    <div class="trade-table-wrap">
      <table>
        <tr><th>Entry Date</th><th>Ticker</th><th>Setup</th><th>Entry</th><th>Stop</th><th>Target</th><th>Exit</th><th>R</th></tr>
        {trade_rows}
      </table>
    </div>
  </div>

  <footer>
    <b>Methodology:</b> tests only the screener's <i>technical</i> rules (EMA20/50 uptrend gate, MACD-bullish
    gate, breakout/pullback/trend-continuation entry, stop capped at ~3% risk, target = greater of 2:1 R:R
    or resistance). Fundamental filters are NOT included -- Yahoo Finance only exposes current fundamentals,
    not point-in-time historical ones, so testing today's P/E against years-old price action would itself be
    a lookahead bias. One position at a time per ticker; a new signal is only taken for the following
    trading session, never the signal day itself. If a single day's bar would hit both stop and target
    (a gap), the stop is assumed to hit first (the standard conservative convention). Trades still open
    after <code>MAX_HOLD_DAYS</code> sessions are closed at that day's price as a "Timeout."
    <br><br>
    Past performance of this rule set on historical data does not guarantee future results -- markets
    change, and a backtest can't capture slippage, liquidity constraints, or execution timing precisely.
    Treat this as a sanity check on the logic, not a promise.
  </footer>
</div>
</body>
</html>
"""


def build_backtest_report(df: pd.DataFrame, out_path: str = "backtest_report.html"):
    stats = _summary_stats(df)
    sgt_now = dt.datetime.now(ZoneInfo("Asia/Singapore"))
    generated_str = sgt_now.strftime("%d %b %Y, %I:%M %p SGT").replace(", 0", ", ")

    open_count = stats.get("open_count", 0)
    open_note = (f"{open_count} signal(s) are still-open positions (too recent to have resolved yet) "
                 f"and are excluded from every stat below." if open_count else
                 "No open positions at the time of this run -- every signal has resolved.")

    if len(df) == 0:
        equity_html = '<p style="color:var(--muted)">No trades were generated over this period.</p>'
        per_stock_rows = ""
        per_setup_rows = ""
        trade_rows = ""
        pf_display = "—"
    else:
        equity_html = _equity_curve_html(df)
        per_stock_rows = _per_stock_rows(df)
        per_setup_rows = _per_setup_rows(df)
        trade_rows = _trade_rows(df)
        pf_display = f"{stats['profit_factor']:.2f}" if np.isfinite(stats['profit_factor']) else "∞"

    html = PAGE_TEMPLATE.format(
        date=generated_str, open_note=open_note,
        total=stats["total"], win_rate=stats["win_rate"],
        avg_r=stats["avg_r"], avg_r_class="pos" if stats["avg_r"] >= 0 else "neg",
        total_r=stats["total_r"], total_r_class="pos" if stats["total_r"] >= 0 else "neg",
        max_dd=stats["max_dd"], profit_factor=pf_display,
        equity_html=equity_html, per_stock_rows=per_stock_rows,
        per_setup_rows=per_setup_rows, trade_rows=trade_rows,
        plotly_cdn_tag=cg.get_plotly_cdn_script_tag(),
    )
    with open(out_path, "w") as f:
        f.write(html)
    return out_path

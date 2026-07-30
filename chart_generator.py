"""
Interactive candlestick chart (Plotly) with the exact indicators the
screener uses:
  - Price candles + 20/50-day EMAs + rolling VWAP (overlay)
  - Volume, with a dashed line at 1.5x the prior-20-day average (surge threshold)
  - RSI(14), with the 35 "oversold" line the screener checks
  - MACD histogram + MACD line + signal line

Unlike a static image, this is a real interactive chart: moving your mouse
along it shows a crosshair with a single unified tooltip giving you price
(OHLC), EMA20/50, VWAP, volume, RSI, and MACD all at that date, across every
panel at once. You can also scroll-zoom and drag to pan.

Usage:
    python chart_generator.py D05.SI --out chart.html
    python chart_generator.py D05.SI --entry 44.20 --stop 42.85 --target 48.35 --out chart.html

If yfinance can't reach the network (e.g. sandboxed environments), pass
--demo to plot synthetic sample data instead, purely to preview the layout.

Note on VWAP: true VWAP is an intraday measure that resets every trading
session, which needs intraday tick data. This chart works from daily bars
(matching the rest of the swing-trade system), so "VWAP" here is a rolling
20-day volume-weighted average price -- a common swing-trading approximation,
not a session VWAP.
"""
import argparse
import os
import numpy as np
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots

RSI_OVERSOLD = 35
VOLUME_SURGE_MULT = 1.5
VWAP_WINDOW = 20

COLOR_BG = "#0A0E14"
COLOR_GRID = "#1A2230"
COLOR_TEXT = "#E9EDF2"
COLOR_MUTED = "#7C8899"
COLOR_BULL = "#35D48C"
COLOR_BEAR = "#FF5C6A"
COLOR_GOLD = "#E8B45C"
COLOR_VWAP = "#9B8FE8"


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def vwap(df, window=VWAP_WINDOW):
    """Rolling N-day volume-weighted average price (see module docstring for
    why this is rolling rather than a true intraday session VWAP)."""
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    pv = typical * df["Volume"]
    return pv.rolling(window).sum() / df["Volume"].rolling(window).sum()


def make_demo_data(periods=180, seed=7):
    """Synthetic OHLCV purely to preview chart layout when live data is unreachable."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    periods = len(dates)
    rets = rng.normal(0.0006, 0.013, periods)
    rets[-15:] += 0.004  # bias the last ~15 sessions upward for a visible bullish setup
    close = 40 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.012, periods))
    low = close * (1 - rng.uniform(0.001, 0.012, periods))
    open_ = close * (1 + rng.normal(0, 0.004, periods))
    vol = rng.integers(1_500_000, 4_000_000, periods).astype(float)
    vol[-3:] *= 1.9  # volume surge near the end
    df = pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=dates)
    return df


def load_data(ticker, period="9mo", demo=False):
    if demo:
        return make_demo_data()
    hist = yf.Ticker(ticker).history(period=period)
    if hist.empty:
        raise SystemExit(f"No data returned for {ticker} -- network unreachable or bad ticker. Try --demo.")
    return hist[["Open", "High", "Low", "Close", "Volume"]]


def build_figure(ticker, df, entry=None, stop=None, target=None):
    ema20 = df["Close"].ewm(span=20, adjust=False).mean()
    ema50 = df["Close"].ewm(span=50, adjust=False).mean()
    vwap20 = vwap(df)
    rsi14 = rsi(df["Close"])
    macd_line, signal_line = macd(df["Close"])
    macd_hist = macd_line - signal_line
    vol_avg20 = df["Volume"].shift(1).rolling(20).mean()  # prior 20 days, excludes today
    surge_line = vol_avg20 * VOLUME_SURGE_MULT
    hist_colors = [COLOR_BULL if v >= 0 else COLOR_BEAR for v in macd_hist]
    vol_colors = [COLOR_BULL if c >= o else COLOR_BEAR for c, o in zip(df["Close"], df["Open"])]

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.5, 0.15, 0.15, 0.2], vertical_spacing=0.03,
    )

    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
        name="Price", increasing_line_color=COLOR_BULL, decreasing_line_color=COLOR_BEAR,
        increasing_fillcolor=COLOR_BULL, decreasing_fillcolor=COLOR_BEAR,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema20, name="EMA20", mode="lines",
                              line=dict(color=COLOR_BULL, width=1.3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=ema50, name="EMA50", mode="lines",
                              line=dict(color=COLOR_GOLD, width=1.3)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=vwap20, name=f"VWAP({VWAP_WINDOW})", mode="lines",
                              line=dict(color=COLOR_VWAP, width=1.3, dash="dot")), row=1, col=1)

    for level, color, label in [(entry, COLOR_TEXT, "Entry"), (stop, COLOR_BEAR, "Stop"), (target, COLOR_BULL, "Target")]:
        if level:
            fig.add_hline(y=level, line=dict(color=color, dash="dashdot", width=1.2),
                          annotation_text=f"{label} {level:.3f}", annotation_position="right",
                          annotation_font_color=color, row=1, col=1)

    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                          marker_color=vol_colors, opacity=0.7), row=2, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=surge_line, name="Vol surge (1.5x)", mode="lines",
                              line=dict(color=COLOR_MUTED, dash="dash", width=1)), row=2, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=rsi14, name="RSI(14)", mode="lines",
                              line=dict(color=COLOR_BULL, width=1.3)), row=3, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=[RSI_OVERSOLD] * len(df), name="Oversold (35)", mode="lines",
                              line=dict(color=COLOR_BEAR, dash="dash", width=1)), row=3, col=1)

    fig.add_trace(go.Bar(x=df.index, y=macd_hist, name="MACD hist",
                          marker_color=hist_colors, opacity=0.5), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=macd_line, name="MACD", mode="lines",
                              line=dict(color=COLOR_BULL, width=1.3)), row=4, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=signal_line, name="Signal", mode="lines",
                              line=dict(color=COLOR_BEAR, width=1.3)), row=4, col=1)

    fig.update_layout(
        title=dict(text=f"{ticker} — Price / Volume / RSI(14) / MACD", font=dict(size=14)),
        paper_bgcolor=COLOR_BG, plot_bgcolor=COLOR_BG,
        font=dict(color=COLOR_TEXT, size=11),
        showlegend=True,
        legend=dict(orientation="h", y=1.06, x=0, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#121824", font_size=11, bordercolor=COLOR_GRID),
        margin=dict(l=55, r=60, t=60, b=30),
        height=820,
        dragmode="pan",
    )
    for i in range(1, 5):
        fig.update_xaxes(showgrid=True, gridcolor=COLOR_GRID, showspikes=True, spikemode="across",
                          spikesnap="cursor", spikecolor=COLOR_TEXT, spikethickness=1,
                          rangeslider_visible=False, row=i, col=1)
        fig.update_yaxes(showgrid=True, gridcolor=COLOR_GRID, row=i, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1)
    fig.update_yaxes(title_text="MACD", row=4, col=1)
    return fig


def generate_chart_html(ticker, df, entry=None, stop=None, target=None, include_js=False):
    """Returns an HTML snippet (a <div> + <script>) for embedding inline in
    the report. include_js=False (default) assumes Plotly's library is
    already loaded once via CDN in the page <head> -- much smaller output
    per chart than embedding the full library on every single one."""
    fig = build_figure(ticker, df, entry=entry, stop=stop, target=target)
    return fig.to_html(full_html=False, include_plotlyjs="cdn" if include_js else False,
                        config={"scrollZoom": True, "displaylogo": False})


def generate_chart(ticker, df, entry=None, stop=None, target=None, out_dir="charts"):
    """CLI/standalone use: saves a self-contained interactive HTML file and
    returns its path."""
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{ticker.replace('.', '_')}.html")
    fig = build_figure(ticker, df, entry=entry, stop=stop, target=target)
    fig.write_html(out_path, include_plotlyjs="cdn", config={"scrollZoom": True, "displaylogo": False})
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?", default="D05.SI")
    p.add_argument("--period", default="9mo")
    p.add_argument("--entry", type=float, default=None)
    p.add_argument("--stop", type=float, default=None)
    p.add_argument("--target", type=float, default=None)
    p.add_argument("--demo", action="store_true", help="use synthetic data instead of live fetch")
    p.add_argument("--out", default="candlestick_chart.html")
    args = p.parse_args()

    data = load_data(args.ticker, args.period, demo=args.demo)
    fig = build_figure(args.ticker, data, entry=args.entry, stop=args.stop, target=args.target)
    fig.write_html(args.out, include_plotlyjs="cdn", config={"scrollZoom": True, "displaylogo": False})
    print(f"Saved interactive chart to {args.out}")

"""
Candlestick chart with the exact indicators the screener uses:
  - Price candles + 20/50 day EMAs (overlay)
  - Volume, with a horizontal line at 1.5x the 20d average (surge threshold)
  - RSI(14), with the 35 "oversold" line the screener checks
  - MACD line vs signal line

Usage:
    python chart_generator.py D05.SI
    python chart_generator.py D05.SI --entry 44.20 --stop 42.85 --target 48.35

If yfinance can't reach the network (e.g. sandboxed environments), pass
--demo to plot synthetic sample data instead, purely to preview the layout.
"""
import argparse
import numpy as np
import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib.pyplot as plt

RSI_OVERSOLD = 35
VOLUME_SURGE_MULT = 1.5


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


def make_demo_data(periods=180, seed=7):
    """Synthetic OHLCV purely to preview chart layout when live data is unreachable."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=periods)
    periods = len(dates)
    rets = rng.normal(0.0006, 0.013, periods)
    # bias the last ~15 sessions upward to create a visible bullish setup
    rets[-15:] += 0.004
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


def generate_chart(ticker, df, entry=None, stop=None, target=None, out_dir="charts", period_label=""):
    """Convenience wrapper used by report_generator.py: builds the chart for
    one ticker and returns the file path it was saved to."""
    import os
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{ticker.replace('.', '_')}.png")
    plot(ticker, df, entry=entry, stop=stop, target=target, out=out_path)
    return out_path


def plot(ticker, df, entry=None, stop=None, target=None, out="candlestick_chart.png"):
    ema20 = df["Close"].ewm(span=20, adjust=False).mean()
    ema50 = df["Close"].ewm(span=50, adjust=False).mean()
    rsi14 = rsi(df["Close"])
    macd_line, signal_line = macd(df["Close"])
    macd_hist = macd_line - signal_line
    hist_colors = ["#35D48C" if v >= 0 else "#FF5C6A" for v in macd_hist]
    vol_avg20 = df["Volume"].rolling(20).mean()
    surge_line = vol_avg20 * VOLUME_SURGE_MULT

    addplots = [
        mpf.make_addplot(ema20, color="#35D48C", width=1.1, label="EMA20"),
        mpf.make_addplot(ema50, color="#E8B45C", width=1.1, label="EMA50"),
        mpf.make_addplot(surge_line, panel=1, color="#7C8899", linestyle="--", width=0.8),
        mpf.make_addplot(rsi14, panel=2, color="#35D48C", width=1.1, ylabel="RSI"),
        mpf.make_addplot([RSI_OVERSOLD] * len(df), panel=2, color="#FF5C6A", linestyle="--", width=0.8),
        mpf.make_addplot(macd_hist, type="bar", panel=3, color=hist_colors, alpha=0.5, width=0.7, ylabel="MACD"),
        mpf.make_addplot(macd_line, panel=3, color="#35D48C", width=1.1),
        mpf.make_addplot(signal_line, panel=3, color="#FF5C6A", width=1.1),
    ]

    hlines = dict(hlines=[], colors=[], linestyle="-.", linewidths=1.1)
    if entry:
        hlines["hlines"].append(entry); hlines["colors"].append("#E9EDF2")
    if stop:
        hlines["hlines"].append(stop); hlines["colors"].append("#FF5C6A")
    if target:
        hlines["hlines"].append(target); hlines["colors"].append("#35D48C")

    mc = mpf.make_marketcolors(up="#35D48C", down="#FF5C6A", edge="inherit",
                                wick="inherit", volume={"up": "#2a6b52", "down": "#7a3038"})
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=mc,
                                facecolor="#0A0E14", edgecolor="#212A38",
                                gridcolor="#1A2230", gridstyle="--",
                                figcolor="#0A0E14", rc={"font.size": 9})

    fig, axes = mpf.plot(
        df, type="candle", style=style, addplot=addplots,
        volume=True, panel_ratios=(3, 1, 1, 1),
        hlines=hlines if hlines["hlines"] else None,
        title=f"\n{ticker} — Price / Volume / RSI(14) / MACD",
        figsize=(11, 10), returnfig=True,
    )
    axes[0].legend(loc="upper left", fontsize=8, facecolor="#121824", framealpha=0.3)
    fig.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Saved chart to {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?", default="D05.SI")
    p.add_argument("--period", default="9mo")
    p.add_argument("--entry", type=float, default=None)
    p.add_argument("--stop", type=float, default=None)
    p.add_argument("--target", type=float, default=None)
    p.add_argument("--demo", action="store_true", help="use synthetic data instead of live fetch")
    p.add_argument("--out", default="candlestick_chart.png")
    args = p.parse_args()

    data = load_data(args.ticker, args.period, demo=args.demo)
    plot(args.ticker, data, entry=args.entry, stop=args.stop, target=args.target, out=args.out)

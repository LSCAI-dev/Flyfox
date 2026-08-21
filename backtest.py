"""
Backtests the screener's TECHNICAL rules against historical price data:
the EMA20/50 uptrend gate, the MACD-bullish gate, and the breakout /
pullback / trend-continuation entry-stop-target logic -- exactly as
implemented in sgx_screener.py, using the same constants (imported directly
from there, so this never silently drifts out of sync with the live system).

IMPORTANT LIMITATION -- fundamentals are NOT backtested here. Yahoo Finance
only exposes a stock's CURRENT fundamentals (P/E, debt/equity, dividend
history), not point-in-time historical snapshots, for free. Testing today's
P/E against price action from two years ago would be a subtle lookahead
bias, so this backtest deliberately tests only the technical side: "would
this system's uptrend/MACD/entry/stop/target rules, as currently
configured, have produced profitable trades over the past few years?" It
does not tell you whether the fundamental filter adds or removes value.

No lookahead bias in the technical indicators themselves: EMA, RSI, MACD,
rolling swing high/low, and rolling VWAP are all backward-looking window
functions (each day's value only depends on that day and earlier), so
computing them once over the full history and reading off each day's value
is equivalent to computing them fresh with only data available "as of" that
day. The walk-forward loop still only ever *acts* on a signal using that
day's value and enters on the FOLLOWING day, so no future information leaks
into any trade decision.

Usage:
    python backtest.py                      # backtests the full SGX_UNIVERSE
    python backtest.py --tickers D05.SI,U11.SI --years 3
    python backtest.py --demo               # synthetic data, sandbox-safe preview

Output:
    backtest_trades.csv    -- one row per simulated trade
    backtest_report.html   -- summary dashboard (equity curve, win rate, per-stock table)
"""
import argparse
import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

import sgx_screener as s  # reuse constants + indicator functions, never redefine them

MAX_HOLD_DAYS = 40  # give up and exit at market if neither stop nor target hit by then


def compute_indicator_series(hist: pd.DataFrame) -> dict:
    """All indicators computed once, vectorized, over the whole history.
    Safe to do this in one pass because every one of these is a
    backward-looking window function (see module docstring)."""
    close = hist["Close"]
    ema_fast = close.ewm(span=s.EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=s.EMA_SLOW, adjust=False).mean()
    rsi14 = s.rsi(close, 14)
    macd_line, signal_line = s.macd(close)
    swing_low = hist["Low"].rolling(s.SWING_LOW_LOOKBACK).min()
    swing_high = hist["High"].rolling(s.RESISTANCE_LOOKBACK).max()
    avg_vol20 = hist["Volume"].shift(1).rolling(20).mean()
    return dict(close=close, ema_fast=ema_fast, ema_slow=ema_slow, rsi14=rsi14,
                macd_line=macd_line, signal_line=signal_line,
                swing_low=swing_low, swing_high=swing_high, avg_vol20=avg_vol20,
                high=hist["High"], low=hist["Low"], volume=hist["Volume"])


def check_signal(ind: dict, t: int) -> dict | None:
    """Checks whether every mandatory gate passes at index t, using only
    ind[...][t] and earlier -- mirrors sgx_screener.apply_ta_filters()
    exactly, just reading from precomputed series instead of re-slicing."""
    if t < s.RESISTANCE_LOOKBACK + s.TREND_SLOPE_LOOKBACK + 1:
        return None  # not enough history yet for a fair evaluation

    ema_fast, ema_slow = ind["ema_fast"], ind["ema_slow"]
    fast_above_slow = ema_fast.iloc[t] > ema_slow.iloc[t]
    fast_slope = ema_fast.iloc[t] - ema_fast.iloc[t - s.TREND_SLOPE_LOOKBACK]
    slow_slope = ema_slow.iloc[t] - ema_slow.iloc[t - s.TREND_SLOPE_LOOKBACK]
    in_uptrend = fast_above_slow and fast_slope > 0 and slow_slope > 0
    if not in_uptrend:
        return None

    macd_bullish = ind["macd_line"].iloc[t] >= ind["signal_line"].iloc[t]
    if not macd_bullish:
        return None

    # Bonus TA signals (mirrors apply_ta_filters' ta_score, min_ta_score=1
    # default -- the uptrend flag itself already satisfies that threshold,
    # matching the live system's current, deliberately loose default)
    ta_score = 1  # uptrend already confirmed above

    current_close = ind["close"].iloc[t]
    swing_low = ind["swing_low"].iloc[t]
    swing_high = ind["swing_high"].iloc[t]
    ema20_now = ema_fast.iloc[t]

    if np.isnan(swing_low) or np.isnan(swing_high):
        return None

    support_candidates = [lvl for lvl in (swing_low, ema20_now) if lvl <= current_close]
    support_level = max(support_candidates) if support_candidates else swing_low

    near_resistance = current_close >= swing_high * (1 - s.BREAKOUT_ZONE_PCT)
    near_support = current_close <= support_level * (1 + s.SUPPORT_ZONE_PCT)

    if near_resistance:
        breakout_trigger = swing_high * (1 + s.BREAKOUT_TRIGGER_BUFFER)
        entry = max(current_close, breakout_trigger)
        reason = "Breakout"
    elif near_support:
        entry = current_close
        reason = "Pullback"
    else:
        entry = current_close
        reason = "Trend-continuation"

    risk_floor = entry * 0.97
    if swing_low >= risk_floor:
        stop = swing_low
    else:
        stop = risk_floor
    risk = entry - stop
    if risk <= 0:
        return None

    min_target = entry + s.MIN_RR * risk
    target = swing_high if swing_high > min_target else min_target
    rr = (target - entry) / risk
    if rr < s.MIN_RR or ta_score < 1:
        return None

    return dict(entry=entry, stop=stop, target=target, rr=rr, reason=reason)


def simulate_trade(ind: dict, entry_idx: int, signal: dict, dates) -> dict:
    """Walks forward from the day AFTER the signal (the earliest a real
    trade could actually be executed) until stop, target, or a max holding
    period is hit. If both stop and target would trigger on the same bar
    (a gap), the stop is assumed hit first -- the standard conservative
    convention, since we don't know the intraday path from daily bars."""
    entry, stop, target = signal["entry"], signal["stop"], signal["target"]
    risk = entry - stop
    n = len(ind["close"])
    end_idx = min(entry_idx + MAX_HOLD_DAYS, n - 1)

    for t in range(entry_idx + 1, end_idx + 1):
        day_low = ind["low"].iloc[t]
        day_high = ind["high"].iloc[t]
        if day_low <= stop:
            exit_price = stop
            return dict(exit_idx=t, exit_date=dates[t], exit_reason="Stop",
                        exit_price=exit_price, r_achieved=(exit_price - entry) / risk)
        if day_high >= target:
            exit_price = target
            return dict(exit_idx=t, exit_date=dates[t], exit_reason="Target",
                        exit_price=exit_price, r_achieved=(exit_price - entry) / risk)

    exit_price = ind["close"].iloc[end_idx]
    return dict(exit_idx=end_idx, exit_date=dates[end_idx], exit_reason="Timeout",
                exit_price=exit_price, r_achieved=(exit_price - entry) / risk)


def backtest_ticker(ticker: str, hist: pd.DataFrame) -> list:
    """One-trade-at-a-time simulation for a single ticker: while a trade is
    open, no new signal is taken for that same ticker (mirrors how you'd
    actually trade one position per name, not stacking entries)."""
    ind = compute_indicator_series(hist)
    dates = hist.index
    trades = []
    t = 0
    n = len(hist)
    while t < n:
        signal = check_signal(ind, t)
        if signal is None:
            t += 1
            continue
        entry_idx = t + 1  # earliest real execution is the next session
        if entry_idx >= n:
            break
        outcome = simulate_trade(ind, entry_idx, signal, dates)
        trades.append(dict(
            ticker=ticker, signal_date=dates[t], entry_date=dates[entry_idx],
            entry=signal["entry"], stop=signal["stop"], target=signal["target"],
            planned_rr=signal["rr"], entry_reason=signal["reason"],
            **outcome,
        ))
        t = outcome["exit_idx"] + 1  # resume scanning only after this trade closes
    return trades


def make_demo_history(seed=1, n=750):
    """Synthetic multi-year OHLCV series with real up/down regimes, purely
    to exercise and validate the simulation engine when live data is
    unreachable (e.g. in a sandboxed environment)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    n = len(dates)
    regime_len = 60
    rets = np.zeros(n)
    i = 0
    while i < n:
        drift = rng.choice([0.0025, -0.0015, 0.0002])
        span = min(regime_len, n - i)
        rets[i:i + span] = rng.normal(drift, 0.012, span)
        i += span
    close = 20 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.002, 0.014, n))
    low = close * (1 - rng.uniform(0.002, 0.014, n))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    vol = rng.integers(500_000, 3_000_000, n).astype(float)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=dates)


def run_backtest(tickers=None, years=3, demo=False) -> pd.DataFrame:
    tickers = tickers or s.SGX_UNIVERSE
    all_trades = []
    for tk in tickers:
        try:
            if demo:
                hist = make_demo_history(seed=abs(hash(tk)) % (2**32))
            else:
                hist = yf.Ticker(tk).history(period=f"{years}y")
            if hist.empty or len(hist) < s.RESISTANCE_LOOKBACK + 100:
                print(f"  skip {tk}: not enough history")
                continue
            trades = backtest_ticker(tk, hist)
            print(f"  {tk}: {len(trades)} trade(s)")
            all_trades.extend(trades)
        except Exception as e:
            print(f"  skip {tk}: {e}")
    if not all_trades:
        return pd.DataFrame()
    df = pd.DataFrame(all_trades).sort_values("entry_date").reset_index(drop=True)
    return df


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default=None, help="comma-separated tickers (default: full SGX_UNIVERSE)")
    p.add_argument("--years", type=int, default=3)
    p.add_argument("--demo", action="store_true")
    p.add_argument("--csv", default="backtest_trades.csv")
    p.add_argument("--out", default="backtest_report.html")
    args = p.parse_args()

    tickers = args.tickers.split(",") if args.tickers else None
    print("Running backtest...")
    trades_df = run_backtest(tickers=tickers, years=args.years, demo=args.demo)
    trades_df.to_csv(args.csv, index=False)
    print(f"\n{len(trades_df)} total trades. Saved to {args.csv}")
    if len(trades_df):
        win_rate = (trades_df["r_achieved"] > 0).mean()
        print(f"Win rate: {win_rate:.1%} | Avg R: {trades_df['r_achieved'].mean():.2f} | Total R: {trades_df['r_achieved'].sum():.1f}")

    from backtest_report import build_backtest_report
    build_backtest_report(trades_df, out_path=args.out)
    print(f"Report written to {args.out}")

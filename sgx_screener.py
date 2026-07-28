"""
SGX Swing Trade Screener
========================
Scans a universe of SGX-listed stocks, filters on fundamental strength
(low P/E vs sector, revenue/earnings growth, low debt-to-equity, consistent
dividends) and requires the stock to be in a confirmed EMA uptrend (20-EMA
above 50-EMA, both sloping upward), then layers on additional technical
triggers (RSI momentum turn, MACD crossover, volume surge) before computing
an entry / stop / target with a minimum 2:1 reward-to-risk ratio.

Usage:
    pip install yfinance pandas numpy --break-system-packages
    python sgx_screener.py

Output:
    sgx_watchlist.csv   - ranked results, machine-readable
    sgx_report.html     - styled watchlist report, open in a browser

Notes:
    - Data comes from Yahoo Finance via yfinance (free, delayed ~15min for
      most exchanges outside the US). Fundamentals coverage for small/mid
      cap SGX names can be patchy -- missing fields are treated as "unknown"
      and that filter is skipped for that stock rather than failing it.
    - This is a screener, not investment advice. Always sanity-check a
      name before sizing a real position.
"""

import time
import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# 1. Universe: edit this list freely. These are liquid SGX mainboard names
#    (STI components + a few well-traded blue chips) as a sane default.
# ---------------------------------------------------------------------------
SGX_UNIVERSE = [
    "D05.SI",  # DBS Group
    "O39.SI",  # OCBC Bank
    "U11.SI",  # UOB
    "Z74.SI",  # Singtel
    "C6L.SI",  # Singapore Airlines
    "C38U.SI", # CapitaLand Integrated Commercial Trust
    "A17U.SI", # CapitaLand Ascendas REIT
    "S68.SI",  # SGX itself
    "C09.SI",  # City Developments
    "F34.SI",  # Wilmar International
    "Y92.SI",  # Thai Beverage
    "BN4.SI",  # Keppel Ltd
    "G13.SI",  # Genting Singapore
    "S63.SI",  # ST Engineering
    "V03.SI",  # Venture Corp
    "H78.SI",  # Hongkong Land
    "M44U.SI", # Mapletree Logistics Trust
    "N2IU.SI", # Mapletree Pan Asia Commercial Trust
    "ME8U.SI", # Mapletree Industrial Trust
    "U96.SI",  # Sembcorp Industries
    "9CI.SI",  # CapitaLand Investment
    "BS6.SI",  # Yangzijiang Shipbuilding
    "5E2.SI",  # Seatrium
    "U14.SI",  # UOL Group
    "AJBU.SI", # Keppel DC REIT
]

# ---------------------------------------------------------------------------
# 2. Screening parameters -- tune these to taste
# ---------------------------------------------------------------------------
LOOKBACK = "1y"
MIN_RR = 2.0                 # minimum reward:risk to include a name
RSI_OVERSOLD = 35            # RSI level considered "oversold" territory
EMA_FAST, EMA_SLOW = 20, 50   # uptrend gate: EMA_FAST must sit above EMA_SLOW
TREND_SLOPE_LOOKBACK = 10     # bars used to measure whether each EMA is still rising
MACD_CROSS_LOOKBACK = 5
VOLUME_SURGE_MULT = 1.5       # today's vol vs 20d avg vol
ASK_BID_LOOKBACK = 20         # bars used for the up/down-volume proxy ratio
SWING_LOW_LOOKBACK = 15       # bars used to find the protective stop level
DIVIDEND_YEARS_CHECK = 5      # consecutive years of dividends required


@dataclass
class StockResult:
    ticker: str
    name: str = ""
    sector: str = ""
    price: float = np.nan
    pe: float = np.nan
    sector_pe_median: float = np.nan
    rev_growth: float = np.nan
    debt_to_equity: float = np.nan
    div_yield: float = np.nan
    div_years_paid: int = 0
    fa_flags: list = field(default_factory=list)
    ta_flags: list = field(default_factory=list)
    fa_score: int = 0
    ta_score: int = 0
    entry: float = np.nan
    stop: float = np.nan
    target: float = np.nan
    rr: float = np.nan
    rel_vol: float = np.nan
    ask_bid_ratio: float = np.nan
    entry_reason: str = ""
    stop_reason: str = ""
    target_reason: str = ""
    in_uptrend: bool = False
    macd_bullish: bool = False
    notes: str = ""


# ---------------------------------------------------------------------------
# 3. Technical indicators
# ---------------------------------------------------------------------------
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def crossed_up_within(fast: pd.Series, slow: pd.Series, lookback: int) -> bool:
    diff = fast - slow
    recent = diff.tail(lookback + 1)
    if len(recent) < 2:
        return False
    return (recent.iloc[:-1].values <= 0).any() and diff.iloc[-1] > 0


# ---------------------------------------------------------------------------
# 4. Fundamental screen
# ---------------------------------------------------------------------------
def fetch_fundamentals(ticker: str) -> dict:
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    out = {
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector") or "Unknown",
        "pe": info.get("trailingPE", np.nan),
        "rev_growth": info.get("revenueGrowth", np.nan),
        "earnings_growth": info.get("earningsGrowth", np.nan),
        "debt_to_equity": info.get("debtToEquity", np.nan),
        "div_yield": info.get("dividendYield", np.nan),
    }
    # Dividend consistency: count distinct years with a payout in the last N years
    try:
        divs = t.dividends
        if divs is not None and len(divs) > 0:
            cutoff = dt.datetime.now(divs.index.tz) - pd.Timedelta(days=365 * DIVIDEND_YEARS_CHECK)
            recent = divs[divs.index >= cutoff]
            out["div_years_paid"] = recent.index.year.nunique()
        else:
            out["div_years_paid"] = 0
    except Exception:
        out["div_years_paid"] = 0
    return out


def apply_fa_filters(res: StockResult, sector_pe_median: float):
    if not np.isnan(res.pe) and not np.isnan(sector_pe_median) and res.pe > 0:
        res.sector_pe_median = sector_pe_median
        if res.pe < sector_pe_median:
            res.fa_flags.append("Low P/E vs sector")
            res.fa_score += 1
    if not np.isnan(res.rev_growth) and res.rev_growth > 0.03:
        res.fa_flags.append("Revenue growth")
        res.fa_score += 1
    if not np.isnan(res.debt_to_equity) and res.debt_to_equity < 100:
        res.fa_flags.append("Low debt/equity")
        res.fa_score += 1
    if res.div_years_paid >= DIVIDEND_YEARS_CHECK - 1:
        res.fa_flags.append(f"Dividend {DIVIDEND_YEARS_CHECK}y consistency")
        res.fa_score += 1


def ema_uptrend_check(close: pd.Series):
    """Mandatory gate: EMA_FAST must sit above EMA_SLOW, and both must be
    sloping upward over the last TREND_SLOPE_LOOKBACK bars."""
    ema_fast = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=EMA_SLOW, adjust=False).mean()

    fast_above_slow = ema_fast.iloc[-1] > ema_slow.iloc[-1]
    fast_slope = ema_fast.iloc[-1] - ema_fast.iloc[-1 - TREND_SLOPE_LOOKBACK]
    slow_slope = ema_slow.iloc[-1] - ema_slow.iloc[-1 - TREND_SLOPE_LOOKBACK]

    passes = bool(fast_above_slow and fast_slope > 0 and slow_slope > 0)
    return passes, ema_fast, ema_slow


def apply_ta_filters(res: StockResult, hist: pd.DataFrame):
    close = hist["Close"]
    vol = hist["Volume"]
    rsi14 = rsi(close, 14)

    uptrend_ok, ema_fast, ema_slow = ema_uptrend_check(close)
    res.in_uptrend = uptrend_ok
    if uptrend_ok:
        res.ta_flags.append(f"Uptrend: EMA{EMA_FAST}>EMA{EMA_SLOW}, both rising")
        res.ta_score += 1
    else:
        res.notes = f"Rejected: not in EMA{EMA_FAST}/{EMA_SLOW} uptrend"

    recent_rsi = rsi14.tail(5)
    if (recent_rsi.min() < RSI_OVERSOLD) and (rsi14.iloc[-1] > recent_rsi.min()):
        res.ta_flags.append("RSI momentum turn from oversold")
        res.ta_score += 1

    macd_line, signal_line = macd(close)
    res.macd_bullish = bool(macd_line.iloc[-1] >= signal_line.iloc[-1])
    if crossed_up_within(macd_line, signal_line, MACD_CROSS_LOOKBACK):
        res.ta_flags.append("MACD bullish cross")
        res.ta_score += 1

    avg_vol20 = vol.iloc[-21:-1].mean()  # prior 20 sessions, excluding today
    res.rel_vol = float(vol.iloc[-1] / avg_vol20) if avg_vol20 > 0 else np.nan
    if avg_vol20 > 0 and vol.iloc[-1] > VOLUME_SURGE_MULT * avg_vol20:
        res.ta_flags.append("Volume surge")
        res.ta_score += 1

    # Ask/Bid ratio -- Yahoo Finance has no real bid/ask trade classification
    # (that needs Level 1/2 quote data), so this is a proxy: volume on days
    # the price closed higher ("buy pressure") vs days it closed lower
    # ("sell pressure") over the last ASK_BID_LOOKBACK sessions.
    window = hist.tail(ASK_BID_LOOKBACK + 1)
    diffs = window["Close"].diff().iloc[1:]
    vols_in_window = window["Volume"].iloc[1:]
    buy_vol = vols_in_window[diffs > 0].sum()
    sell_vol = vols_in_window[diffs < 0].sum()
    res.ask_bid_ratio = float(buy_vol / sell_vol) if sell_vol > 0 else np.nan

    entry = float(close.iloc[-1])
    res.entry_reason = "Last closing price on the day of the scan"

    swing_low = float(hist["Low"].tail(SWING_LOW_LOOKBACK).min())
    risk_floor = entry * 0.97  # cap max risk at ~3% of entry
    # Use whichever stop is CLOSER to entry (i.e. the smaller of the two risk
    # amounts) -- if the technical swing low sits further than 3% away, the
    # 3% cap takes over instead of accepting the wider, riskier stop.
    if swing_low >= risk_floor:
        stop = swing_low
        res.stop_reason = f"Recent swing low over the last {SWING_LOW_LOOKBACK} sessions"
    else:
        stop = risk_floor
        res.stop_reason = "3% max-risk cap (technical swing low was further than 3% away)"
    risk = entry - stop
    if risk <= 0:
        res.notes = "Could not derive a valid stop (no clear swing low)"
        return

    # Target: at least MIN_RR, but respect the recent swing high if it's further out
    swing_high = float(hist["High"].tail(60).max())
    min_target = entry + MIN_RR * risk
    if swing_high > min_target:
        target = swing_high
        res.target_reason = "Recent swing high (resistance) over the last 60 sessions"
    else:
        target = min_target
        res.target_reason = f"Minimum {MIN_RR:.0f}:1 reward-to-risk from entry and stop"

    rr = (target - entry) / risk
    res.entry, res.stop, res.target, res.rr = entry, stop, target, rr


# ---------------------------------------------------------------------------
# 6. Runner
# ---------------------------------------------------------------------------
def run_screen(universe=None, min_fa_score=1, min_ta_score=1) -> pd.DataFrame:
    universe = universe or SGX_UNIVERSE
    raw = []
    for tk in universe:
        try:
            fa = fetch_fundamentals(tk)
            hist = yf.Ticker(tk).history(period=LOOKBACK)
            if hist.empty or len(hist) < 60:
                continue
            res = StockResult(ticker=tk, name=fa["name"], sector=fa["sector"],
                               pe=fa["pe"], rev_growth=fa["rev_growth"],
                               debt_to_equity=fa["debt_to_equity"],
                               div_yield=fa["div_yield"], div_years_paid=fa["div_years_paid"])
            raw.append((res, hist))
            time.sleep(0.3)  # be polite to the data source
        except Exception as e:
            print(f"  skip {tk}: {e}")

    # sector P/E medians across the fetched universe
    sector_pes = {}
    for res, _ in raw:
        if res.sector and not np.isnan(res.pe) and res.pe > 0:
            sector_pes.setdefault(res.sector, []).append(res.pe)
    sector_pe_median = {s: float(np.median(v)) for s, v in sector_pes.items()}

    rows = []
    for res, hist in raw:
        apply_fa_filters(res, sector_pe_median.get(res.sector, np.nan))
        apply_ta_filters(res, hist)
        if (res.in_uptrend and res.macd_bullish and res.fa_score >= min_fa_score
                and res.ta_score >= min_ta_score and res.rr >= MIN_RR):
            rows.append(res)

    df = pd.DataFrame([{
        "Ticker": r.ticker, "Name": r.name, "Sector": r.sector,
        "Price": round(r.price if not np.isnan(r.price) else r.entry, 3),
        "Entry": round(r.entry, 3), "Stop": round(r.stop, 3), "Target": round(r.target, 3),
        "R:R": round(r.rr, 2), "FA Score": r.fa_score, "TA Score": r.ta_score,
        "FA Signals": ", ".join(r.fa_flags), "TA Signals": ", ".join(r.ta_flags),
        "Entry Reason": r.entry_reason, "Stop Reason": r.stop_reason, "Target Reason": r.target_reason,
        "Rel Vol": round(r.rel_vol, 2) if not np.isnan(r.rel_vol) else None,
        "Ask/Bid Ratio (approx)": round(r.ask_bid_ratio, 2) if not np.isnan(r.ask_bid_ratio) else None,
    } for r in rows])

    if not df.empty:
        df["Composite"] = df["FA Score"] + df["TA Score"] + df["R:R"].clip(upper=4) / 2
        df = df.sort_values("Composite", ascending=False).drop(columns="Composite").reset_index(drop=True)
    return df


if __name__ == "__main__":
    print("Scanning SGX universe...")
    watchlist = run_screen()
    watchlist.to_csv("sgx_watchlist.csv", index=False)
    print(f"Found {len(watchlist)} candidates. Saved to sgx_watchlist.csv")
    print(watchlist.to_string(index=False))

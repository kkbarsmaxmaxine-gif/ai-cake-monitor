"""
ai_cake_monitor/fetcher.py – yfinance data fetcher + snapshot builder.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


# ── yfinance extraction helpers ───────────────────────────────────────────────

def _normalise_df(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns, drop tz from index."""
    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    if hasattr(df.index, "tz") and df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def _extract_single(raw: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """
    Pull one ticker out of a yfinance MultiIndex result.
    yfinance uses (metric, ticker) MultiIndex when multiple tickers are requested.
    """
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        levels = raw.columns.levels
        # Level 0 = metric (Close, Open...), Level 1 = ticker symbol
        if len(levels) > 1 and ticker in levels[1]:
            df = raw.xs(ticker, axis=1, level=1)
        elif ticker in levels[0]:
            df = raw.xs(ticker, axis=1, level=0)
        else:
            # Try case-insensitive match
            upper = ticker.upper()
            matches_1 = [t for t in levels[1] if str(t).upper() == upper]
            matches_0 = [t for t in levels[0] if str(t).upper() == upper]
            if matches_1:
                df = raw.xs(matches_1[0], axis=1, level=1)
            elif matches_0:
                df = raw.xs(matches_0[0], axis=1, level=0)
            else:
                return None
    else:
        df = raw

    df = df.dropna(how="all")
    return _normalise_df(df) if not df.empty else None


# ── Data fetchers ─────────────────────────────────────────────────────────────

def fetch_daily_data(tickers: list[str], period: str = "10d") -> dict[str, pd.DataFrame]:
    """
    Fetch daily OHLCV for a list of tickers.
    Returns {ticker: DataFrame} for tickers with valid data.
    """
    if not tickers:
        return {}
    logger.info("Fetching daily (%s) for %d tickers", period, len(tickers))
    try:
        raw = yf.download(
            tickers,
            period=period,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.error("yfinance daily download failed: %s", exc)
        return {}

    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = _extract_single(raw, ticker)
        if df is not None and not df.empty:
            df.index = pd.to_datetime(df.index)
            result[ticker] = df
        else:
            logger.debug("No daily data: %s", ticker)
    logger.info("Daily data: %d/%d tickers returned", len(result), len(tickers))
    return result


def fetch_intraday_data(
    tickers: list[str],
    period: str = "1d",
    interval: str = "5m",
) -> dict[str, pd.DataFrame]:
    """
    Fetch intraday bars.  Returns empty dict gracefully on failure or market close.
    Non-US tickers (KS, TW) will naturally have no US-session data — that's fine.
    """
    if not tickers:
        return {}
    logger.info("Fetching intraday (%s/%s) for %d tickers", interval, period, len(tickers))
    try:
        raw = yf.download(
            tickers,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as exc:
        logger.warning("Intraday download failed: %s", exc)
        return {}

    result: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        df = _extract_single(raw, ticker)
        if df is not None and not df.empty:
            df.index = pd.to_datetime(df.index)
            result[ticker] = df
        else:
            logger.debug("No intraday data: %s", ticker)
    logger.info("Intraday data: %d/%d tickers returned", len(result), len(tickers))
    return result


# ── Snapshot builder ──────────────────────────────────────────────────────────

def _vol_ratio(df: pd.DataFrame) -> float:
    """today_volume / avg_volume_of_prior_5_sessions"""
    vols = df["volume"].dropna()
    if len(vols) < 2:
        return float("nan")
    today_vol = float(vols.iloc[-1])
    avg5 = float(vols.iloc[-6:-1].mean()) if len(vols) >= 6 else float(vols.iloc[:-1].mean())
    return today_vol / avg5 if avg5 > 0 else float("nan")


def _rebound_metrics(
    today_close: float,
    daily_high: float,
    daily_low: float,
    intra_df: Optional[pd.DataFrame],
) -> tuple[float, float]:
    """
    Returns (rebound_ratio, rebound_pct).
    rebound_ratio = (close - day_low) / (day_high - day_low), [0, 1]
    rebound_pct   = (close - day_low) / day_low * 100
    Prefers intraday bars when available for more precise low tick.
    """
    # Use intraday bars for precise high/low if available
    if intra_df is not None and not intra_df.empty:
        i_low  = float(intra_df["low"].min())  if "low"  in intra_df.columns else daily_low
        i_high = float(intra_df["high"].max()) if "high" in intra_df.columns else daily_high
        last_close = float(intra_df["close"].iloc[-1]) if "close" in intra_df.columns else today_close
    else:
        i_low  = daily_low
        i_high = daily_high
        last_close = today_close

    rng = i_high - i_low
    rebound_ratio = (last_close - i_low) / rng if rng > 1e-8 else 0.5
    rebound_pct   = (last_close - i_low) / i_low * 100 if i_low > 0 else float("nan")
    return round(rebound_ratio, 4), round(rebound_pct, 2)


def build_snapshot(
    daily_data:    dict[str, pd.DataFrame],
    intraday_data: dict[str, pd.DataFrame],
    ticker_to_layer: dict[str, str],
    ticker_labels:   dict[str, str],
) -> pd.DataFrame:
    """
    Merge daily + intraday into one row-per-ticker DataFrame.

    Columns:
        ticker, display_name, layer,
        close, prev_close, open, day_high, day_low, volume,
        change_pct, rebound_ratio, rebound_pct, vol_ratio
    """
    rows = []
    for ticker, df in daily_data.items():
        if len(df) < 2:
            logger.debug("Too few daily rows for %s (got %d)", ticker, len(df))
            continue

        today = df.iloc[-1]
        prev  = df.iloc[-2]

        close      = float(today.get("close", today.get("adj close", float("nan"))))
        prev_close = float(prev.get("close",  prev.get("adj close",  float("nan"))))
        open_      = float(today.get("open",   float("nan")))
        high       = float(today.get("high",   float("nan")))
        low        = float(today.get("low",    float("nan")))
        volume     = float(today.get("volume", float("nan")))

        if np.isnan(close) or np.isnan(prev_close) or prev_close == 0:
            continue

        change_pct = (close - prev_close) / prev_close * 100
        vol_r      = _vol_ratio(df)
        reb_ratio, reb_pct = _rebound_metrics(close, high, low, intraday_data.get(ticker))

        rows.append({
            "ticker":        ticker,
            "display_name":  ticker_labels.get(ticker, ticker),
            "layer":         ticker_to_layer.get(ticker, "unknown"),
            "close":         round(close, 2),
            "prev_close":    round(prev_close, 2),
            "open":          round(open_, 2) if not np.isnan(open_) else float("nan"),
            "day_high":      round(high, 2)  if not np.isnan(high)  else float("nan"),
            "day_low":       round(low, 2)   if not np.isnan(low)   else float("nan"),
            "volume":        int(volume)     if not np.isnan(volume) else 0,
            "change_pct":    round(change_pct, 2),
            "rebound_ratio": reb_ratio,
            "rebound_pct":   reb_pct,
            "vol_ratio":     round(vol_r, 2) if not np.isnan(vol_r) else float("nan"),
        })

    return pd.DataFrame(rows).reset_index(drop=True) if rows else pd.DataFrame()

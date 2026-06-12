"""
ai_cake_monitor/validator.py — Data quality checker.

Runs after every fetch to catch: date lag, missing tickers,
extreme moves, zero volume, and stale freeze.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────────────────────
_WARN_CHANGE  = 15.0   # |change%| above this → warning (unusual but real)
_ERROR_CHANGE = 40.0   # |change%| above this → error   (likely bad data)
_STALE_RATIO  = 0.40   # if this fraction of tickers are 0.00% → suspect stale


def validate(
    daily_data:       dict[str, pd.DataFrame],
    snapshot:         pd.DataFrame,
    expected_tickers: list[str],
    date_str:         str,
) -> dict[str, Any]:
    """
    Run all quality checks and return a structured report.

    Return schema::
        {
          "status":     "ok" | "warning" | "error",
          "checked_at": "<iso8601>Z",
          "summary":    "All checks passed" | "2 warnings, 1 error",
          "issues": [
            {"level": "warning"|"error", "check": str, "ticker": str|None, "detail": str}
          ]
        }
    """
    issues: list[dict] = []
    warn_n = 0
    err_n  = 0

    def _issue(level: str, check: str, detail: str, ticker: str | None = None) -> None:
        nonlocal warn_n, err_n
        issues.append({"level": level, "check": check, "ticker": ticker, "detail": detail})
        if level == "error":
            err_n  += 1
        else:
            warn_n += 1
        log = logger.error if level == "error" else logger.warning
        t = f" [{ticker}]" if ticker else ""
        log("DQ %s%s: %s", check, t, detail)

    # ── 1. Date lag ───────────────────────────────────────────────────────────
    actual_date: str | None = None
    for df in daily_data.values():
        if df is not None and not df.empty:
            actual_date = pd.Timestamp(df.index[-1]).strftime("%Y%m%d")
            break

    if actual_date is None:
        _issue("error", "date_lag", "No valid data rows returned — cannot determine data date")
    elif actual_date == date_str:
        logger.info("DQ date_lag: OK — data date matches %s", date_str)
    else:
        try:
            lag = (datetime.strptime(date_str, "%Y%m%d")
                   - datetime.strptime(actual_date, "%Y%m%d")).days
            level = "error" if lag > 3 else "warning"
            _issue(level, "date_lag",
                   f"Data is {lag} trading-day(s) behind: expected {date_str}, got {actual_date}")
        except ValueError:
            _issue("warning", "date_lag",
                   f"Date mismatch: expected {date_str}, got {actual_date!r}")

    # ── 2. Missing tickers ────────────────────────────────────────────────────
    fetched = set(daily_data.keys())
    missing = [t for t in expected_tickers if t not in fetched]
    if missing:
        _issue("warning", "missing_tickers",
               f"{len(missing)} ticker(s) missing from fetch: {', '.join(missing)}")
    else:
        logger.info("DQ missing_tickers: OK — all %d tickers fetched", len(expected_tickers))

    # ── 3. Outlier daily moves ────────────────────────────────────────────────
    outlier_found = False
    if not snapshot.empty and "change_pct" in snapshot.columns:
        for _, row in snapshot.iterrows():
            chg    = row.get("change_pct")
            ticker = str(row.get("ticker", "?"))
            if chg is None or pd.isna(chg):
                continue
            abs_chg = abs(float(chg))
            if abs_chg >= _ERROR_CHANGE:
                _issue("error", "outlier",
                       f"{chg:+.1f}% — extreme move, likely bad data (threshold ±{_ERROR_CHANGE}%)",
                       ticker=ticker)
                outlier_found = True
            elif abs_chg >= _WARN_CHANGE:
                _issue("warning", "outlier",
                       f"{chg:+.1f}% — unusual single-day move (verify)",
                       ticker=ticker)
                outlier_found = True
    if not outlier_found:
        logger.info("DQ outlier: OK — no extreme moves detected")

    # ── 4. Zero volume ────────────────────────────────────────────────────────
    if not snapshot.empty and "volume" in snapshot.columns:
        zero_vol = snapshot[snapshot["volume"] == 0]["ticker"].tolist()
        if zero_vol:
            _issue("warning", "zero_volume",
                   f"Zero volume on: {', '.join(zero_vol)}")
        else:
            logger.info("DQ zero_volume: OK")

    # ── 5. Stale freeze (too many 0% changes) ─────────────────────────────────
    if not snapshot.empty and "change_pct" in snapshot.columns:
        total    = len(snapshot)
        zero_chg = int((snapshot["change_pct"].abs() < 0.001).sum())
        if total >= 5 and zero_chg / total >= _STALE_RATIO:
            _issue("warning", "stale_freeze",
                   f"{zero_chg}/{total} tickers show ~0% change — data may be stale or market closed")
        else:
            logger.info("DQ stale_freeze: OK — %d/%d tickers at 0%%", zero_chg, total)

    # ── 6. Zero / negative price ──────────────────────────────────────────────
    if not snapshot.empty and "close" in snapshot.columns:
        bad_price = snapshot[snapshot["close"] <= 0]["ticker"].tolist()
        if bad_price:
            _issue("error", "bad_price",
                   f"Price ≤ 0 detected: {', '.join(bad_price)}")
        else:
            logger.info("DQ bad_price: OK")

    # ── Summary ───────────────────────────────────────────────────────────────
    if err_n == 0 and warn_n == 0:
        status  = "ok"
        summary = "All checks passed"
    elif err_n > 0:
        status  = "error"
        summary = f"{warn_n} warning(s), {err_n} error(s)"
    else:
        status  = "warning"
        summary = f"{warn_n} warning(s), 0 errors"

    logger.info("DQ result: %s — %s", status.upper(), summary)

    return {
        "status":     status,
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "summary":    summary,
        "issues":     issues,
    }

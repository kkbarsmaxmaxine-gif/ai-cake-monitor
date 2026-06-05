#!/usr/bin/env python3
"""
main.py – AI 五層蛋糕 + 美股相對強弱監控

Usage
-----
  # Run with intraday rebound data (default)
  python main.py

  # Skip intraday fetch (faster, no rebound metrics)
  python main.py --skip-intraday

  # Override date label in report
  python main.py --date 20260605
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import LAYERS, BENCHMARK, LOG_LEVEL
from fetcher import fetch_daily_data, fetch_intraday_data, build_snapshot
from analyzer import build_full_analysis
from reporter import generate_report, print_terminal_summary, save_report
from notifier import send_notification


def _setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("main")


def _build_ticker_maps() -> tuple[list[str], dict[str, str], dict[str, str]]:
    """
    Flatten LAYERS config into:
      all_tickers     : deduplicated list (first-occurrence order)
      ticker_to_layer : ticker → primary layer_id (first occurrence wins)
      ticker_labels   : ticker → display name overrides
    """
    ticker_to_layer: dict[str, str] = {}
    ticker_labels:   dict[str, str] = {}
    seen:            set[str]       = set()
    all_tickers:     list[str]      = []

    for layer_id, cfg in LAYERS.items():
        for t in cfg["tickers"]:
            if t not in seen:
                seen.add(t)
                all_tickers.append(t)
            if t not in ticker_to_layer:
                ticker_to_layer[t] = layer_id
        for t, label in cfg.get("ticker_labels", {}).items():
            ticker_labels[t] = label

    return all_tickers, ticker_to_layer, ticker_labels


def run(date_str: str, skip_intraday: bool = False) -> dict:
    logger = logging.getLogger("main")

    all_tickers, ticker_to_layer, ticker_labels = _build_ticker_maps()
    all_with_bench = [BENCHMARK] + all_tickers

    # ── Step 1: Daily data ────────────────────────────────────────────────────
    logger.info("=== Step 1: Daily data ===")
    daily_data = fetch_daily_data(all_with_bench, period="10d")

    if not daily_data:
        logger.error("No daily data returned — check internet / market hours")
        return {}

    # ── Step 2: Intraday data (optional) ─────────────────────────────────────
    logger.info("=== Step 2: Intraday data ===")
    intraday_data: dict = {}
    if not skip_intraday:
        # Only fetch US-listed tickers for intraday (KS/TW tickers already closed)
        us_tickers = [t for t in all_tickers if "." not in t]
        intraday_data = fetch_intraday_data(us_tickers, period="1d", interval="5m")
    else:
        logger.info("Intraday fetch skipped (--skip-intraday)")

    # ── Step 3: Benchmark return ──────────────────────────────────────────────
    benchmark_chg: float | None = None
    bench_df = daily_data.get(BENCHMARK)
    if bench_df is not None and len(bench_df) >= 2:
        c0 = float(bench_df["close"].iloc[-2])
        c1 = float(bench_df["close"].iloc[-1])
        if c0 != 0:
            benchmark_chg = round((c1 - c0) / c0 * 100, 2)
    logger.info("Benchmark (%s) change: %s", BENCHMARK,
                f"{benchmark_chg:+.2f}%" if benchmark_chg is not None else "N/A")

    # ── Step 4: Build snapshot ────────────────────────────────────────────────
    logger.info("=== Step 3: Build snapshot ===")
    stock_daily = {t: df for t, df in daily_data.items() if t != BENCHMARK}
    snapshot = build_snapshot(stock_daily, intraday_data, ticker_to_layer, ticker_labels)

    if snapshot.empty:
        logger.error("Snapshot is empty — nothing to analyse")
        return {}

    logger.info("Snapshot: %d tickers", len(snapshot))

    # ── Step 5: Analysis ──────────────────────────────────────────────────────
    logger.info("=== Step 4: Analysis ===")
    analysis = build_full_analysis(snapshot)

    # ── Step 6: Report ────────────────────────────────────────────────────────
    logger.info("=== Step 5: Report ===")
    print_terminal_summary(analysis, benchmark_chg)

    report_md   = generate_report(analysis, benchmark_chg, date_str)
    report_path = save_report(report_md, date_str)
    logger.info("Report → %s", report_path)

    # ── Step 6: Telegram notification ────────────────────────────────────────
    logger.info("=== Step 6: Telegram ===")
    send_notification(analysis, benchmark_chg, date_str, report_path)

    return {
        "snapshot":      snapshot,
        "analysis":      analysis,
        "benchmark_chg": benchmark_chg,
        "report_path":   report_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI 五層蛋糕 監控",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--date", default=None,
        help="Override date label in report (YYYYMMDD)",
    )
    parser.add_argument(
        "--skip-intraday", action="store_true",
        help="Skip intraday 5m fetch (no rebound_ratio; much faster)",
    )
    parser.add_argument("--log-level", default=LOG_LEVEL)
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y%m%d")
    logger   = _setup_logging(args.log_level)
    logger.info("AI Cake Monitor | date=%s | intraday=%s",
                date_str, not args.skip_intraday)

    result = run(date_str=date_str, skip_intraday=args.skip_intraday)

    if result:
        n = len(result.get("snapshot", []))
        print(f"  監控個股: {n} 檔 | 報告: {result['report_path']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

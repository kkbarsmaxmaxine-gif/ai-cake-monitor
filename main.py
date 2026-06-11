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
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import LAYERS, BENCHMARK, NASDAQ, VIX, LOG_LEVEL
from fetcher import fetch_daily_data, fetch_intraday_data, build_snapshot
from analyzer import build_full_analysis
from reporter import generate_report, print_terminal_summary, save_report
from notifier import send_notification
from social_fetcher import build_buzz


def _setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("main")


def _save_web_data(
    analysis:      dict,
    benchmark_chg: float | None,
    date_str:      str,
    nasdaq_chg:    float | None = None,
    vix_level:     float | None = None,
    vix_chg:       float | None = None,
    buzz:          dict | None  = None,
) -> None:
    """Write docs/data.json for the bubble-chart web dashboard."""
    import math

    def _f(v):
        """Convert float to JSON-safe value (NaN/Inf → None)."""
        if v is None:
            return None
        try:
            f = float(v)
            return None if (math.isnan(f) or math.isinf(f)) else round(f, 2)
        except (TypeError, ValueError):
            return None

    layer_perf = analysis.get("layer_perf")
    resilience = analysis.get("resilience")
    if layer_perf is None or layer_perf.empty:
        return

    layers_out = []
    for _, row in layer_perf.iterrows():
        layer_id = row["layer_id"]
        top_stocks = []
        if resilience is not None and not resilience.empty:
            sub = resilience[resilience["layer"] == layer_id].head(3)
            for _, sr in sub.iterrows():
                top_stocks.append({
                    "ticker":       sr["ticker"],
                    "display_name": sr["display_name"],
                    "change_pct":   _f(sr["change_pct"]),
                })
        layer_buzz = (buzz or {}).get("by_layer", {}).get(layer_id, {})
        layers_out.append({
            "layer_id":      layer_id,
            "label":         row["layer_label"],
            "cake_layer":    int(row["cake_layer"]),
            "avg_change":    _f(row["avg_change"]),
            "avg_vol_ratio": _f(row["avg_vol_ratio"]),
            "best_ticker":   row["best_ticker"],
            "best_pct":      _f(row["best_pct"]),
            "worst_ticker":  row["worst_ticker"],
            "worst_pct":     _f(row["worst_pct"]),
            "top_stocks":    top_stocks,
            "buzz_total":    layer_buzz.get("total", 0),
            "buzz_top":      layer_buzz.get("top_ticker", ""),
        })

    payload = {
        "date":          date_str,
        "benchmark_chg": _f(benchmark_chg),
        "nasdaq_chg":    _f(nasdaq_chg),
        "vix_level":     _f(vix_level),
        "vix_chg":       _f(vix_chg),
        "layers":        layers_out,
        "social_buzz":   buzz or {},
    }

    docs_dir = Path(__file__).parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    out_path = docs_dir / "data.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.getLogger("main").info("Web data → %s", out_path)


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
    all_with_bench = [BENCHMARK, NASDAQ, VIX] + all_tickers

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

    # ── Step 3: Benchmark + VIX ──────────────────────────────────────────────
    benchmark_chg: float | None = None
    bench_df = daily_data.get(BENCHMARK)
    if bench_df is not None and len(bench_df) >= 2:
        c0 = float(bench_df["close"].iloc[-2])
        c1 = float(bench_df["close"].iloc[-1])
        if c0 != 0:
            benchmark_chg = round((c1 - c0) / c0 * 100, 2)
    logger.info("Benchmark (%s) change: %s", BENCHMARK,
                f"{benchmark_chg:+.2f}%" if benchmark_chg is not None else "N/A")

    nasdaq_chg: float | None = None
    ndq_df = daily_data.get(NASDAQ)
    if ndq_df is not None and len(ndq_df) >= 2:
        n0 = float(ndq_df["close"].iloc[-2])
        n1 = float(ndq_df["close"].iloc[-1])
        if n0 != 0:
            nasdaq_chg = round((n1 - n0) / n0 * 100, 2)
    logger.info("NASDAQ change: %s", f"{nasdaq_chg:+.2f}%" if nasdaq_chg is not None else "N/A")

    vix_level: float | None = None
    vix_chg:   float | None = None
    vix_df = daily_data.get(VIX)
    if vix_df is not None and len(vix_df) >= 2:
        vix_level = round(float(vix_df["close"].iloc[-1]), 2)
        v0 = float(vix_df["close"].iloc[-2])
        if v0 != 0:
            vix_chg = round((vix_level - v0) / v0 * 100, 2)
    logger.info("VIX level: %s", vix_level if vix_level is not None else "N/A")

    # ── Step 4: Build snapshot ────────────────────────────────────────────────
    logger.info("=== Step 3: Build snapshot ===")
    stock_daily = {t: df for t, df in daily_data.items() if t not in (BENCHMARK, NASDAQ, VIX)}
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
    print_terminal_summary(analysis, benchmark_chg, nasdaq_chg, vix_level, vix_chg)

    report_md   = generate_report(analysis, benchmark_chg, date_str, vix_level, vix_chg, nasdaq_chg)
    report_path = save_report(report_md, date_str)
    logger.info("Report → %s", report_path)

    # ── Step 6: Social buzz ───────────────────────────────────────────────────
    logger.info("=== Step 6: Social buzz ===")
    buzz = build_buzz(all_tickers, ticker_labels, ticker_to_layer)

    # ── Step 7: Generate web data.json ───────────────────────────────────────
    logger.info("=== Step 7: Web data.json ===")
    _save_web_data(analysis, benchmark_chg, date_str, nasdaq_chg, vix_level, vix_chg, buzz)

    # ── Step 8: Telegram notification ────────────────────────────────────────
    logger.info("=== Step 8: Telegram ===")
    send_notification(analysis, benchmark_chg, date_str, report_path, vix_level, vix_chg, nasdaq_chg, buzz)

    return {
        "snapshot":      snapshot,
        "analysis":      analysis,
        "benchmark_chg": benchmark_chg,
        "nasdaq_chg":    nasdaq_chg,
        "vix_level":     vix_level,
        "vix_chg":       vix_chg,
        "report_path":   report_path,
        "buzz":          buzz,
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

#!/usr/bin/env python3
"""
social_only.py – lightweight pre-market social buzz fetch.

Skips all market-data steps; only collects social mentions and writes
docs/social_buzz.json.  Triggered by the pre-market GitHub Actions cron.

Usage:
  python social_only.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import LAYERS, LOG_LEVEL
from main import _build_ticker_maps
from social_fetcher import build_buzz

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("social_only")


def main() -> int:
    logger.info("Social-only run started")
    all_tickers, ticker_to_layer, ticker_labels = _build_ticker_maps()

    buzz = build_buzz(all_tickers, ticker_labels, ticker_to_layer)

    out_path = Path(__file__).parent / "docs" / "social_buzz.json"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(buzz, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Social buzz → %s", out_path)

    if buzz.get("top5"):
        print("Top 5 buzz:")
        for item in buzz["top5"]:
            print(f"  {item['display_name']:15s}  {item['total']} 則  (score {item['score']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())

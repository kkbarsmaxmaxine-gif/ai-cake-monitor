"""
ai_cake_monitor/config.py – Jensen Huang's AI 5-layer cake monitor config.

Layer mapping (7 sub-layers):
  1  Energy / Power
  2a GPU / ASIC
  2b HBM / Memory
  2c CPU / SoC
  3  Networking / CPO (Infra)
  4  Model / Software
  5  Application / Robotics
"""
from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# AVGO → chip_core (ASIC primary narrative)
# MRVL → infra_cpo (networking/CPO primary narrative)
# Non-US tickers: KS suffix = Korea, TW suffix = Taiwan, OTC ADRs work via yfinance
LAYERS: dict[str, dict] = {
    "energy": {
        "label": "⚡ Energy / Power",
        "cake_layer": 1,
        "tickers": ["CEG", "VST"],
        "ticker_labels": {},
    },
    "chip_core": {
        "label": "🧠 GPU / ASIC",
        "cake_layer": 2,
        "tickers": ["NVDA", "TSM", "AVGO"],
        "ticker_labels": {},
    },
    "chip_memory": {
        "label": "💾 HBM / Memory",
        "cake_layer": 2,
        "tickers": ["MU", "000660.KS", "005930.KS"],
        "ticker_labels": {"000660.KS": "SKHynix", "005930.KS": "Samsung"},
    },
    "chip_cpu": {
        "label": "🔲 CPU / SoC",
        "cake_layer": 2,
        "tickers": ["ARM", "AMD", "INTC", "QCOM", "2454.TW"],
        "ticker_labels": {"2454.TW": "MediaTek"},
    },
    "infra_cpo": {
        "label": "🔌 Networking / CPO",
        "cake_layer": 3,
        "tickers": ["MRVL", "ANET", "LITE", "COHR"],
        "ticker_labels": {},
    },
    "model_software": {
        "label": "🤖 Model / Software",
        "cake_layer": 4,
        "tickers": ["NOW", "PLTR", "CRM"],
        "ticker_labels": {},
    },
    "application_robotics": {
        "label": "🦾 Application / Robotics",
        "cake_layer": 5,
        # FANUY=FANUC ADR, YASKY=Yaskawa ADR, ABBNY=ABB ADR (OTC),
        # ROK=Rockwell Automation (KUKA/industrial proxy), TSLA=humanoid robot narrative
        "tickers": ["FANUY", "YASKY", "ABBNY", "ROK", "TSLA"],
        "ticker_labels": {
            "FANUY": "FANUC",
            "YASKY": "Yaskawa",
            "ABBNY": "ABB",
            "ROK":   "Rockwell",
        },
    },
}

BENCHMARK = "^GSPC"

# Intraday interval for rebound calculation
INTRADAY_INTERVAL = "5m"
INTRADAY_PERIOD   = "1d"

LOG_LEVEL = "INFO"

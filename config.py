"""
ai_cake_monitor/config.py – Jensen Huang's AI 5-layer cake monitor config.

Layer mapping (10 sub-layers):
  1   Energy / Power
  2a  GPU / ASIC
  2b  HBM / Memory
  2c  CPU / SoC
  3   Networking / CPO
  4   Model / Software
  5a  Application / Robotics (industrial)
  5b  Humanoid / AI Robotics
  5c  Satellite / LEO
  5d  Consumer Electronics
"""
from __future__ import annotations

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

LAYERS: dict[str, dict] = {
    # ── Layer 1: Energy ───────────────────────────────────────────────────────
    "energy": {
        "label": "⚡ Energy / Power",
        "cake_layer": 1,
        "tickers": ["CEG", "VST", "GEV", "FSLR", "NEE"],
        "ticker_labels": {
            "GEV": "GE Vernova",
        },
    },

    # ── Layer 2: Silicon ──────────────────────────────────────────────────────
    "chip_core": {
        "label": "🧠 GPU / ASIC",
        "cake_layer": 2,
        "tickers": ["NVDA", "TSM", "AVGO", "ASML", "AMD"],
        "ticker_labels": {},
    },
    "chip_memory": {
        "label": "💾 HBM / Memory",
        "cake_layer": 2,
        "tickers": ["MU", "000660.KS", "005930.KS", "WDC", "LRCX"],
        "ticker_labels": {
            "000660.KS": "SKHynix",
            "005930.KS": "Samsung",
            "WDC":       "Western Digital",
            "LRCX":      "Lam Research",
        },
    },
    "chip_cpu": {
        "label": "🔲 CPU / SoC",
        "cake_layer": 2,
        "tickers": ["ARM", "INTC", "QCOM", "2454.TW", "MCHP"],
        "ticker_labels": {
            "2454.TW": "MediaTek",
            "MCHP":    "Microchip",
        },
    },

    # ── Layer 3: Networking ───────────────────────────────────────────────────
    "infra_cpo": {
        "label": "🔌 Networking / CPO",
        "cake_layer": 3,
        "tickers": ["MRVL", "ANET", "LITE", "COHR", "CIEN"],
        "ticker_labels": {
            "CIEN": "Ciena",
        },
    },

    # ── Layer 4: Software ─────────────────────────────────────────────────────
    "model_software": {
        "label": "🤖 Model / Software",
        "cake_layer": 4,
        "tickers": ["NOW", "PLTR", "CRM", "MSFT", "META"],
        "ticker_labels": {},
    },

    # ── Layer 5: Applications ─────────────────────────────────────────────────
    "application_robotics": {
        "label": "🦾 Industrial Robotics",
        "cake_layer": 5,
        # FANUY=FANUC, YASKY=Yaskawa, ABBNY=ABB, ROK=Rockwell, TSLA=humanoid narrative
        "tickers": ["FANUY", "YASKY", "ABBNY", "ROK", "TSLA"],
        "ticker_labels": {
            "FANUY": "FANUC",
            "YASKY": "Yaskawa",
            "ABBNY": "ABB",
            "ROK":   "Rockwell",
        },
    },
    "humanoid_robotics": {
        "label": "🤖 Humanoid / AI Robots",
        "cake_layer": 5,
        # Pure-play AI robotics: surgical, automation software, industrial AI
        "tickers": ["ISRG", "PATH", "HON", "EMR", "TER"],
        "ticker_labels": {
            "ISRG": "Intuitive Surgical",
            "PATH": "UiPath",
            "HON":  "Honeywell",
            "EMR":  "Emerson",
            "TER":  "Teradyne",
        },
    },
    "satellite": {
        "label": "🛰️ Satellite / LEO",
        "cake_layer": 5,
        # Low-earth orbit satellite communications & launch
        "tickers": ["ASTS", "RKLB", "LUNR", "VSAT", "GSAT"],
        "ticker_labels": {
            "ASTS": "AST SpaceMobile",
            "RKLB": "Rocket Lab",
            "LUNR": "Intuitive Machines",
            "VSAT": "Viasat",
            "GSAT": "Globalstar",
        },
    },
    "consumer": {
        "label": "📱 Consumer Electronics",
        "cake_layer": 5,
        # AI-driven consumer tech & platforms
        "tickers": ["AAPL", "AMZN", "GOOGL", "NFLX", "SHOP"],
        "ticker_labels": {
            "GOOGL": "Alphabet",
            "NFLX":  "Netflix",
            "SHOP":  "Shopify",
        },
    },
}

BENCHMARK = "^GSPC"
VIX       = "^VIX"

# Intraday interval for rebound calculation
INTRADAY_INTERVAL = "5m"
INTRADAY_PERIOD   = "1d"

LOG_LEVEL = "INFO"

"""
ai_cake_monitor/analyzer.py – Layer aggregation and 5-question analysis.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import LAYERS


# ── Q1 + Q2: Layer-level performance ─────────────────────────────────────────

def layer_performance(snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Per-layer summary sorted best → worst by avg_change.
    Answers Q1 (which layer fell most/least) and Q2 (resilience context).
    """
    if snapshot.empty:
        return pd.DataFrame()

    rows = []
    for layer_id, cfg in LAYERS.items():
        sub = snapshot[snapshot["layer"] == layer_id].copy()
        if sub.empty:
            continue
        chg = sub["change_pct"].dropna()
        if chg.empty:
            continue

        best_idx  = sub["change_pct"].idxmax()
        worst_idx = sub["change_pct"].idxmin()

        rows.append({
            "layer_id":      layer_id,
            "layer_label":   cfg["label"],
            "cake_layer":    cfg["cake_layer"],
            "n_tickers":     len(sub),
            "avg_change":    round(float(chg.mean()), 2),
            "median_change": round(float(chg.median()), 2),
            "best_ticker":   sub.loc[best_idx,  "display_name"],
            "best_pct":      round(float(chg.max()), 2),
            "worst_ticker":  sub.loc[worst_idx, "display_name"],
            "worst_pct":     round(float(chg.min()), 2),
            "avg_vol_ratio": round(float(sub["vol_ratio"].dropna().mean()), 2)
                             if sub["vol_ratio"].notna().any() else float("nan"),
        })

    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values("avg_change", ascending=False)
        .reset_index(drop=True)
    )


# ── Q3: Within-layer resilience ───────────────────────────────────────────────

def resilience_rank(snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Add relative_strength = ticker_change - layer_avg_change.
    Sort by layer then relative_strength descending → layer champions first.
    """
    if snapshot.empty:
        return snapshot.copy()

    result = snapshot.copy()
    result["relative_strength"] = float("nan")

    for layer_id in result["layer"].unique():
        mask = result["layer"] == layer_id
        chg  = result.loc[mask, "change_pct"].dropna()
        if chg.empty:
            continue
        layer_avg = float(chg.mean())
        result.loc[mask, "relative_strength"] = (
            result.loc[mask, "change_pct"] - layer_avg
        ).round(2)

    return (
        result
        .sort_values(["layer", "relative_strength"], ascending=[True, False])
        .reset_index(drop=True)
    )


# ── Q4: Intraday rebound ranking ──────────────────────────────────────────────

def rebound_rank(snapshot: pd.DataFrame) -> pd.DataFrame:
    """
    Rank all tickers by rebound_ratio descending.
    High ratio (→1.0) = closed near day-high after touching low.
    """
    if snapshot.empty or "rebound_ratio" not in snapshot.columns:
        return snapshot.copy()
    valid = snapshot[snapshot["rebound_ratio"].notna()]
    return valid.sort_values("rebound_ratio", ascending=False).reset_index(drop=True)


# ── Q5: Narrative / layer-rotation detection ──────────────────────────────────

def narrative_detection(
    layer_perf: pd.DataFrame,
    snapshot:   pd.DataFrame,
) -> dict:
    """
    Answer: which narrative is the market trading today?

    Signals used:
    - Leading layer  : highest avg_change (absolute leadership)
    - Weakest layer  : lowest avg_change  (what's being sold)
    - Money flow     : highest avg vol_ratio (capital rotation)
    - Verdict        : maps leading cake_layer → human narrative label
    """
    if layer_perf.empty:
        return {}

    result: dict = {}

    top = layer_perf.iloc[0]
    bot = layer_perf.iloc[-1]

    result["leading"] = {
        "layer_id": top["layer_id"],
        "label":    top["layer_label"],
        "avg_pct":  top["avg_change"],
    }
    result["weakest"] = {
        "layer_id": bot["layer_id"],
        "label":    bot["layer_label"],
        "avg_pct":  bot["avg_change"],
    }

    # Layer with highest average volume expansion
    vol_by_layer = (
        snapshot.groupby("layer")["vol_ratio"]
        .mean()
        .dropna()
    )
    if not vol_by_layer.empty:
        flow_layer = str(vol_by_layer.idxmax())
        result["money_flow"] = {
            "layer_id":      flow_layer,
            "label":         LAYERS.get(flow_layer, {}).get("label", flow_layer),
            "avg_vol_ratio": round(float(vol_by_layer[flow_layer]), 2),
        }

    # Human-readable verdict derived from the leading sub-layer's cake_layer number
    leading_id = result["leading"]["layer_id"]
    cake_n = LAYERS.get(leading_id, {}).get("cake_layer", 0)
    cake_map = {
        1: "⚡ Energy",
        2: "🧠 Silicon (Chips)",
        3: "🔌 Infrastructure",
        4: "🤖 Model / Software",
        5: "🦾 Application",
    }
    result["verdict"] = cake_map.get(cake_n, leading_id)

    # Signal strength assessment
    leading_pct = float(top["avg_change"]) if not np.isnan(top["avg_change"]) else 0.0
    if leading_pct > 1.5:
        result["signal"] = "strong"
    elif leading_pct > 0.2:
        result["signal"] = "weak"
    else:
        result["signal"] = "defensive"

    return result


# ── Master analysis builder ────────────────────────────────────────────────────

def build_full_analysis(snapshot: pd.DataFrame) -> dict:
    layer_perf    = layer_performance(snapshot)
    with_resil    = resilience_rank(snapshot)
    with_rebound  = rebound_rank(snapshot)
    narrative     = narrative_detection(layer_perf, snapshot)

    return {
        "snapshot":    snapshot,
        "layer_perf":  layer_perf,
        "resilience":  with_resil,
        "rebound":     with_rebound,
        "narrative":   narrative,
    }

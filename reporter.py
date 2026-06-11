"""
ai_cake_monitor/reporter.py – Markdown report + terminal summary.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from config import LAYERS, OUTPUT_DIR

logger = logging.getLogger(__name__)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _pct(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    sign = "+" if float(v) > 0 else ""
    return f"{sign}{float(v):.2f}%"


def _f(v, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{float(v):.{d}f}"


def _bar(v, width: int = 10) -> str:
    """
    ASCII progress bar mapping [-5%, +5%] → [empty … full].
    Centre = 0%.  Each block = 1%.
    """
    if v is None or np.isnan(v):
        return "─" * width
    # Map [-5, +5] to [0, 1]
    norm   = min(max((float(v) + 5.0) / 10.0, 0.0), 1.0)
    filled = round(norm * width)
    return "█" * filled + "░" * (width - filled)


def _sign_emoji(v) -> str:
    if v is None or np.isnan(v):
        return "  "
    return "🟢" if float(v) > 0 else ("🔴" if float(v) < 0 else "⚪")


# ── Markdown report ───────────────────────────────────────────────────────────

def generate_report(
    analysis:       dict,
    benchmark_chg:  float | None,
    date_str:       str,
    vix_level:      float | None = None,
    vix_chg:        float | None = None,
) -> str:
    layer_perf = analysis["layer_perf"]
    resilience = analysis["resilience"]
    rebound    = analysis["rebound"]
    narrative  = analysis["narrative"]
    snapshot   = analysis["snapshot"]

    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    bm_str = f"S&P500 {_pct(benchmark_chg)}" if benchmark_chg is not None else "S&P500 N/A"

    if vix_level is not None:
        vix_emoji = "🔴" if (vix_chg or 0) > 0 else "🟢"
        vix_chg_str = f" ({'+' if (vix_chg or 0) > 0 else ''}{vix_chg:.1f}%)" if vix_chg is not None else ""
        vix_mood = "極度恐慌" if vix_level >= 40 else ("恐慌" if vix_level >= 25 else ("警戒" if vix_level >= 18 else "平靜"))
        vix_str = f"{vix_emoji} VIX {vix_level:.1f}{vix_chg_str} [{vix_mood}]"
    else:
        vix_str = "VIX N/A"

    lines: list[str] = []

    lines += [
        f"# AI 五層蛋糕 監控日報 — {date_str}",
        f"> 產生時間: {now} | 基準: {bm_str} | {vix_str}",
        "",
        "---",
        "",
    ]

    # ── Q1 + Q2: Layer performance ────────────────────────────────────────────
    lines.append("## Q1 + Q2 各層漲跌排行\n")
    lines.append("> Q1: 哪層跌最深/最少？　Q2: 各層最強/最弱個股\n")

    if not layer_perf.empty:
        lines.append("| # | 蛋糕層 | 均漲跌 | 趨勢 | 最強個股 | 最弱個股 | Vol倍率 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for rank, row in layer_perf.iterrows():
            bar = _bar(row["avg_change"])
            lines.append(
                f"| {rank + 1} "
                f"| {row['layer_label']} "
                f"| **{_pct(row['avg_change'])}** "
                f"| `{bar}` "
                f"| {row['best_ticker']} ({_pct(row['best_pct'])}) "
                f"| {row['worst_ticker']} ({_pct(row['worst_pct'])}) "
                f"| {_f(row['avg_vol_ratio'])}x |"
            )

        top = layer_perf.iloc[0]
        bot = layer_perf.iloc[-1]
        lines += [
            "",
            f"> 🏆 **最強層**: {top['layer_label']} — 均漲 **{_pct(top['avg_change'])}**",
            f"> 💀 **最弱層**: {bot['layer_label']} — 均跌 **{_pct(bot['avg_change'])}**",
            "",
        ]
    else:
        lines.append("_無資料_\n")

    # ── Q3: Resilience within each layer ─────────────────────────────────────
    lines.append("## Q3 各層抗跌冠軍\n")
    lines.append("> relative_strength = 個股漲跌 − 所在層均值，正數 = 跑贏本層\n")

    if not resilience.empty and "relative_strength" in resilience.columns:
        lines.append("| 層 | 排名 | 個股 | 漲跌 | 相對強弱 | Vol倍率 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for layer_id, cfg in LAYERS.items():
            sub = resilience[resilience["layer"] == layer_id]
            if sub.empty:
                continue
            for rank, (_, row) in enumerate(sub.iterrows(), 1):
                rs     = row["relative_strength"]
                rs_str = f"+{rs:.2f}%" if (not np.isnan(rs) and rs > 0) else f"{rs:.2f}%"
                medal  = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"  {rank}")
                lines.append(
                    f"| {cfg['label']} "
                    f"| {medal} "
                    f"| **{row['display_name']}** "
                    f"| {_pct(row['change_pct'])} "
                    f"| {rs_str} "
                    f"| {_f(row['vol_ratio'])}x |"
                )
    else:
        lines.append("_無資料_\n")

    # ── Q4: Intraday rebound ranking ──────────────────────────────────────────
    lines += ["", "## Q4 從日內低點反彈最快\n"]
    lines.append(
        "> rebound_ratio = (收盤 − 日低) / (日高 − 日低)　"
        "→ 1.0 = 收盤剛好在日高　0.0 = 收盤剛好在日低\n"
    )

    if not rebound.empty and "rebound_ratio" in rebound.columns:
        top_reb = rebound[rebound["rebound_ratio"].notna()].head(10)
        if not top_reb.empty:
            lines.append("| # | 個股 | 層 | rebound_ratio | rebound_pct | 今日漲跌 |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for rank, (_, row) in enumerate(top_reb.iterrows(), 1):
                layer_label = LAYERS.get(row["layer"], {}).get("label", row["layer"])
                lines.append(
                    f"| {rank} "
                    f"| **{row['display_name']}** "
                    f"| {layer_label} "
                    f"| {_f(row['rebound_ratio'], 3)} "
                    f"| {_pct(row['rebound_pct'])} "
                    f"| {_pct(row['change_pct'])} |"
                )
        else:
            lines.append("_Intraday 資料不足（盤中執行或市場收盤）_\n")
    else:
        lines.append("_無資料_\n")

    # ── Q5: Narrative verdict ─────────────────────────────────────────────────
    lines += ["", "## Q5 市場現在交易哪個敘事？\n"]

    if narrative:
        verdict = narrative.get("verdict", "未知")
        leading = narrative.get("leading", {})
        weakest = narrative.get("weakest", {})
        mflow   = narrative.get("money_flow", {})
        signal  = narrative.get("signal", "unknown")

        signal_map = {
            "strong":    "✅ **強訊號** — 領先層明顯跑贏，資金方向清晰",
            "weak":      "⚠️ **弱訊號** — 各層表現接近，市場方向分散",
            "defensive": "🚨 **防禦模式** — 全層普跌，觀察現金/防禦類輪動",
        }

        lines += [
            f"### 🎯 當前主線: **{verdict}**",
            "",
            f"- 🔥 **最強層**: {leading.get('label', '')} "
            f"(均漲 {_pct(leading.get('avg_pct'))})",
            f"- 🥶 **最弱層**: {weakest.get('label', '')} "
            f"(均跌 {_pct(weakest.get('avg_pct'))})",
            f"- 💰 **資金流入**: {mflow.get('label', '')} "
            f"(Vol倍率 {_f(mflow.get('avg_vol_ratio'))}x)",
            "",
            f"> {signal_map.get(signal, '')}",
            "",
        ]

        # Quick visual of all layers (score relative to benchmark)
        if not layer_perf.empty and benchmark_chg is not None:
            lines.append("### 各層 vs S&P500\n")
            lines.append("| 層 | 均漲跌 | vs S&P | 方向 |")
            lines.append("| --- | --- | --- | --- |")
            for _, row in layer_perf.iterrows():
                vs_sp = row["avg_change"] - benchmark_chg
                vs_str = f"+{vs_sp:.2f}%" if vs_sp > 0 else f"{vs_sp:.2f}%"
                direction = "↑ 跑贏" if vs_sp > 0.3 else ("↓ 跑輸" if vs_sp < -0.3 else "→ 持平")
                lines.append(
                    f"| {row['layer_label']} "
                    f"| {_pct(row['avg_change'])} "
                    f"| {vs_str} "
                    f"| {direction} |"
                )
    else:
        lines.append("_無法計算（資料不足）_\n")

    # ── Full snapshot ─────────────────────────────────────────────────────────
    lines += ["", "---", "## 全股票快照\n"]

    if not snapshot.empty:
        # Merge relative_strength from resilience
        if not resilience.empty and "relative_strength" in resilience.columns:
            rs_map = (
                resilience[["ticker", "relative_strength"]]
                .drop_duplicates("ticker")
                .set_index("ticker")["relative_strength"]
            )
        else:
            rs_map = pd.Series(dtype=float)

        snap_sorted = snapshot.sort_values("change_pct", ascending=False)
        lines.append("| 個股 | 層 | 今日% | 相對強弱 | Rebound | Vol倍率 |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for _, row in snap_sorted.iterrows():
            layer_lbl = LAYERS.get(row["layer"], {}).get("label", row["layer"])
            rs = rs_map.get(row["ticker"], float("nan"))
            rs_str = (
                f"+{rs:.2f}%" if (not np.isnan(rs) and rs > 0)
                else (f"{rs:.2f}%" if not np.isnan(rs) else "N/A")
            )
            lines.append(
                f"| {_sign_emoji(row['change_pct'])} {row['display_name']} "
                f"| {layer_lbl} "
                f"| {_pct(row['change_pct'])} "
                f"| {rs_str} "
                f"| {_f(row.get('rebound_ratio', float('nan')), 3)} "
                f"| {_f(row.get('vol_ratio', float('nan')), 2)}x |"
            )

    n = len(snapshot) if not snapshot.empty else 0
    lines += [
        "",
        "---",
        f"_監控個股數: **{n}** | 本報告純屬量化監控輸出，不構成投資建議_",
    ]

    return "\n".join(lines)


# ── Terminal summary ──────────────────────────────────────────────────────────

def print_terminal_summary(
    analysis:      dict,
    benchmark_chg: float | None,
    vix_level:     float | None = None,
    vix_chg:       float | None = None,
) -> None:
    layer_perf = analysis["layer_perf"]
    narrative  = analysis["narrative"]

    print("\n" + "=" * 62)
    print("  AI 五層蛋糕 Monitor")
    bm = f"  S&P500: {_pct(benchmark_chg)}" if benchmark_chg is not None else "  S&P500: N/A"
    print(bm)
    if vix_level is not None:
        mood = "極度恐慌" if vix_level >= 40 else ("恐慌" if vix_level >= 25 else ("警戒" if vix_level >= 18 else "平靜"))
        vix_chg_str = f" ({'+' if (vix_chg or 0) > 0 else ''}{vix_chg:.1f}%)" if vix_chg is not None else ""
        print(f"  VIX:    {vix_level:.1f}{vix_chg_str}  [{mood}]")
    print("=" * 62)

    if not layer_perf.empty:
        print("\n  層別表現 (最強 → 最弱):")
        for _, row in layer_perf.iterrows():
            bar  = _bar(row["avg_change"], 8)
            sign = "+" if row["avg_change"] > 0 else ""
            chg  = f"{sign}{row['avg_change']:.2f}%"
            print(f"  {row['layer_label']:<36} {chg:>7}  [{bar}]")

    if narrative:
        verdict = narrative.get("verdict", "未知")
        leading = narrative.get("leading", {})
        weakest = narrative.get("weakest", {})
        print(f"\n  🎯 當前主線: {verdict}")
        print(f"     最強: {leading.get('label', '')} ({_pct(leading.get('avg_pct'))})")
        print(f"     最弱: {weakest.get('label', '')} ({_pct(weakest.get('avg_pct'))})")
        signal = narrative.get("signal", "")
        if signal == "strong":
            print("     訊號: ✅ 強 — 方向清晰")
        elif signal == "weak":
            print("     訊號: ⚠️  弱 — 方向分散")
        else:
            print("     訊號: 🚨 防禦 — 全層承壓")

    print("=" * 62 + "\n")


# ── Save ──────────────────────────────────────────────────────────────────────

def save_report(content: str, date_str: str) -> Path:
    path = OUTPUT_DIR / f"ai_cake_monitor_{date_str}.md"
    path.write_text(content, encoding="utf-8")
    logger.info("Report saved: %s", path)
    return path

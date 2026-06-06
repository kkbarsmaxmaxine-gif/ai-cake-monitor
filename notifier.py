"""
notifier.py – Telegram notification for AI Cake Monitor.

Requires env vars:
  TELEGRAM_BOT_TOKEN  – from @BotFather
  TELEGRAM_CHAT_ID    – your personal or group chat ID
"""
from __future__ import annotations

import logging
import os
import urllib.request
import urllib.parse
import urllib.error
import json
from pathlib import Path

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _post(token: str, method: str, payload: dict) -> bool:
    url  = TELEGRAM_API.format(token=token, method=method)
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.warning("Telegram API error: %s", result)
                return False
            return True
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        logger.warning("Telegram HTTP %s: %s", exc.code, body)
        return False
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


def _post_document(token: str, chat_id: str, path: Path, caption: str = "") -> bool:
    """Send a file using multipart/form-data."""
    import urllib.error
    boundary = "----TGBoundary"
    with open(path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"{caption}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{path.name}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    url = TELEGRAM_API.format(token=token, method="sendDocument")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.warning("Telegram sendDocument error: %s", result)
                return False
            return True
    except Exception as exc:
        logger.warning("Telegram sendDocument failed: %s", exc)
        return False


def _pct(v) -> str:
    if v is None:
        return "N/A"
    try:
        sign = "+" if float(v) > 0 else ""
        return f"{sign}{float(v):.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def build_message(analysis: dict, benchmark_chg: float | None, date_str: str) -> str:
    layer_perf = analysis.get("layer_perf")
    narrative  = analysis.get("narrative", {})
    snapshot   = analysis.get("snapshot")

    bm = f"S&P500 {_pct(benchmark_chg)}" if benchmark_chg is not None else "S&P500 N/A"

    lines = [
        f"📊 AI 五層蛋糕 {date_str}",
        f"基準: {bm}",
        "",
    ]

    # Layer ranking
    if layer_perf is not None and not layer_perf.empty:
        lines.append("各層漲跌:")
        for _, row in layer_perf.iterrows():
            chg  = row["avg_change"]
            sign = "▲" if chg > 0 else "▼"
            lines.append(f"  {sign} {row['layer_label']}  {_pct(chg)}")
        lines.append("")

    # Narrative
    if narrative:
        verdict = narrative.get("verdict", "")
        leading = narrative.get("leading", {})
        weakest = narrative.get("weakest", {})
        signal  = narrative.get("signal", "")
        signal_icon = {"strong": "✅", "weak": "⚠️", "defensive": "🚨"}.get(signal, "")
        signal_text = {"strong": "方向清晰", "weak": "方向分散", "defensive": "全層承壓"}.get(signal, "")
        lines += [
            f"🎯 當前主線: {verdict}",
            f"最強: {leading.get('label', '')} ({_pct(leading.get('avg_pct'))})",
            f"最弱: {weakest.get('label', '')} ({_pct(weakest.get('avg_pct'))})",
            f"{signal_icon} {signal_text}",
            "",
        ]

    # Top 3 resilient stocks
    resilience = analysis.get("resilience")
    if resilience is not None and not resilience.empty and "relative_strength" in resilience.columns:
        top3 = (
            resilience[resilience["relative_strength"].notna()]
            .nlargest(3, "relative_strength")
        )
        if not top3.empty:
            lines.append("抗跌冠軍:")
            for _, row in top3.iterrows():
                rs = row["relative_strength"]
                lines.append(
                    f"  {row['display_name']}  "
                    f"{_pct(row['change_pct'])} (+{rs:.2f}% vs 本層)"
                )

    lines.append("\n詳見 output/ 報告")
    return "\n".join(lines)


def send_notification(
    analysis:      dict,
    benchmark_chg: float | None,
    date_str:      str,
    report_path:   Path | None = None,
) -> None:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.info("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set)")
        return

    msg = build_message(analysis, benchmark_chg, date_str)
    ok  = _post(token, "sendMessage", {
        "chat_id": chat_id,
        "text":    msg,
    })
    if ok:
        logger.info("Telegram message sent")

    # Attach the Markdown report as a document
    if report_path and report_path.exists():
        _post_document(token, chat_id, report_path,
                       caption=f"AI Cake Monitor {date_str}")
        logger.info("Telegram document sent: %s", report_path.name)

"""
social_fetcher.py – social media buzz tracker for ai_cake_monitor (US stocks).

Platforms:
  Reddit  — set REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET env vars (free Reddit app)
  YouTube — set YOUTUBE_API_KEY env var (free Google Cloud key)
  News    — SemiAnalysis + TrendForce + EE Times (scraping, no auth)

All platforms degrade gracefully if credentials are absent.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

_REDDIT_SUBS = [
    "wallstreetbets", "stocks", "investing",
    "nvidia", "semiconductors", "StockMarket",
]

_NEWS_URLS = [
    ("semianalysis",  "https://semianalysis.com/"),
    ("trendforce",    "https://www.trendforce.com/news/"),
    ("eetimes",       "https://www.eetimes.com/"),
    ("tomshardware",  "https://www.tomshardware.com/news"),
    ("theregister",   "https://www.theregister.com/"),
    ("nikkei_asia",   "https://asia.nikkei.com/"),
]

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _search_terms(ticker: str, ticker_labels: dict[str, str]) -> list[str]:
    """Return the search strings for a ticker: [base_symbol, display_name]."""
    base  = ticker.split(".")[0]
    label = ticker_labels.get(ticker, "")
    terms = [base]
    if label and label.upper() != base.upper():
        terms.append(label)
    return terms


def _get(url: str, *, timeout: int = 15, extra_headers: dict | None = None) -> str:
    headers = {"User-Agent": _UA}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ── Reddit ────────────────────────────────────────────────────────────────────

def _reddit_token() -> str:
    import base64
    client_id     = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return ""
    creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=b"grant_type=client_credentials",
        headers={
            "Authorization": f"Basic {creds}",
            "User-Agent": "ai_cake_monitor/1.0",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("access_token", "")
    except Exception as exc:
        logger.warning("Reddit auth: %s", exc)
        return ""


def _fetch_reddit(tickers: list[str], ticker_labels: dict[str, str]) -> dict[str, int]:
    token = _reddit_token()
    if not token:
        logger.info("Reddit: no credentials — skipping")
        return {}

    auth_headers = {
        "Authorization": f"bearer {token}",
        "User-Agent": "ai_cake_monitor/1.0",
    }
    cutoff   = datetime.now(timezone.utc) - timedelta(hours=24)
    counts: dict[str, int] = {t: 0 for t in tickers}
    term_map  = {t: _search_terms(t, ticker_labels) for t in tickers}

    for sub in _REDDIT_SUBS:
        url = f"https://oauth.reddit.com/r/{sub}/new?limit=200"
        try:
            req = urllib.request.Request(url, headers=auth_headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                children = json.loads(resp.read()).get("data", {}).get("children", [])
            for post in children:
                pd  = post.get("data", {})
                ts  = pd.get("created_utc", 0)
                if datetime.fromtimestamp(ts, tz=timezone.utc) < cutoff:
                    continue
                text = (pd.get("title", "") + " " + pd.get("selftext", "")).upper()
                for ticker, terms in term_map.items():
                    if any(t.upper() in text for t in terms):
                        counts[ticker] += 1
            time.sleep(0.5)
        except Exception as exc:
            logger.warning("Reddit r/%s: %s", sub, exc)

    logger.info("Reddit: %d tickers with mentions", sum(1 for v in counts.values() if v))
    return {t: v for t, v in counts.items() if v > 0}


# ── YouTube ───────────────────────────────────────────────────────────────────

def _fetch_youtube(tickers: list[str], ticker_labels: dict[str, str]) -> dict[str, int]:
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        logger.info("YouTube: no API key — skipping")
        return {}

    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts: dict[str, int] = {}

    for ticker in tickers:
        terms = _search_terms(ticker, ticker_labels)
        q     = " OR ".join(f'"{t}"' for t in terms) + " stock"
        params = urllib.parse.urlencode({
            "key":           api_key,
            "q":             q,
            "type":          "video",
            "publishedAfter":yesterday,
            "part":          "snippet",
            "maxResults":    50,
        })
        try:
            data   = json.loads(_get(f"https://www.googleapis.com/youtube/v3/search?{params}"))
            counts[ticker] = len(data.get("items", []))
            time.sleep(0.2)
        except Exception as exc:
            logger.warning("YouTube %s: %s", ticker, exc)

    logger.info("YouTube: %d tickers with results", sum(1 for v in counts.values() if v))
    return {t: v for t, v in counts.items() if v > 0}


# ── News scraping ─────────────────────────────────────────────────────────────

def _fetch_news(tickers: list[str], ticker_labels: dict[str, str]) -> dict[str, int]:
    term_map = {t: _search_terms(t, ticker_labels) for t in tickers}
    counts: dict[str, int] = {t: 0 for t in tickers}

    for source, url in _NEWS_URLS:
        try:
            html = _get(url).lower()
            for ticker, terms in term_map.items():
                for term in terms:
                    counts[ticker] += html.count(term.lower())
        except Exception as exc:
            logger.warning("News %s: %s", source, exc)

    logger.info("News: %d tickers with mentions", sum(1 for v in counts.values() if v))
    return {t: v for t, v in counts.items() if v > 0}


# ── Public API ────────────────────────────────────────────────────────────────

def build_buzz(
    tickers:        list[str],
    ticker_labels:  dict[str, str],
    ticker_to_layer: dict[str, str],
) -> dict:
    """
    Fetch social buzz from all configured platforms and return aggregated results.

    Return schema:
      updated_at  : ISO timestamp
      sources     : list of platforms that returned data
      by_ticker   : ticker → {display_name, reddit, youtube, news, total, score}
      by_layer    : layer_id → {total, score, top_ticker}
      top5        : list of top-5 tickers by weighted score
    """
    logger.info("Social buzz: starting fetch")

    reddit_counts  = _fetch_reddit(tickers, ticker_labels)
    youtube_counts = _fetch_youtube(tickers, ticker_labels)
    news_counts    = _fetch_news(tickers, ticker_labels)

    sources = (
        (["reddit"]  if reddit_counts  else []) +
        (["youtube"] if youtube_counts else []) +
        (["news"]    if news_counts    else [])
    )

    by_ticker: dict[str, dict] = {}
    for t in tickers:
        r = reddit_counts.get(t, 0)
        y = youtube_counts.get(t, 0)
        n = news_counts.get(t, 0)
        total = r + y + n
        # weights: reddit×1, youtube×3 (higher quality signal), news×2
        score = r + y * 3 + n * 2
        by_ticker[t] = {
            "display_name": ticker_labels.get(t, t.split(".")[0]),
            "reddit":  r,
            "youtube": y,
            "news":    n,
            "total":   total,
            "score":   score,
        }

    top5 = sorted(by_ticker.items(), key=lambda x: x[1]["score"], reverse=True)[:5]
    top5_out = [{"ticker": k, **v} for k, v in top5 if v["total"] > 0]

    by_layer: dict[str, dict] = {}
    for t, buzz in by_ticker.items():
        lid = ticker_to_layer.get(t, "unknown")
        if lid not in by_layer:
            by_layer[lid] = {"total": 0, "score": 0, "top_ticker": "", "top_score": -1}
        by_layer[lid]["total"] += buzz["total"]
        by_layer[lid]["score"] += buzz["score"]
        if buzz["score"] > by_layer[lid]["top_score"]:
            by_layer[lid]["top_score"] = buzz["score"]
            by_layer[lid]["top_ticker"] = buzz["display_name"]

    logger.info("Social buzz done — sources: %s | top: %s",
                sources, top5_out[0]["display_name"] if top5_out else "—")
    return {
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sources":    sources,
        "by_ticker":  by_ticker,
        "by_layer":   by_layer,
        "top5":       top5_out,
    }

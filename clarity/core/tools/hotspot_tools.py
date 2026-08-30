"""Today's top stories and their related stocks."""

from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx


GOOGLE_NEWS_RSS = (
    "https://news.google.com/rss/search?"
    f"q={quote_plus('财经 OR 金融 OR 股市 OR 科技 OR 商业 when:1d')}"
    "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
)
EASTMONEY_SEARCH = "https://searchapi.eastmoney.com/api/suggest/get"
EASTMONEY_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ClarityFinance/1.0)"}


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def _parse_hotspots(content: bytes, limit: int = 10) -> list[dict[str, str | int]]:
    root = ElementTree.fromstring(content)
    hotspots: list[dict[str, str | int]] = []
    seen: set[str] = set()

    for item in root.findall("./channel/item"):
        source_node = item.find("source")
        source = (source_node.text or "") if source_node is not None else ""
        raw_title = item.findtext("title", "").strip()
        title = raw_title.removesuffix(f" - {source}").strip() if source else raw_title
        key = re.sub(r"\W", "", title).lower()
        if not title or key in seen:
            continue
        seen.add(key)

        published = item.findtext("pubDate", "")
        try:
            published = parsedate_to_datetime(published).astimezone().strftime("%m-%d %H:%M")
        except (TypeError, ValueError):
            pass

        hotspots.append(
            {
                "rank": len(hotspots) + 1,
                "title": title,
                "summary": _plain_text(item.findtext("description", ""))[:240],
                "source": source,
                "published": published,
                "link": item.findtext("link", ""),
            }
        )
        if len(hotspots) == limit:
            break

    return hotspots


async def get_today_hotspots(limit: int = 10) -> dict[str, Any]:
    """Return today's leading news events from Google News."""
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        response = await client.get(GOOGLE_NEWS_RSS)
        response.raise_for_status()

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "hotspots": _parse_hotspots(response.content, limit),
    }


def _event_keywords(title: str) -> list[str]:
    """Extract a small set of likely company names from a headline."""
    # ponytail: headline matching is enough here; add LLM entity extraction if measured misses justify it.
    title = re.sub(r"【[^】]+】", "", title)
    parts = re.split(
        r"[，,；;：:、/|]|助力|宣布|发布|启动|财报|出炉|上涨|下跌|走高|走低|"
        r"收购|投资|获批|签署|计划|完成|终止|回应|拟|将|与",
        title,
    )
    keywords = []
    for part in parts:
        for word in re.findall(r"[A-Za-z][A-Za-z0-9.&-]{1,15}|[\u4e00-\u9fff]{2,10}", part):
            if word.upper() in {"AI", "IPO", "A股", "美股", "港股"} or word in keywords:
                continue
            keywords.append(word)
    return keywords[:8]


def _parse_eastmoney(payload: dict[str, Any], keyword: str) -> dict[str, str] | None:
    items = payload.get("QuotationCodeTable", {}).get("Data") or []
    for item in items:
        if item.get("Classify") not in {"AStock", "HK", "UsStock"}:
            continue
        name = item.get("Name", "")
        if keyword.casefold() not in name.casefold() and name.casefold() not in keyword.casefold():
            continue
        return {
            "symbol": item.get("Code", ""),
            "name": name,
            "market": item.get("SecurityTypeName", "-"),
            "relation": f"事件中提及“{keyword}”",
        }
    return None


def _extract_stock_codes(text: str) -> list[dict[str, str]]:
    patterns = [
        (r"(?:NASDAQ|NYSE|AMEX)\s*[:：]\s*([A-Z][A-Z0-9.-]{0,5})", "美股"),
        (r"(?<!\d)([036]\d{5})(?:\.(?:SS|SZ))?(?!\d)", "A股"),
        (r"(?<!\d)(\d{4,5})\.HK\b", "港股"),
    ]
    found = []
    seen = set()
    for pattern, market in patterns:
        for symbol in re.findall(pattern, text, flags=re.IGNORECASE):
            symbol = symbol.upper()
            if symbol not in seen:
                seen.add(symbol)
                found.append({"symbol": symbol, "name": "-", "market": market, "relation": "关联报道明确提及"})
    return found


async def find_related_stocks(title: str, limit: int = 8) -> dict[str, Any]:
    """Search Eastmoney and finance news for stocks related to an event."""
    title = title.strip()
    if not title:
        raise ValueError("热点事件标题不能为空")

    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        related_url = (
            "https://news.google.com/rss/search?"
            f"q={quote_plus(f'{title} 股票 OR 上市公司 when:7d')}"
            "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
        )
        response = await client.get(related_url)
        response.raise_for_status()
        related_news = _parse_hotspots(response.content, 8)
        stocks = []
        seen = set()
        for keyword in _event_keywords(title):
            response = await client.get(
                EASTMONEY_SEARCH,
                params={"input": keyword, "type": 14, "count": 5, "token": EASTMONEY_TOKEN},
            )
            response.raise_for_status()
            stock = _parse_eastmoney(response.json(), keyword)
            if stock and stock["symbol"] not in seen:
                seen.add(stock["symbol"])
                stocks.append(stock)
            if len(stocks) == limit:
                break

    news = [
        {"title": str(item["title"]), "publisher": str(item["source"]), "link": str(item["link"])}
        for item in related_news[:5]
    ]

    evidence = " ".join(f"{item['title']} {item['summary']}" for item in related_news)
    for stock in _extract_stock_codes(evidence):
        if stock["symbol"] not in seen:
            seen.add(stock["symbol"])
            stocks.append(stock)

    return {
        "event": title,
        "stocks": stocks[:limit],
        "news": news,
        "finance_search_url": f"https://so.eastmoney.com/web/s?keyword={quote_plus(title)}",
    }

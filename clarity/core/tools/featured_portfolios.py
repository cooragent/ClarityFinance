"""Public holdings that can seed the existing self-evolving portfolio loop."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import httpx
from parsel import Selector

from .my_holdings import add_holdings
from .portfolio_evolution import _profile_dir, continue_portfolio, create_portfolio


SOURCE_URL = "https://www.dataroma.com/m/holdings.php?m={}"
FEATURED_PORTFOLIOS = [
    {"id": "BRK", "name": "沃伦·巴菲特", "fund": "Berkshire Hathaway", "style": "价值 / 大盘"},
    {"id": "HH", "name": "段永平", "fund": "H&H International Investment", "style": "科技 / 消费"},
    {"id": "TGM", "name": "蔡斯·科尔曼", "fund": "Tiger Global Management", "style": "全球科技成长"},
    {"id": "vg", "name": "Viking Global", "fund": "Viking Global Investors", "style": "全球成长"},
    {"id": "LPC", "name": "斯蒂芬·曼德尔", "fund": "Lone Pine Capital", "style": "成长 / 科技"},
    {"id": "AM", "name": "大卫·泰珀", "fund": "Appaloosa Management", "style": "科技 / 宏观"},
    {"id": "psc", "name": "比尔·阿克曼", "fund": "Pershing Square", "style": "集中持仓"},
    {"id": "HC", "name": "李录", "fund": "Himalaya Capital", "style": "价值 / 科技"},
    {"id": "GFT", "name": "盖茨基金会信托", "fund": "Gates Foundation Trust", "style": "长期 / 多元"},
    {"id": "SAM", "name": "迈克尔·伯里", "fund": "Scion Asset Management", "style": "逆向 / 事件"},
]


def get_featured_portfolios() -> list[dict]:
    return [
        {"rank": rank, **item, "source_url": SOURCE_URL.format(item["id"])}
        for rank, item in enumerate(FEATURED_PORTFOLIOS, 1)
    ]


def _parse_holdings(html: str, manager_id: str, limit: int) -> dict:
    selector = Selector(text=html)
    manager = selector.xpath("normalize-space(//div[@id='f_name'])").get()
    details = " ".join(selector.xpath("//p[@id='p2']//text()").getall())
    period = re.search(r"Period:\s*(.+?)\s*Portfolio date:", details)
    portfolio_date = re.search(r"Portfolio date:\s*(.+?)\s*No\. of stocks:", details)
    holdings = []
    for row in selector.xpath("//table[@id='grid']//tbody/tr"):
        ticker = row.css("td.stock a::text").get()
        weight = row.xpath("./td[3]/text()").get()
        if not ticker or not weight:
            continue
        holdings.append(
            {
                "ticker": ticker.strip().replace(".", "-"),
                "name": (row.css("td.stock span::text").get() or "").removeprefix(" - ").strip(),
                "weight_pct": float(weight),
                "activity": " ".join(row.xpath("./td[4]//text()").getall()).strip(),
            }
        )
        if len(holdings) >= limit:
            break
    if not manager or not holdings:
        raise ValueError("公开持仓页面暂时没有可用数据")
    return {
        "id": manager_id,
        "manager": manager,
        "period": period.group(1).strip() if period else "未知",
        "portfolio_date": portfolio_date.group(1).strip() if portfolio_date else "未知",
        "source_url": SOURCE_URL.format(manager_id),
        "holdings": holdings,
    }


def fetch_featured_holdings(featured_id: str, limit: int = 20) -> dict:
    if featured_id not in {item["id"] for item in FEATURED_PORTFOLIOS}:
        raise ValueError("未知的明星组合")
    response = httpx.get(
        SOURCE_URL.format(featured_id),
        headers={"User-Agent": "Mozilla/5.0 ClarityFinance/0.1"},
        timeout=15,
        follow_redirects=True,
    )
    response.raise_for_status()
    return _parse_holdings(response.text, featured_id, min(max(limit, 2), 30))


def follow_featured_portfolio(
    featured_id: str,
    profile_prefix: str,
    risk: str,
    portfolio_size: int,
    target_return_pct: float,
    max_drawdown_pct: float,
    trading_cost_pct: float,
    years: int = 3,
    rounds: int = 3,
    end: str | None = None,
) -> dict:
    featured = next((item for item in FEATURED_PORTFOLIOS if item["id"] == featured_id), None)
    if not featured:
        raise ValueError("未知的明星组合")
    disclosure = fetch_featured_holdings(featured_id)
    end = end or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.fromisoformat(end) - timedelta(days=int(years) * 365)).strftime("%Y-%m-%d")
    period = re.sub(r"[^A-Za-z0-9]+", "-", disclosure["period"]).strip("-")
    profile = f"{profile_prefix.strip() or 'Follow'}-{featured['name']}-{period}"
    if (_profile_dir(profile) / "state.json").exists():
        result = continue_portfolio(profile, rounds, end)
    else:
        tickers = ",".join(item["ticker"] for item in disclosure["holdings"])
        result = create_portfolio(
            profile, ["美股"], ["科技"], risk,
            min(int(portfolio_size), len(disclosure["holdings"])),
            target_return_pct, max_drawdown_pct, trading_cost_pct,
            start, end, rounds, tickers,
        )
    result["featured"] = featured
    result["source_holdings"] = disclosure
    add_holdings(
        disclosure["holdings"],
        "Follow 明星组合",
        f"{disclosure['manager']} · {disclosure['period']}",
    )
    return result

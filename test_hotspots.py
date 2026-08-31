from clarity.core.tools.hotspot_tools import (
    _event_keywords,
    _extract_stock_codes,
    _parse_eastmoney,
    _parse_hotspots,
)


def test_hotspot_and_stock_parsing():
    rss = b"""<?xml version="1.0"?><rss><channel>
      <item><title>Event A - Source A</title><link>https://a</link><source>Source A</source><description>Summary A</description></item>
      <item><title>Event A - Source B</title><link>https://b</link><source>Source B</source></item>
      <item><title>Event B - Source B</title><link>https://c</link><source>Source B</source></item>
    </channel></rss>"""
    hotspots = _parse_hotspots(rss)
    assert [item["title"] for item in hotspots] == ["Event A", "Event B"]
    assert [item["rank"] for item in hotspots] == [1, 2]

    stock = _parse_eastmoney(
        {
            "QuotationCodeTable": {
                "Data": [
                    {"Code": "688825", "Name": "长鑫科技", "Classify": "23", "SecurityTypeName": "科创板", "MktNum": "1", "QuoteID": "1.688825"}
                ]
            }
        },
        "长鑫科技",
    )
    assert stock == {
        "symbol": "688825",
        "name": "长鑫科技",
        "market": "科创板",
        "relation": "事件中提及“长鑫科技”",
        "chart_url": "https://quote.eastmoney.com/unify/r/1.688825",
        "source": "东方财富行情",
    }
    assert "英伟达" in _event_keywords("【早报】美股走高；英伟达财报出炉、SpaceX启动IPO")
    assert _event_keywords("长鑫科技下周一上市，发行价为8.66元/股")[0] == "长鑫科技"
    assert [
        stock["symbol"]
        for stock in _extract_stock_codes("NASDAQ: NVDA、600519 和 0700.HK")
    ] == ["NVDA", "600519", "0700"]

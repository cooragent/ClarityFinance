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
                    {"Code": "NVDA", "Name": "英伟达", "Classify": "UsStock", "SecurityTypeName": "美股"}
                ]
            }
        },
        "英伟达",
    )
    assert stock == {
        "symbol": "NVDA",
        "name": "英伟达",
        "market": "美股",
        "relation": "事件中提及“英伟达”",
    }
    assert "英伟达" in _event_keywords("【早报】美股走高；英伟达财报出炉、SpaceX启动IPO")
    assert [
        stock["symbol"]
        for stock in _extract_stock_codes("NASDAQ: NVDA、600519 和 0700.HK")
    ] == ["NVDA", "600519", "0700"]

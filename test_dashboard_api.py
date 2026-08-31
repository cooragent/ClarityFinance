from api import DashboardResult, _dashboard_rows
from clarity.core.tools.dashboard_scanner import MarketOverview


def test_dashboard_serializes_scanner_dataclasses():
    overviews = _dashboard_rows([MarketOverview(date="2026-08-30", market_type="美股")])
    result = DashboardResult(
        success=True,
        date="2026-08-30",
        market_overviews=overviews,
        recommendations=[],
        summary="",
    )
    assert result.market_overviews == [{
        "date": "2026-08-30",
        "market_type": "美股",
        "index_name": "",
        "index_value": 0.0,
        "index_change_pct": 0.0,
        "up_count": 0,
        "down_count": 0,
        "total_amount": 0.0,
        "top_sectors": [],
        "bottom_sectors": [],
    }]

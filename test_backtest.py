import pandas as pd

from clarity.core.tools.backtest_tools import run_sma_backtest


def test_sma_backtest_smoke():
    dates = pd.date_range("2025-01-01", periods=80, freq="D")
    close = [100 + i * 0.2 for i in range(35)] + [107 - (i - 35) * 0.3 for i in range(35, 55)] + [101 + (i - 55) * 0.5 for i in range(55, 80)]
    data = pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": [price + 1 for price in close],
            "low": [price - 1 for price in close],
            "close": close,
            "volume": 1_000,
        }
    )
    result = run_sma_backtest(data, "TEST", fast=5, slow=15)
    assert len(result["curve"]) == len(data) * 2
    assert set(result["curve"]["series"]) == {"均线策略", "买入持有"}
    assert list(result["orders"].columns) == ["日期", "操作", "价格", "数量", "手续费"]

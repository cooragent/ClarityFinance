# -*- coding: utf-8 -*-
"""Unit tests for TenguFetcher — no network / no API key required.

Mocks the HTTP layer (`_request`) and verifies the FIRM envelope is parsed and
normalized onto the project's STANDARD_COLUMNS, for both normalized and
Polygon-style bar field names, and that the provider is a no-op without a key.

Run:  python test_tengu_fetcher.py     (or: pytest test_tengu_fetcher.py)
"""
from clarity.core.tools.data_provider.base import DataFetchError
from clarity.core.tools.data_provider.tengu_fetcher import TenguFetcher

POLYGON_STYLE = {"results": [
    {"t": 1704067200000, "o": 100.0, "h": 105.0, "l": 99.0, "c": 104.0, "v": 1000000},
    {"t": 1704153600000, "o": 104.0, "h": 106.0, "l": 103.0, "c": 105.5, "v": 1200000},
    {"t": 1704240000000, "o": 105.5, "h": 108.0, "l": 105.0, "c": 107.0, "v": 900000},
]}
NORMALIZED_STYLE = {"data": [
    {"date": "2024-01-01", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0, "volume": 1000000},
    {"date": "2024-01-02", "open": 104.0, "high": 106.0, "low": 103.0, "close": 105.5, "volume": 1200000},
]}


def _mocked(payload):
    f = TenguFetcher(api_key="test-key")
    f._request = lambda path, params: payload  # bypass network
    return f


def test_polygon_style_bars():
    df = _mocked(POLYGON_STYLE).get_daily_data("AAPL", days=5)
    assert len(df) == 3
    for col in ("code", "date", "open", "high", "low", "close", "volume", "pct_chg", "ma5", "rsi"):
        assert col in df.columns, f"missing {col}"
    assert float(df["close"].iloc[-1]) == 107.0
    assert str(df["date"].iloc[0].date()) == "2024-01-01"  # epoch-ms decoded
    print("ok: polygon-style bars ->", len(df), "rows, last close", float(df["close"].iloc[-1]))


def test_normalized_bars():
    df = _mocked(NORMALIZED_STYLE).get_daily_data("AAPL", days=5)
    assert len(df) == 2
    assert float(df["open"].iloc[0]) == 100.0
    assert float(df["pct_chg"].iloc[1]) != 0.0  # computed
    print("ok: normalized bars ->", len(df), "rows")


def test_requires_api_key():
    f = TenguFetcher(api_key=None, base_url="https://firm.tengu.co")
    f.api_key = None  # ensure no env fallback
    try:
        f.get_daily_data("AAPL", days=5)
    except DataFetchError:
        print("ok: no key -> DataFetchError (fails over gracefully)")
        return
    raise AssertionError("expected DataFetchError without an API key")


if __name__ == "__main__":
    test_polygon_style_bars()
    test_normalized_bars()
    test_requires_api_key()
    print("\nALL TESTS PASSED")

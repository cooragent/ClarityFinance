import pandas as pd
import pytest

from clarity.core.state_store import state_history
from clarity.core.tools import simulated_trading

my_holdings = simulated_trading


def test_my_holdings_follow_update_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(my_holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (120.0, 100.0))

    my_holdings.add_holdings(
        [{"ticker": "NVDA", "name": "NVIDIA", "weight_pct": 12.5}],
        "Follow",
        "Tiger Global",
    )
    watchlist = my_holdings.holdings_snapshot()["holdings"][0]
    assert watchlist["last_price"] == 120
    assert watchlist["market_value"] == 0
    my_holdings.set_position("NVDA", 2, 80)
    snapshot = my_holdings.holdings_snapshot()

    assert snapshot["count"] == 1
    assert snapshot["holdings"][0]["status"] == "持有"
    assert snapshot["holdings"][0]["market_value"] == 240
    assert snapshot["holdings"][0]["total_gain"] == 80
    assert snapshot["holdings"][0]["sources"] == ["Follow · Tiger Global", "手动录入"]
    assert snapshot["account"]["available_capital_usd"] == 999_920
    assert (tmp_path / "clarity.sqlite3").exists()
    assert len(state_history(my_holdings.HOLDINGS_FILE)) == 3
    assert my_holdings.list_holdings()[0]["ticker"] == "NVDA"

    my_holdings.add_watchlist("NVDA", "NVIDIA")
    assert my_holdings.list_holdings()[0]["quantity"] == 2
    invested = my_holdings.invest_capital("NVDA", 100)
    assert invested["account"]["invested_capital_usd"] == 260
    assert invested["holdings"][0]["quantity"] > 2

    dates = pd.date_range("2026-01-01", periods=4)
    monkeypatch.setattr(
        my_holdings,
        "_price_history",
        lambda ticker, start, end: pd.Series([100, 101, 100, 102], index=dates, dtype=float),
    )
    performance = my_holdings.holdings_performance(7)
    assert performance["mode"] == "actual"
    assert performance["curve"][-1] == {
        "date": "2026-01-04",
        "series": "USD 每日收益",
        "value": 2.0,
    }

    my_holdings.set_position("NVDA", 0, 0)
    target_performance = my_holdings.holdings_performance(7)
    assert target_performance["mode"] == "target"
    assert len(target_performance["curve"]) == 3

    assert my_holdings.remove_holding("NVDA") == []
    assert my_holdings.buy_virtual_capital()["account"]["funding_capital_usd"] == 2_000_000


def test_follow_invests_100k_by_weight_once(tmp_path, monkeypatch):
    monkeypatch.setattr(my_holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (100.0, 100.0))
    holdings = [
        {"ticker": "NVDA", "name": "NVIDIA", "weight_pct": 60},
        {"ticker": "AAPL", "name": "Apple", "weight_pct": 40},
    ]

    first = my_holdings.invest_weighted_holdings(holdings, 100_000, "Follow", "Fund", "fund:q2")
    second = my_holdings.invest_weighted_holdings(holdings, 100_000, "Follow", "Fund", "fund:q2")

    assert first["account"]["invested_capital_usd"] == 100_000
    assert [row["quantity"] for row in first["holdings"]] == [600, 400]
    assert first["investment"] == {"capital_usd": 100_000, "positions": 2, "already_followed": False}
    assert second["investment"]["already_followed"] is True
    assert second["account"]["invested_capital_usd"] == 100_000

    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (80.0, 80.0))
    assert my_holdings.holdings_snapshot()["account"]["available_capital_usd"] == 880_000
    with pytest.raises(ValueError, match="可用股本不足"):
        my_holdings.invest_capital("NVDA", 900_000)

    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (120.0, 120.0))
    assert my_holdings.invest_capital("NVDA", 910_000)["account"]["available_capital_usd"] == 10_000


def test_snapshot_keeps_market_value_when_quotes_are_temporarily_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(my_holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    my_holdings.add_watchlist("AAPL", "Apple")
    my_holdings.set_position("NVDA", 2, 80)
    monkeypatch.setattr(
        my_holdings,
        "_prefetch_quotes",
        lambda tickers, quotes: {ticker: ValueError("offline") for ticker in tickers},
    )

    snapshot = my_holdings.holdings_snapshot()

    assert [row["ticker"] for row in snapshot["holdings"]] == ["NVDA", "AAPL"]
    assert snapshot["holdings"][0]["last_price"] == 80
    assert snapshot["holdings"][0]["market_value"] == 160
    assert snapshot["holdings"][0]["quote_stale"] is True
    assert snapshot["stale_quotes"] == ["NVDA"]


def test_simulated_positions_are_isolated_by_user(tmp_path, monkeypatch):
    monkeypatch.setattr(my_holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (100.0, 100.0))
    alice = "a" * 32
    bob = "b" * 32

    my_holdings.set_position("NVDA", 2, 80, user_id=alice)

    assert my_holdings.holdings_snapshot(alice)["holdings"][0]["ticker"] == "NVDA"
    assert my_holdings.holdings_snapshot(bob)["holdings"] == []
    assert my_holdings.holdings_snapshot(bob)["account"]["available_capital_usd"] == 1_000_000

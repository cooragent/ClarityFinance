from clarity.core.tools import my_holdings


def test_my_holdings_follow_update_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(my_holdings, "HOLDINGS_FILE", tmp_path / "holdings.json")
    monkeypatch.setattr(my_holdings, "_quote", lambda ticker: (120.0, 100.0))

    my_holdings.add_holdings(
        [{"ticker": "NVDA", "name": "NVIDIA", "weight_pct": 12.5}],
        "Follow",
        "Tiger Global",
    )
    my_holdings.set_position("NVDA", 2, 80)
    snapshot = my_holdings.holdings_snapshot()

    assert snapshot["count"] == 1
    assert snapshot["holdings"][0]["status"] == "持有"
    assert snapshot["holdings"][0]["market_value"] == 240
    assert snapshot["holdings"][0]["total_gain"] == 80
    assert snapshot["holdings"][0]["sources"] == ["Follow · Tiger Global", "手动录入"]

    assert my_holdings.remove_holding("NVDA") == []

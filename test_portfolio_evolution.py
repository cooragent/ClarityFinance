import pandas as pd

from clarity.core.state_store import state_history
from clarity.core.tools import portfolio_evolution
from clarity.core.tools.portfolio_evolution import _candidate, evaluate_portfolio


def test_portfolio_evaluation_and_bounded_candidate():
    dates = pd.bdate_range("2022-01-01", periods=500)
    prices = pd.DataFrame(
        {
            "A": [100 * (1.0008 ** i) for i in range(500)],
            "B": [100 * (1.0004 ** i) * (1 + 0.01 * ((i % 20) - 10) / 10) for i in range(500)],
            "C": [100 * (0.9999 ** i) for i in range(500)],
        },
        index=dates,
    )
    preferences = {
        "portfolio_size": 2,
        "target_return_pct": 10,
        "max_drawdown_pct": 20,
        "trading_cost_pct": 0.1,
    }
    params = {"momentum_days": 84, "volatility_days": 40, "rebalance_days": 20, "cash_buffer": 0.05, "max_weight": 0.6}
    result = evaluate_portfolio(prices, preferences, params)
    candidate, hypothesis = _candidate(params, 1, result, preferences)
    assert 0 <= result["score"] <= 100
    assert len(result["curve"]) == (len(prices) - int(len(prices) * 0.6)) * 2
    assert candidate["cash_buffer"] == 0
    assert "cash_buffer" in hypothesis


def test_evolution_persists_attempts_and_snapshot(tmp_path, monkeypatch):
    dates = pd.bdate_range("2022-01-01", periods=500)
    prices = pd.DataFrame(
        {
            "A": [100 * (1.0008 ** i) for i in range(500)],
            "B": [100 * (1.0004 ** i) for i in range(500)],
            "C": [100 * (1.0002 ** i) for i in range(500)],
        },
        index=dates,
    )
    monkeypatch.setattr(portfolio_evolution, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(portfolio_evolution, "fetch_prices", lambda *args: (prices, []))
    result = portfolio_evolution.create_portfolio(
        "test", ["美股"], ["科技"], "均衡", 2, 10, 20, 0.1,
        "2022-01-01", "2023-12-31", rounds=2, custom_tickers="A,B,C",
    )
    state_path = tmp_path / "test" / "state.json"
    state = portfolio_evolution._read_json(state_path, None)
    attempts = portfolio_evolution._read_json(tmp_path / "test" / "attempts.json", [])
    assert result["version"] == state["version"]
    assert state["next_version"] == 4
    assert len(attempts) == 2
    assert len(state_history(state_path)) >= 4

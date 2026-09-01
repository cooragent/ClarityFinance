from clarity.core.tools import featured_portfolios
from clarity.core.tools.featured_portfolios import _parse_holdings, get_featured_portfolios


def test_featured_holdings_parser():
    html = """
    <div id="f_name">Example Fund</div>
    <p id="p2">Period: <span>Q2 2026</span><br/>Portfolio date: <span>30 Jun 2026</span><br/>No. of stocks: <span>2</span></p>
    <table id="grid"><tbody>
      <tr><td></td><td class="stock"><a>BRK.B<span> - Berkshire Hathaway</span></a></td><td>55.5</td><td>Add 2%</td></tr>
      <tr><td></td><td class="stock"><a>AAPL<span> - Apple Inc.</span></a></td><td>44.5</td><td>Reduce 1%</td></tr>
    </tbody></table>
    """
    result = _parse_holdings(html, "X", 10)
    assert len(get_featured_portfolios()) == 10
    assert result["period"] == "Q2 2026"
    assert result["portfolio_date"] == "30 Jun 2026"
    assert result["holdings"][0] == {
        "ticker": "BRK-B", "name": "Berkshire Hathaway", "weight_pct": 55.5, "activity": "Add 2%"
    }


def test_follow_allocates_only_to_the_authenticated_users_simulation(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        featured_portfolios,
        "fetch_featured_holdings",
        lambda featured_id: {
            "manager": "Example Fund", "period": "Q2 2026", "portfolio_date": "2026-06-30",
            "holdings": [{"ticker": "AAPL", "name": "Apple", "weight_pct": 100}],
        },
    )
    monkeypatch.setattr(featured_portfolios, "_state_exists", lambda path: False)
    monkeypatch.setattr(featured_portfolios, "create_portfolio", lambda *args: {"profile": args[0]})

    def invest(*args):
        captured["user_id"] = args[-1]
        return {"investment": {"already_followed": False}, "account": {}}

    monkeypatch.setattr(featured_portfolios, "invest_weighted_holdings", invest)
    featured_portfolios.follow_featured_portfolio(
        "BRK", "Follow", "均衡", 5, 12, 20, 0.15, end="2026-08-31", user_id="alice"
    )

    assert captured["user_id"] == "alice"

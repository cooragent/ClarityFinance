"""User-isolated simulated stock trading and portfolio valuation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from functools import lru_cache
from math import isfinite
from pathlib import Path
from threading import Lock
from typing import Any

import pandas as pd

from ..state_store import read_state, state_exists, write_state
from .data_provider import MarketType, YfinanceFetcher, detect_market_type


PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOLDINGS_FILE = PROJECT_ROOT / "runtime/my_holdings.json"  # Legacy state is claimed by the first authenticated user.
DEFAULT_CAPITAL_USD = 1_000_000.0
VIRTUAL_CAPITAL_USD = 1_000_000.0
VIRTUAL_COIN_PRICE_USD = 10.0
_LOCK = Lock()
_YFINANCE_LOCK = Lock()


def _ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,14}", ticker):
        raise ValueError("股票代码格式无效")
    return ticker


def _new_state() -> dict[str, Any]:
    return {
        "account": {
            "initial_capital_usd": DEFAULT_CAPITAL_USD,
            "virtual_capital_usd": 0.0,
            "virtual_coin_spend_usd": 0.0,
            "realized_pnl_usd": 0.0,
            "followed_allocations": {},
        },
        "holdings": [],
    }


def _state_file(user_id: str | None) -> Path:
    return HOLDINGS_FILE if user_id is None else HOLDINGS_FILE.parent / "users" / user_id / "simulated_trading.json"


def _load_state(user_id: str | None = None) -> dict[str, Any]:
    path = _state_file(user_id)
    exists = state_exists(path)
    if user_id and not exists and state_exists(HOLDINGS_FILE):
        claim = HOLDINGS_FILE.parent / "legacy_simulation_claim.json"
        if not state_exists(claim):
            raw = read_state(HOLDINGS_FILE, _new_state())
            write_state(claim, {"user_id": user_id})
        else:
            raw = _new_state()
    else:
        raw = read_state(path, _new_state())
    state = {"account": _new_state()["account"], "holdings": raw} if isinstance(raw, list) else raw
    account = {**_new_state()["account"], **state.get("account", {})}
    normalized = {"account": account, "holdings": state.get("holdings", [])}
    if not exists or normalized != raw:
        write_state(path, normalized)
    return normalized


def _save_state(state: dict[str, Any], user_id: str | None = None) -> None:
    write_state(_state_file(user_id), state)
    holdings_performance.cache_clear()


def list_holdings(user_id: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        return _load_state(user_id)["holdings"]


def add_holdings(
    items: list[dict[str, Any]], source: str, source_detail: str = "", user_id: str | None = None,
) -> list[dict[str, Any]]:
    """Add watchlist entries without zeroing an existing position."""
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        state = _load_state(user_id)
        holdings = state["holdings"]
        indexed = {item["ticker"]: item for item in holdings}
        for incoming in items:
            ticker = _ticker(str(incoming.get("ticker") or incoming.get("symbol") or ""))
            holding = indexed.get(ticker)
            if holding is None:
                holding = {
                    "ticker": ticker,
                    "name": str(incoming.get("name") or ""),
                    "quantity": 0.0,
                    "avg_cost": 0.0,
                    "target_weight_pct": incoming.get("weight_pct"),
                    "sources": [],
                    "added_at": now,
                }
                holdings.append(holding)
                indexed[ticker] = holding
            elif incoming.get("name") and not holding.get("name"):
                holding["name"] = str(incoming["name"])
            if incoming.get("quantity") is not None:
                holding["quantity"] = max(float(incoming["quantity"]), 0)
                holding.pop("invested_capital_usd", None)
            if incoming.get("avg_cost") is not None:
                holding["avg_cost"] = max(float(incoming["avg_cost"]), 0)
                holding.pop("invested_capital_usd", None)
            if incoming.get("weight_pct") is not None:
                holding["target_weight_pct"] = float(incoming["weight_pct"])
            provenance = " · ".join(part for part in (source, source_detail) if part)
            if provenance and provenance not in holding["sources"]:
                holding["sources"].append(provenance)
            holding["updated_at"] = now
        _save_state(state, user_id)
        return holdings


def add_watchlist(ticker: str, name: str = "", user_id: str | None = None) -> list[dict[str, Any]]:
    return add_holdings([{"ticker": ticker, "name": name}], "手动加入", user_id=user_id)


def set_position(
    ticker: str, quantity: float, avg_cost: float, name: str = "", user_id: str | None = None,
) -> list[dict[str, Any]]:
    if not isfinite(quantity) or not isfinite(avg_cost):
        raise ValueError("持仓数量和平均成本必须是有限数字")
    if quantity > 0 and avg_cost <= 0:
        raise ValueError("持仓数量大于 0 时，平均成本必须大于 0")
    return add_holdings(
        [{"ticker": ticker, "name": name, "quantity": quantity, "avg_cost": avg_cost}],
        "手动录入",
        user_id=user_id,
    )


def _currency(ticker: str) -> str:
    market = detect_market_type(ticker)
    if ticker.isdigit() and len(ticker) <= 5:
        market = MarketType.HK_STOCK
    return {MarketType.A_SHARE: "CNY", MarketType.HK_STOCK: "HKD"}.get(market, "USD")


def _quote(ticker: str) -> tuple[float, float]:
    end = datetime.now() + timedelta(days=1)
    with _YFINANCE_LOCK:
        data = YfinanceFetcher().get_daily_data(
            ticker,
            start_date=(end - timedelta(days=14)).strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
        )
    return _last_two(data["close"])


def _last_two(values: pd.Series) -> tuple[float, float]:
    closes = values.dropna()
    if closes.empty:
        raise ValueError("没有最新行情")
    current = float(closes.iloc[-1])
    previous = float(closes.iloc[-2] if len(closes) > 1 else closes.iloc[-1])
    if not isfinite(current) or current <= 0:
        raise ValueError("最新行情无效")
    return current, previous


def _fx_per_usd(currency: str, quotes: dict[str, tuple[float, float]]) -> float:
    if currency == "USD":
        return 1.0
    ticker = f"{currency}=X"
    rate = _cached_quote(ticker, quotes)[0]
    if rate <= 0:
        raise ValueError("汇率行情无效")
    return rate


def _cached_quote(ticker: str, quotes: dict[str, tuple[float, float]]) -> tuple[float, float]:
    if ticker not in quotes:
        quotes[ticker] = _quote(ticker)
    return quotes[ticker]


def _prefetch_quotes(
    tickers: set[str], quotes: dict[str, tuple[float, float]],
) -> dict[str, Exception]:
    missing = tickers - quotes.keys()
    if not missing:
        return {}
    errors: dict[str, Exception] = {}
    if len(missing) >= 5:
        try:
            import yfinance as yf

            fetcher = YfinanceFetcher()
            symbols = {ticker: fetcher._convert_stock_code(ticker) for ticker in missing}
            end = datetime.now() + timedelta(days=1)
            with _YFINANCE_LOCK:
                data = yf.download(
                    list(symbols.values()),
                    start=(end - timedelta(days=14)).strftime("%Y-%m-%d"),
                    end=end.strftime("%Y-%m-%d"),
                    progress=False,
                    auto_adjust=True,
                    group_by="ticker",
                )
            for ticker, symbol in symbols.items():
                try:
                    quotes[ticker] = _last_two(data[symbol]["Close"])
                except Exception as exc:
                    errors[ticker] = exc
        except Exception as exc:
            errors = {ticker: exc for ticker in missing}
        return errors
    for ticker in missing:
        try:
            quotes[ticker] = _quote(ticker)
        except Exception as exc:
            errors[ticker] = exc
    return errors


def _snapshot(state: dict[str, Any], quotes: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:
    rows, errors, valuation_errors, stale_quotes = [], [], [], []
    if quotes is None:
        quotes = {}
    required_quotes = {item["ticker"] for item in state["holdings"]}
    required_quotes.update(
        f"{currency}=X"
        for currency in {_currency(item["ticker"]) for item in state["holdings"]}
        if currency != "USD"
    )
    quote_errors = _prefetch_quotes(required_quotes, quotes)
    for holding in state["holdings"]:
        ticker = holding["ticker"]
        quantity = float(holding.get("quantity") or 0)
        avg_cost = float(holding.get("avg_cost") or 0)
        last_price = previous_close = 0.0
        currency = _currency(ticker)
        fx_per_usd = 1.0
        try:
            if ticker in quote_errors:
                raise quote_errors[ticker]
            if currency != "USD" and f"{currency}=X" in quote_errors:
                raise quote_errors[f"{currency}=X"]
            last_price, previous_close = _cached_quote(ticker, quotes)
            fx_per_usd = _fx_per_usd(currency, quotes)
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
            if quantity > 0 and avg_cost > 0:
                last_price = previous_close = avg_cost
                stale_quotes.append(ticker)
            elif quantity > 0:
                valuation_errors.append(ticker)
        value = quantity * last_price
        invested_local = quantity * avg_cost
        invested_usd = float(holding.get("invested_capital_usd") or (invested_local / fx_per_usd))
        value_usd = value / fx_per_usd
        total_gain_usd = value_usd - invested_usd if avg_cost else 0.0
        rows.append(
            {
                **holding,
                "currency": currency,
                "last_price": round(last_price, 4),
                "day_change_pct": round((last_price / previous_close - 1) * 100, 2) if previous_close else 0,
                "market_value": round(value, 2),
                "market_value_usd": round(value_usd, 2),
                "invested_capital_usd": round(invested_usd, 2),
                "day_gain": round(quantity * (last_price - previous_close), 2),
                "total_gain": round(value - invested_local, 2) if avg_cost else 0,
                "total_gain_usd": round(total_gain_usd, 2),
                "total_gain_pct": round((value / invested_local - 1) * 100, 2) if invested_local else 0,
                "status": "持有" if quantity > 0 else "待投入股本",
                "quote_stale": ticker in stale_quotes,
            }
        )

    totals: dict[str, dict[str, float]] = {}
    for row in rows:
        group = totals.setdefault(row["currency"], {"market_value": 0, "day_gain": 0, "total_gain": 0})
        for key in group:
            group[key] = round(group[key] + row[key], 2)
    for row in rows:
        currency_total = totals[row["currency"]]["market_value"]
        row["allocation_pct"] = round(row["market_value"] / currency_total * 100, 2) if currency_total else 0
    rows.sort(key=lambda row: float(row.get("quantity") or 0) <= 0)

    account = state["account"]
    funding = float(account["initial_capital_usd"]) + float(account["virtual_capital_usd"])
    invested = sum(float(row["invested_capital_usd"]) for row in rows)
    unrealized = sum(float(row["total_gain_usd"]) for row in rows)
    equity = funding + float(account["realized_pnl_usd"]) + unrealized
    account_view = {
        **account,
        "funding_capital_usd": round(funding, 2),
        "invested_capital_usd": round(invested, 2),
        "unrealized_pnl_usd": round(unrealized, 2),
        "portfolio_equity_usd": round(equity, 2),
        "available_capital_usd": round(max(equity - invested, 0), 2),
    }
    return {
        "holdings": rows, "totals": totals, "count": len(rows), "errors": errors,
        "valuation_errors": valuation_errors, "stale_quotes": stale_quotes, "account": account_view,
    }


def holdings_snapshot(user_id: str | None = None) -> dict[str, Any]:
    with _LOCK:
        state = _load_state(user_id)
    return _snapshot(state)


def _apply_investment(
    state: dict[str, Any], incoming: dict[str, Any], capital_usd: float,
    price: float, fx_per_usd: float, source: str, source_detail: str,
) -> None:
    ticker = _ticker(str(incoming.get("ticker") or incoming.get("symbol") or ""))
    holding = next((item for item in state["holdings"] if item["ticker"] == ticker), None)
    if holding is None:
        holding = {
            "ticker": ticker, "name": str(incoming.get("name") or ""), "quantity": 0.0,
            "avg_cost": 0.0, "target_weight_pct": incoming.get("weight_pct"), "sources": [],
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }
        state["holdings"].append(holding)
    old_quantity = float(holding.get("quantity") or 0)
    old_avg_cost = float(holding.get("avg_cost") or 0)
    old_capital = float(holding.get("invested_capital_usd") or (old_quantity * old_avg_cost / fx_per_usd))
    added_quantity = capital_usd * fx_per_usd / price
    new_quantity = old_quantity + added_quantity
    holding.update(
        {
            "name": holding.get("name") or str(incoming.get("name") or ""),
            "quantity": new_quantity,
            "avg_cost": (old_quantity * old_avg_cost + added_quantity * price) / new_quantity,
            "invested_capital_usd": old_capital + capital_usd,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    if incoming.get("weight_pct") is not None:
        holding["target_weight_pct"] = float(incoming["weight_pct"])
    provenance = " · ".join(part for part in (source, source_detail) if part)
    if provenance and provenance not in holding["sources"]:
        holding["sources"].append(provenance)


def invest_capital(
    ticker: str, capital_usd: float, name: str = "", user_id: str | None = None,
) -> dict[str, Any]:
    ticker = _ticker(ticker)
    capital_usd = float(capital_usd)
    if not isfinite(capital_usd) or capital_usd <= 0:
        raise ValueError("投入股本必须大于 0")
    with _LOCK:
        state = _load_state(user_id)
        quotes: dict[str, tuple[float, float]] = {}
        before = _snapshot(state, quotes)
        if before["valuation_errors"] or before["stale_quotes"]:
            raise ValueError("部分持仓行情不可用，暂时无法准确计算可用股本")
        if capital_usd > before["account"]["available_capital_usd"] + 0.01:
            raise ValueError(f"可用股本不足，当前可用 ${before['account']['available_capital_usd']:,.2f}")
        price = _cached_quote(ticker, quotes)[0]
        currency = _currency(ticker)
        _apply_investment(state, {"ticker": ticker, "name": name}, capital_usd, price, _fx_per_usd(currency, quotes), "增加股本", "")
        _save_state(state, user_id)
        return _snapshot(state, quotes)


def invest_weighted_holdings(
    items: list[dict[str, Any]], capital_usd: float, source: str, source_detail: str,
    allocation_id: str, user_id: str | None = None,
) -> dict[str, Any]:
    capital_usd = float(capital_usd)
    if not isfinite(capital_usd) or capital_usd <= 0:
        raise ValueError("投入股本必须大于 0")
    with _LOCK:
        state = _load_state(user_id)
        if allocation_id in state["account"]["followed_allocations"]:
            return {**_snapshot(state), "investment": {"capital_usd": 0, "already_followed": True}}
        quotes: dict[str, tuple[float, float]] = {}
        before = _snapshot(state, quotes)
        if before["valuation_errors"] or before["stale_quotes"]:
            raise ValueError("部分持仓行情不可用，暂时无法准确计算可用股本")
        if capital_usd > before["account"]["available_capital_usd"] + 0.01:
            raise ValueError(f"可用股本不足，当前可用 ${before['account']['available_capital_usd']:,.2f}")
        priced = []
        weighted_items = []
        for item in items:
            weight = max(float(item.get("weight_pct") or 0), 0)
            if not isfinite(weight) or weight <= 0:
                continue
            ticker = _ticker(str(item.get("ticker") or item.get("symbol") or ""))
            weighted_items.append((item, ticker, weight))
        required_quotes = {ticker for _, ticker, _ in weighted_items}
        required_quotes.update(
            f"{currency}=X"
            for currency in {_currency(ticker) for _, ticker, _ in weighted_items}
            if currency != "USD"
        )
        quote_errors = _prefetch_quotes(required_quotes, quotes)
        for item, ticker, weight in weighted_items:
            try:
                if ticker in quote_errors:
                    raise quote_errors[ticker]
                currency = _currency(ticker)
                if currency != "USD" and f"{currency}=X" in quote_errors:
                    raise quote_errors[f"{currency}=X"]
                priced.append((item, weight, _cached_quote(ticker, quotes)[0], _fx_per_usd(_currency(ticker), quotes)))
            except Exception:
                continue
        weight_total = sum(weight for _, weight, _, _ in priced)
        if not priced or weight_total <= 0:
            raise ValueError("Follow 组合没有可交易的行情")
        for item, weight, price, fx_per_usd in priced:
            allocation = capital_usd * weight / weight_total
            _apply_investment(state, item, allocation, price, fx_per_usd, source, source_detail)
        state["account"]["followed_allocations"][allocation_id] = capital_usd
        _save_state(state, user_id)
        return {
            **_snapshot(state, quotes),
            "investment": {"capital_usd": capital_usd, "positions": len(priced), "already_followed": False},
        }


def remove_holding(ticker: str, user_id: str | None = None) -> list[dict[str, Any]]:
    ticker = _ticker(ticker)
    with _LOCK:
        state = _load_state(user_id)
        holding = next((item for item in state["holdings"] if item["ticker"] == ticker), None)
        if not holding:
            return state["holdings"]
        quantity = float(holding.get("quantity") or 0)
        if quantity > 0:
            quotes = {ticker: _quote(ticker)}
            fx_per_usd = _fx_per_usd(_currency(ticker), quotes)
            invested = float(holding.get("invested_capital_usd") or (quantity * float(holding.get("avg_cost") or 0) / fx_per_usd))
            proceeds = quantity * quotes[ticker][0] / fx_per_usd
            state["account"]["realized_pnl_usd"] += proceeds - invested
        state["holdings"] = [item for item in state["holdings"] if item["ticker"] != ticker]
        _save_state(state, user_id)
        return state["holdings"]


def buy_virtual_capital(packs: int = 1, user_id: str | None = None) -> dict[str, Any]:
    if not 1 <= int(packs) <= 100:
        raise ValueError("每次购买数量必须在 1 到 100 之间")
    with _LOCK:
        state = _load_state(user_id)
        state["account"]["virtual_capital_usd"] += int(packs) * VIRTUAL_CAPITAL_USD
        state["account"]["virtual_coin_spend_usd"] += int(packs) * VIRTUAL_COIN_PRICE_USD
        _save_state(state, user_id)
    return holdings_snapshot(user_id)


def _price_history(ticker: str, start: str, end: str) -> pd.Series:
    with _YFINANCE_LOCK:
        data = YfinanceFetcher().get_daily_data(ticker, start_date=start, end_date=end)
    data["date"] = pd.to_datetime(data["date"])
    return data.set_index("date")["close"].dropna().astype(float)


@lru_cache(maxsize=64)
def holdings_performance(days: int = 90, user_id: str | None = None) -> dict[str, Any]:
    """Reconstruct daily returns for current positions, separated by currency."""
    holdings = list_holdings(user_id)
    positions = [item for item in holdings if float(item.get("quantity") or 0) > 0]
    mode = "actual"
    if not positions:
        positions = [item for item in holdings if float(item.get("target_weight_pct") or 0) > 0]
        mode = "target"
    if not positions:
        return {"curve": [], "days": days, "mode": mode, "errors": []}

    end = datetime.now() + timedelta(days=1)
    start = end - timedelta(days=days * 2 + 30)
    grouped: dict[str, list[tuple[pd.Series, float]]] = {}
    errors = []
    for holding in positions:
        try:
            prices = _price_history(
                holding["ticker"], start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            ).rename(holding["ticker"])
            exposure = float(holding["quantity"] if mode == "actual" else holding["target_weight_pct"])
            grouped.setdefault(_currency(holding["ticker"]), []).append((prices, exposure))
        except Exception as exc:
            errors.append(f"{holding['ticker']}: {exc}")

    curve = []
    for currency, entries in grouped.items():
        prices = pd.concat([item[0] for item in entries], axis=1).sort_index().ffill().dropna().tail(days + 1)
        exposures = pd.Series({item[0].name: item[1] for item in entries})
        if mode == "actual":
            returns = prices.mul(exposures, axis=1).sum(axis=1).pct_change().mul(100).dropna()
        else:
            weights = exposures / exposures.sum()
            returns = prices.pct_change().mul(weights, axis=1).sum(axis=1, min_count=1).mul(100).dropna()
        curve.extend(
            {"date": date.date().isoformat(), "series": f"{currency} 每日收益", "value": round(float(value), 4)}
            for date, value in returns.items()
        )
    return {"curve": sorted(curve, key=lambda item: (item["date"], item["series"])), "days": days, "mode": mode, "errors": errors}

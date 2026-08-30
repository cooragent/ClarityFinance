"""Durable, single-user holdings for the local Clarity app."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from .data_provider import MarketType, YfinanceFetcher, detect_market_type
from .portfolio_evolution import _atomic_json, _read_json


HOLDINGS_FILE = Path("runtime/my_holdings.json")
_LOCK = Lock()


def _ticker(value: str) -> str:
    ticker = value.strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-]{0,14}", ticker):
        raise ValueError("股票代码格式无效")
    return ticker


def list_holdings() -> list[dict[str, Any]]:
    with _LOCK:
        return _read_json(HOLDINGS_FILE, [])


def add_holdings(items: list[dict[str, Any]], source: str, source_detail: str = "") -> list[dict[str, Any]]:
    now = datetime.now().isoformat(timespec="seconds")
    with _LOCK:
        holdings = _read_json(HOLDINGS_FILE, [])
        indexed = {item["ticker"]: item for item in holdings}
        for incoming in items:
            ticker = _ticker(str(incoming.get("ticker") or incoming.get("symbol") or ""))
            holding = indexed.get(ticker)
            if holding is None:
                holding = {
                    "ticker": ticker,
                    "name": str(incoming.get("name") or ""),
                    "quantity": float(incoming.get("quantity") or 0),
                    "avg_cost": float(incoming.get("avg_cost") or 0),
                    "target_weight_pct": incoming.get("weight_pct"),
                    "sources": [],
                    "added_at": now,
                }
                holdings.append(holding)
                indexed[ticker] = holding
            elif incoming.get("name") and not holding.get("name"):
                holding["name"] = str(incoming["name"])
            if "quantity" in incoming:
                holding["quantity"] = max(float(incoming["quantity"]), 0)
            if "avg_cost" in incoming:
                holding["avg_cost"] = max(float(incoming["avg_cost"]), 0)
            if incoming.get("weight_pct") is not None:
                holding["target_weight_pct"] = float(incoming["weight_pct"])
            provenance = " · ".join(part for part in (source, source_detail) if part)
            if provenance and provenance not in holding["sources"]:
                holding["sources"].append(provenance)
            holding["updated_at"] = now
        _atomic_json(HOLDINGS_FILE, holdings)
        return holdings


def set_position(ticker: str, quantity: float, avg_cost: float, name: str = "") -> list[dict[str, Any]]:
    return add_holdings(
        [{"ticker": ticker, "name": name, "quantity": quantity, "avg_cost": avg_cost}],
        "手动录入",
    )


def remove_holding(ticker: str) -> list[dict[str, Any]]:
    ticker = _ticker(ticker)
    with _LOCK:
        holdings = [item for item in _read_json(HOLDINGS_FILE, []) if item["ticker"] != ticker]
        _atomic_json(HOLDINGS_FILE, holdings)
        return holdings


def _currency(ticker: str) -> str:
    market = detect_market_type(ticker)
    return {MarketType.A_SHARE: "CNY", MarketType.HK_STOCK: "HKD"}.get(market, "USD")


def _quote(ticker: str) -> tuple[float, float]:
    end = datetime.now() + timedelta(days=1)
    data = YfinanceFetcher().get_daily_data(
        ticker,
        start_date=(end - timedelta(days=14)).strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
    )
    closes = data["close"].dropna()
    if closes.empty:
        raise ValueError("没有最新行情")
    return float(closes.iloc[-1]), float(closes.iloc[-2] if len(closes) > 1 else closes.iloc[-1])


def holdings_snapshot() -> dict[str, Any]:
    rows, errors = [], []
    for holding in list_holdings():
        try:
            last_price, previous_close = _quote(holding["ticker"])
        except Exception as exc:
            last_price = previous_close = 0.0
            errors.append(f"{holding['ticker']}: {exc}")
        quantity = float(holding.get("quantity") or 0)
        avg_cost = float(holding.get("avg_cost") or 0)
        value = quantity * last_price
        invested = quantity * avg_cost
        rows.append(
            {
                **holding,
                "currency": _currency(holding["ticker"]),
                "last_price": round(last_price, 4),
                "day_change_pct": round((last_price / previous_close - 1) * 100, 2) if previous_close else 0,
                "market_value": round(value, 2),
                "day_gain": round(quantity * (last_price - previous_close), 2),
                "total_gain": round(value - invested, 2) if avg_cost else 0,
                "total_gain_pct": round((value / invested - 1) * 100, 2) if invested else 0,
                "status": "持有" if quantity > 0 else "待建仓",
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

    return {"holdings": rows, "totals": totals, "count": len(rows), "errors": errors}

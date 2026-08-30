"""Minimal Backtrader strategy validation."""

from __future__ import annotations

from math import sqrt
from typing import Any

import backtrader as bt
import pandas as pd

from .data_provider import DataFetcherManager


class _SmaCross(bt.Strategy):
    params = (("fast", 10), ("slow", 30), ("allocation", 0.95))

    def __init__(self):
        self.signal = bt.ind.CrossOver(
            bt.ind.SMA(self.data.close, period=self.p.fast),
            bt.ind.SMA(self.data.close, period=self.p.slow),
        )
        self.pending = None
        self.equity: list[tuple[Any, float]] = []
        self.orders: list[dict[str, Any]] = []
        self.closed_pnls: list[float] = []

    def _record_equity(self):
        self.equity.append((self.data.datetime.date(0), self.broker.getvalue()))

    def prenext(self):
        self._record_equity()

    def next(self):
        self._record_equity()
        if self.pending:
            return
        if not self.position and self.signal > 0:
            size = int(self.broker.getcash() * self.p.allocation / self.data.close[0])
            if size:
                self.pending = self.buy(size=size)
        elif self.position and self.signal < 0:
            self.pending = self.close()

    def notify_order(self, order):
        if order.status == order.Completed:
            self.orders.append(
                {
                    "日期": bt.num2date(order.executed.dt).date().isoformat(),
                    "操作": "买入" if order.isbuy() else "卖出",
                    "价格": round(order.executed.price, 2),
                    "数量": abs(int(order.executed.size)),
                    "手续费": round(order.executed.comm, 2),
                }
            )
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.pending = None

    def notify_trade(self, trade):
        if trade.isclosed:
            self.closed_pnls.append(trade.pnlcomm)


def run_sma_backtest(
    data: pd.DataFrame,
    ticker: str,
    fast: int = 10,
    slow: int = 30,
    initial_cash: float = 100_000,
    commission_pct: float = 0.1,
    slippage_pct: float = 0.05,
) -> dict[str, Any]:
    """Backtest a long-only moving-average crossover strategy."""
    if not ticker.strip():
        raise ValueError("股票代码不能为空")
    if fast < 2 or slow <= fast:
        raise ValueError("慢均线周期必须大于快均线周期，且快均线至少为 2")
    if initial_cash <= 0 or not 0 <= commission_pct <= 10 or not 0 <= slippage_pct <= 10:
        raise ValueError("初始资金必须大于 0，佣金和滑点必须在 0% 到 10% 之间")
    if data is None or len(data) <= slow:
        raise ValueError(f"历史数据不足，至少需要 {slow + 1} 根 K 线")

    frame = data.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").set_index("date")
    frame = frame[["open", "high", "low", "close", "volume"]].dropna()

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(bt.feeds.PandasData(dataname=frame))
    cerebro.addstrategy(_SmaCross, fast=fast, slow=slow)
    cerebro.broker.setcash(initial_cash)
    cerebro.broker.setcommission(commission=commission_pct / 100)
    cerebro.broker.set_slippage_perc(slippage_pct / 100)
    strategy = cerebro.run()[0]

    equity = pd.DataFrame(strategy.equity, columns=["date", "strategy"]).drop_duplicates("date", keep="last")
    equity["date"] = pd.to_datetime(equity["date"])
    closes = frame["close"].reindex(equity["date"].values, method="ffill").to_numpy()
    equity["benchmark"] = initial_cash * closes / frame["close"].iloc[0]
    daily_returns = equity["strategy"].pct_change().dropna()
    drawdown = equity["strategy"] / equity["strategy"].cummax() - 1
    sharpe = 0.0 if daily_returns.std() == 0 else daily_returns.mean() / daily_returns.std() * sqrt(252)
    wins = sum(pnl > 0 for pnl in strategy.closed_pnls)
    final_value = float(equity["strategy"].iloc[-1])

    curve = equity.melt("date", var_name="series", value_name="value")
    curve["series"] = curve["series"].map({"strategy": "均线策略", "benchmark": "买入持有"})
    return {
        "ticker": ticker.upper(),
        "start": frame.index[0].date().isoformat(),
        "end": frame.index[-1].date().isoformat(),
        "initial_cash": initial_cash,
        "final_value": final_value,
        "total_return_pct": (final_value / initial_cash - 1) * 100,
        "benchmark_return_pct": (frame["close"].iloc[-1] / frame["close"].iloc[0] - 1) * 100,
        "max_drawdown_pct": float(drawdown.min() * 100),
        "sharpe": float(sharpe),
        "closed_trades": len(strategy.closed_pnls),
        "win_rate_pct": wins / len(strategy.closed_pnls) * 100 if strategy.closed_pnls else 0.0,
        "curve": curve,
        "orders": pd.DataFrame(strategy.orders, columns=["日期", "操作", "价格", "数量", "手续费"]),
    }


def run_backtest(ticker: str, start: str, end: str, **kwargs) -> dict[str, Any]:
    """Fetch project-standardized prices and run the SMA strategy."""
    if not start or not end or pd.Timestamp(start) >= pd.Timestamp(end):
        raise ValueError("开始日期必须早于结束日期")
    data, source = DataFetcherManager().get_daily_data(ticker, start_date=start, end_date=end)
    result = run_sma_backtest(data, ticker, **kwargs)
    result["data_source"] = source
    return result

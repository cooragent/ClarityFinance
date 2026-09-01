"""Preference-driven portfolios with benchmarked, versioned self-evolution."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..state_store import DATABASE_FILE, read_state, state_exists, write_state
from .data_provider import YfinanceFetcher


RUNTIME_DIR = Path("runtime/portfolio_evolution")
UNIVERSES = {
    "美股": {
        "科技": ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "AVGO", "AMD", "ORCL", "CRM"],
        "消费": ["WMT", "COST", "HD", "MCD", "NKE", "PG", "PEP", "KO"],
        "医疗": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO", "ABT"],
        "金融": ["JPM", "BAC", "V", "MA", "BRK-B"],
        "能源": ["XOM", "CVX", "COP"],
    },
    "A股": {
        "科技": ["300750", "002594", "002415", "000725", "603986"],
        "消费": ["600519", "000858", "000333", "600887", "601888"],
        "医疗": ["600276", "300760", "000538", "300015"],
        "金融": ["601318", "600036", "601166", "600030"],
        "能源": ["601088", "600900", "601857", "600028"],
    },
    "港股": {
        "科技": ["00700", "09988", "03690", "01810", "00981"],
        "消费": ["02020", "02331", "09633", "06862"],
        "医疗": ["02269", "06160", "01093", "01177"],
        "金融": ["01299", "02318", "00939", "01398", "00388"],
        "能源": ["00883", "00386", "00857"],
    },
}
BASE_PARAMS = {
    "保守": {"momentum_days": 126, "volatility_days": 60, "rebalance_days": 20, "cash_buffer": 0.20, "max_weight": 0.30},
    "均衡": {"momentum_days": 84, "volatility_days": 40, "rebalance_days": 20, "cash_buffer": 0.05, "max_weight": 0.40},
    "进取": {"momentum_days": 42, "volatility_days": 20, "rebalance_days": 10, "cash_buffer": 0.00, "max_weight": 0.60},
}


def _atomic_json(path: Path, value: Any) -> None:
    write_state(path, value)


def _read_json(path: Path, default: Any) -> Any:
    return read_state(path, default)


def _state_exists(path: Path) -> bool:
    return state_exists(path)


def _append(path: Path, entry: dict[str, Any]) -> None:
    entries = _read_json(path, [])
    entries.append(entry)
    _atomic_json(path, entries)


def _profile_dir(profile: str, user_id: str | None = None) -> Path:
    profile = re.sub(r"[^\w\-\u4e00-\u9fff]", "_", profile.strip())[:40]
    if not profile:
        raise ValueError("组合名称不能为空")
    return RUNTIME_DIR / "users" / user_id / profile if user_id else RUNTIME_DIR / profile


def build_universe(markets: list[str], sectors: list[str], custom_tickers: str = "") -> list[str]:
    custom = [ticker.upper() for ticker in re.split(r"[,，\s]+", custom_tickers.strip()) if ticker]
    if custom:
        return list(dict.fromkeys(custom))
    if not markets or not sectors:
        raise ValueError("至少选择一个市场和一个偏好行业")
    tickers = [ticker for market in markets for sector in sectors for ticker in UNIVERSES.get(market, {}).get(sector, [])]
    return list(dict.fromkeys(tickers))


def fetch_prices(tickers: list[str], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    fetcher = YfinanceFetcher()
    series = {}
    errors = []
    for ticker in tickers:
        try:
            data = fetcher.get_daily_data(ticker, start_date=start, end_date=end)
            series[ticker] = data.set_index("date")["close"]
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
    if not series:
        raise ValueError("股票池没有可用行情：" + "; ".join(errors[:3]))
    prices = pd.DataFrame(series).sort_index().ffill()
    prices = prices.loc[:, prices.notna().mean() >= 0.9].dropna()
    if prices.empty:
        raise ValueError("股票行情日期无法对齐")
    return prices, errors


def _cap_weights(weights: pd.Series, cap: float) -> pd.Series:
    weights = weights / weights.sum()
    cap = max(cap, 1 / len(weights))
    for _ in range(len(weights)):
        over = weights > cap
        if not over.any() or (~over).sum() == 0:
            break
        excess = float((weights[over] - cap).sum())
        weights[over] = cap
        weights[~over] += excess * weights[~over] / weights[~over].sum()
    return weights / weights.sum()


def _metrics(returns: pd.Series) -> dict[str, float]:
    returns = returns.fillna(0)
    growth = float((1 + returns).prod())
    annual_return = growth ** (252 / max(len(returns), 1)) - 1 if growth > 0 else -1.0
    volatility = float(returns.std() * sqrt(252))
    sharpe = 0.0 if returns.std() == 0 else float(returns.mean() / returns.std() * sqrt(252))
    equity = (1 + returns).cumprod()
    max_drawdown = float((equity / equity.cummax() - 1).min())
    return {
        "annual_return": annual_return,
        "volatility": volatility,
        "sharpe": sharpe,
        "max_drawdown": max_drawdown,
        "total_return": growth - 1,
    }


def _preference_score(metrics: dict[str, float], benchmark: dict[str, float], preferences: dict[str, Any]) -> float:
    target = max(float(preferences["target_return_pct"]) / 100, 0.01)
    drawdown_limit = max(float(preferences["max_drawdown_pct"]) / 100, 0.01)
    return_points = 40 * np.clip(metrics["annual_return"] / (target * 1.5), 0, 1)
    drawdown_points = 30 * np.clip(1 - abs(metrics["max_drawdown"]) / drawdown_limit, 0, 1)
    sharpe_points = 20 * np.clip((metrics["sharpe"] + 0.5) / 2, 0, 1)
    benchmark_points = 10 if metrics["annual_return"] > benchmark["annual_return"] else 0
    return round(float(return_points + drawdown_points + sharpe_points + benchmark_points), 2)


def evaluate_portfolio(
    prices: pd.DataFrame,
    preferences: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Run one fixed-parameter, out-of-sample portfolio benchmark."""
    momentum_days = int(params["momentum_days"])
    volatility_days = int(params["volatility_days"])
    warmup = max(momentum_days, volatility_days)
    if len(prices) <= warmup + 30:
        raise ValueError(f"回测数据不足，当前策略至少需要 {warmup + 31} 个交易日")

    returns = prices.pct_change(fill_method=None).fillna(0)
    weights = pd.DataFrame(np.nan, index=prices.index, columns=prices.columns)
    size = min(int(preferences["portfolio_size"]), len(prices.columns))
    for index in range(warmup, len(prices), int(params["rebalance_days"])):
        momentum = prices.iloc[index] / prices.iloc[index - momentum_days] - 1
        volatility = returns.iloc[index - volatility_days + 1 : index + 1].std() * sqrt(252)
        ranking = (momentum / volatility.replace(0, np.nan)).dropna().nlargest(size)
        if ranking.empty:
            continue
        selected_vol = volatility[ranking.index].replace(0, np.nan).dropna()
        selected = _cap_weights(1 / selected_vol, float(params["max_weight"]))
        weights.iloc[index] = 0.0
        weights.loc[weights.index[index], selected.index] = selected * (1 - float(params["cash_buffer"]))

    weights = weights.ffill().fillna(0)
    held_weights = weights.shift(1).fillna(0)
    gross_returns = (held_weights * returns).sum(axis=1)
    costs = weights.diff().abs().sum(axis=1) * float(preferences["trading_cost_pct"]) / 100
    portfolio_returns = gross_returns - costs
    validation_start = max(warmup + 1, int(len(prices) * 0.6))
    validation_returns = portfolio_returns.iloc[validation_start:]
    benchmark_returns = returns.mean(axis=1).iloc[validation_start:]
    metrics = _metrics(validation_returns)
    benchmark_metrics = _metrics(benchmark_returns)
    score = _preference_score(metrics, benchmark_metrics, preferences)
    equity = (1 + validation_returns).cumprod()
    benchmark_equity = (1 + benchmark_returns).cumprod()
    latest = weights.iloc[-1]

    return {
        "score": score,
        "metrics": {key: round(float(value), 6) for key, value in metrics.items()},
        "benchmark_metrics": {key: round(float(value), 6) for key, value in benchmark_metrics.items()},
        "portfolio": [
            {"ticker": ticker, "weight": round(float(weight), 6)}
            for ticker, weight in latest[latest > 0].sort_values(ascending=False).items()
        ],
        "curve": pd.DataFrame(
            {
                "date": equity.index,
                "策略组合": equity.values,
                "等权基准": benchmark_equity.values,
            }
        ).melt("date", var_name="series", value_name="value"),
        "validation_start": prices.index[validation_start].date().isoformat(),
    }


def _candidate(reference: dict[str, Any], attempt: int, result: dict[str, Any], preferences: dict[str, Any]) -> tuple[dict[str, Any], str]:
    params = reference.copy()
    drawdown_limit = float(preferences["max_drawdown_pct"]) / 100
    moves = [
        ("cash_buffer", 0.05 if abs(result["metrics"]["max_drawdown"]) > drawdown_limit else -0.05),
        ("momentum_days", -21),
        ("momentum_days", 21),
        ("volatility_days", 10),
        ("volatility_days", -10),
        ("rebalance_days", 5),
        ("rebalance_days", -5),
    ]
    field, delta = moves[(attempt - 1) % len(moves)]
    limits = {
        "cash_buffer": (0.0, 0.4),
        "momentum_days": (21, 252),
        "volatility_days": (10, 126),
        "rebalance_days": (5, 63),
    }
    low, high = limits[field]
    params[field] = round(float(np.clip(params[field] + delta, low, high)), 2)
    if field != "cash_buffer":
        params[field] = int(params[field])
    return params, f"调整 {field}: {reference[field]} → {params[field]}"


def _benchmark_id(prices: pd.DataFrame) -> str:
    digest = hashlib.sha256(pd.util.hash_pandas_object(prices).values.tobytes()).hexdigest()[:10]
    return f"{prices.index[0].date()}_{prices.index[-1].date()}_{digest}"


def _public_result(state: dict[str, Any], evaluation: dict[str, Any], profile_dir: Path, errors: list[str]) -> dict[str, Any]:
    scoreboard = _read_json(profile_dir / "scoreboard.json", [])
    return {
        "profile": state["profile"],
        "version": state["version"],
        "preferences": state["preferences"],
        "params": state["params"],
        "universe": state["universe"],
        "score": evaluation["score"],
        "metrics": evaluation["metrics"],
        "benchmark_metrics": evaluation["benchmark_metrics"],
        "portfolio": evaluation["portfolio"],
        "curve": evaluation["curve"],
        "history": pd.DataFrame(scoreboard),
        "data_errors": errors,
        "state_path": f"{DATABASE_FILE}#portfolio_evolution/{profile_dir.name}/state",
    }


def create_portfolio(
    profile: str,
    markets: list[str],
    sectors: list[str],
    risk: str,
    portfolio_size: int,
    target_return_pct: float,
    max_drawdown_pct: float,
    trading_cost_pct: float,
    start: str,
    end: str,
    rounds: int = 3,
    custom_tickers: str = "",
    user_id: str | None = None,
) -> dict[str, Any]:
    profile_dir = _profile_dir(profile, user_id)
    if _state_exists(profile_dir / "state.json"):
        raise ValueError("该组合名称已存在，请使用“继续演进”或换一个名称")
    if risk not in BASE_PARAMS or not 2 <= portfolio_size <= 20 or rounds < 0 or rounds > 20:
        raise ValueError("风险偏好、持仓数量或演进轮数无效")
    if target_return_pct <= 0 or not 0 < max_drawdown_pct <= 100 or not 0 <= trading_cost_pct <= 10:
        raise ValueError("收益目标、最大回撤或交易成本无效")
    if pd.Timestamp(start) >= pd.Timestamp(end):
        raise ValueError("开始日期必须早于结束日期")

    universe = build_universe(markets, sectors, custom_tickers)
    preferences = {
        "markets": markets,
        "sectors": sectors,
        "risk": risk,
        "portfolio_size": int(portfolio_size),
        "target_return_pct": float(target_return_pct),
        "max_drawdown_pct": float(max_drawdown_pct),
        "trading_cost_pct": float(trading_cost_pct),
        "start": start,
    }
    prices, errors = fetch_prices(universe, start, end)
    if len(prices.columns) < min(portfolio_size, 2):
        raise ValueError("有效股票数量不足以生成组合")
    params = BASE_PARAMS[risk].copy()
    evaluation = evaluate_portfolio(prices, preferences, params)
    benchmark_id = _benchmark_id(prices)
    now = datetime.now().isoformat(timespec="seconds")
    state = {
        "profile": profile,
        "version": 1,
        "next_version": 2,
        "attempt": 0,
        "preferences": preferences,
        "universe": list(prices.columns),
        "params": params,
        "score": evaluation["score"],
        "metrics": evaluation["metrics"],
        "benchmark_id": benchmark_id,
        "updated_at": now,
    }
    _atomic_json(profile_dir / "state.json", state)
    _append(
        profile_dir / "scoreboard.json",
        {"time": now, "version": 1, "score": evaluation["score"], "annual_return_pct": round(evaluation["metrics"]["annual_return"] * 100, 2), "max_drawdown_pct": round(evaluation["metrics"]["max_drawdown"] * 100, 2), "benchmark_id": benchmark_id, "decision": "baseline"},
    )
    return continue_portfolio(profile, rounds, end, user_id) if rounds else _public_result(state, evaluation, profile_dir, errors)


def continue_portfolio(
    profile: str, rounds: int = 3, end: str | None = None, user_id: str | None = None,
) -> dict[str, Any]:
    profile_dir = _profile_dir(profile, user_id)
    state = _read_json(profile_dir / "state.json", None)
    if not state:
        raise ValueError("组合不存在，请先创建组合")
    if rounds < 1 or rounds > 20:
        raise ValueError("每次演进轮数必须在 1 到 20 之间")
    end = end or datetime.now().strftime("%Y-%m-%d")
    if pd.Timestamp(state["preferences"]["start"]) >= pd.Timestamp(end):
        raise ValueError("结束日期必须晚于组合的开始日期")
    prices, errors = fetch_prices(state["universe"], state["preferences"]["start"], end)
    benchmark_id = _benchmark_id(prices)
    reference = evaluate_portfolio(prices, state["preferences"], state["params"])
    state["score"], state["metrics"], state["benchmark_id"] = reference["score"], reference["metrics"], benchmark_id
    _atomic_json(profile_dir / "state.json", state)

    for _ in range(rounds):
        snapshot = profile_dir / "snapshots" / f"v{state['version']}-{benchmark_id}.json"
        if not _state_exists(snapshot):
            _atomic_json(snapshot, state)
        state["attempt"] += 1
        candidate_version = state["next_version"]
        state["next_version"] += 1
        _atomic_json(profile_dir / "state.json", state)
        candidate_params, hypothesis = _candidate(state["params"], state["attempt"], reference, state["preferences"])
        candidate = evaluate_portfolio(prices, state["preferences"], candidate_params)
        drawdown_limit = -float(state["preferences"]["max_drawdown_pct"]) / 100
        admissible = candidate["metrics"]["max_drawdown"] >= drawdown_limit or candidate["metrics"]["max_drawdown"] > reference["metrics"]["max_drawdown"]
        accepted = candidate["score"] > reference["score"] and admissible
        attempt_entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "candidate_version": candidate_version,
            "reference_version": state["version"],
            "benchmark_id": benchmark_id,
            "hypothesis": hypothesis,
            "reference_score": reference["score"],
            "candidate_score": candidate["score"],
            "admissible": admissible,
            "accepted": accepted,
        }
        _append(profile_dir / "attempts.json", attempt_entry)
        if accepted:
            reference = candidate
            state.update({"version": candidate_version, "params": candidate_params, "score": candidate["score"], "metrics": candidate["metrics"]})
            _atomic_json(profile_dir / "state.json", state)
            _append(
                profile_dir / "scoreboard.json",
                {"time": attempt_entry["time"], "version": candidate_version, "score": candidate["score"], "annual_return_pct": round(candidate["metrics"]["annual_return"] * 100, 2), "max_drawdown_pct": round(candidate["metrics"]["max_drawdown"] * 100, 2), "benchmark_id": benchmark_id, "decision": "accepted"},
            )
        # Rejected Candidates never touch the active params: rollback is implicit and auditable.

    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    _atomic_json(profile_dir / "state.json", state)
    return _public_result(state, reference, profile_dir, errors)

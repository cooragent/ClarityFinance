# -*- coding: utf-8 -*-
"""
TenguFetcher - Tengu FIRM 数据源 (US equities + filings/insider/13F/congressional)
=====================================================================================

数据来源：Tengu FIRM API (https://tengu.co/api) — 一个 API key 覆盖美股行情、基本面、
SEC 备案、内部人(Form 4)/机构(13F)/国会交易等。通过 MCP / REST 提供。

设计为「可选、按需启用」：仅当环境变量 TENGU_API_KEY (或 FIRM_API_KEY) 存在时才会被
DataFetcherManager 加入默认数据源列表，因此不设置 key 时对现有行为零影响。

免费 key（无需信用卡）：https://tengu.co/api

Env:
    TENGU_API_KEY   your Tengu API key (sent as the X-API-Key header)
    TENGU_FIRM_BASE optional base URL override (default https://firm.tengu.co)
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import List

import pandas as pd

from .base import (
    BaseFetcher,
    DataFetchError,
    RateLimitError,
    DataSourceUnavailableError,
    MarketType,
    STANDARD_COLUMNS,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = os.getenv("TENGU_FIRM_BASE", "https://firm.tengu.co")


class TenguFetcher(BaseFetcher):
    """
    Tengu FIRM 数据源实现

    优先级：1（美股优先，行情之外还带备案/基本面/另类数据）
    覆盖市场：美股 (NASDAQ/NYSE)
    """

    name = "TenguFetcher"
    priority = 1
    supported_markets: List[MarketType] = [MarketType.US_STOCK]

    # Historical OHLCV bars endpoint (day/week/month/hour/minute/second granularity).
    PRICES_PATH = "/api/v3/fundamentals/prices"

    def __init__(self, api_key: str = None, base_url: str = None, timeout: int = 20):
        self.api_key = api_key or os.getenv("TENGU_API_KEY") or os.getenv("FIRM_API_KEY")
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    # --- HTTP ---------------------------------------------------------------
    def _request(self, path: str, params: dict) -> object:
        if not self.api_key:
            raise DataSourceUnavailableError(
                "TenguFetcher 需要 TENGU_API_KEY（免费获取：https://tengu.co/api）"
            )
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"X-API-Key": self.api_key, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise RateLimitError(f"Tengu FIRM 速率限制 (429) for {params.get('ticker')}")
            if e.code in (401, 402, 403):
                raise DataSourceUnavailableError(
                    f"Tengu FIRM 鉴权/额度错误 ({e.code})；检查 TENGU_API_KEY 与套餐额度"
                )
            raise DataFetchError(f"Tengu FIRM HTTP {e.code}: {e.reason}") from e
        except urllib.error.URLError as e:
            raise DataFetchError(f"Tengu FIRM 网络错误: {e}") from e

    # --- BaseFetcher hooks --------------------------------------------------
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        payload = self._request(
            self.PRICES_PATH,
            {
                "ticker": stock_code.strip().upper(),
                "asset_class": "stocks",
                "interval": "day",
                "interval_multiplier": 1,
                "start_date": start_date,
                "end_date": end_date,
                "limit": 5000,
            },
        )
        bars = self._extract_bars(payload)
        if not bars:
            raise DataFetchError(f"Tengu FIRM 未返回 {stock_code} 的行情数据")
        return pd.DataFrame(bars)

    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """Map the FIRM bar fields onto the project's STANDARD_COLUMNS.

        Tolerant to both normalized keys (open/high/low/close/volume/date) and
        Polygon-style short keys (o/h/l/c/v/t), so it works regardless of the
        exact envelope field names.
        """
        df = df.copy()
        aliases = {
            "date": ["date", "t", "timestamp", "time", "datetime", "day"],
            "open": ["open", "o"],
            "high": ["high", "h"],
            "low": ["low", "l"],
            "close": ["close", "c", "adj_close", "adjClose"],
            "volume": ["volume", "v", "vol"],
        }
        cols = {}
        for std, candidates in aliases.items():
            for cand in candidates:
                if cand in df.columns:
                    cols[std] = df[cand]
                    break
        norm = pd.DataFrame(cols)

        missing = {"date", "open", "high", "low", "close"} - set(norm.columns)
        if missing:
            raise DataFetchError(
                f"Tengu FIRM 响应缺少字段 {sorted(missing)}；实际列: {list(df.columns)}"
            )

        norm["date"] = self._to_datetime(norm["date"])
        if "volume" not in norm.columns:
            norm["volume"] = 0

        norm["pct_chg"] = (norm["close"].astype(float).pct_change() * 100).fillna(0).round(2)
        norm["amount"] = norm["volume"].astype(float) * norm["close"].astype(float)
        norm["code"] = stock_code

        keep = ["code"] + STANDARD_COLUMNS
        return norm[[c for c in keep if c in norm.columns]]

    # --- helpers ------------------------------------------------------------
    @staticmethod
    def _extract_bars(payload: object) -> list:
        """Find the list of bars inside the FIRM response envelope."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("results", "bars", "prices", "data", "items", "ohlcv", "candles", "series"):
                val = payload.get(key)
                if isinstance(val, list):
                    return val
                if isinstance(val, dict):
                    for key2 in ("results", "bars", "prices", "items", "ohlcv", "candles"):
                        if isinstance(val.get(key2), list):
                            return val[key2]
        return []

    @staticmethod
    def _to_datetime(series: pd.Series) -> pd.Series:
        num = pd.to_numeric(series, errors="coerce")
        if num.notna().all() and float(num.max()) > 1e9:  # epoch seconds/millis
            unit = "ms" if float(num.max()) > 1e12 else "s"
            return pd.to_datetime(num, unit=unit)
        return pd.to_datetime(series, errors="coerce")

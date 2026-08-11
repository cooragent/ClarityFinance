# -*- coding: utf-8 -*-
"""
数据源策略层 - 支持 A股、H股、美股
===================================

数据源优先级：
1. AkshareFetcher (Priority 0) - A股首选
2. EfinanceFetcher (Priority 1) - A股备选
3. YfinanceFetcher (Priority 2) - 美股/港股/A股兜底

市场覆盖：
- A股: 上证(600xxx, 601xxx, 603xxx, 688xxx), 深证(000xxx, 002xxx, 300xxx)
- H股: 港交所 (xxxxx.HK)
- 美股: NASDAQ, NYSE (AAPL, NVDA, etc.)
"""

from .base import BaseFetcher, DataFetcherManager, DataFetchError, MarketType, detect_market_type
from .akshare_fetcher import AkshareFetcher
from .efinance_fetcher import EfinanceFetcher
from .yfinance_fetcher import YfinanceFetcher
from .tengu_fetcher import TenguFetcher

__all__ = [
    'BaseFetcher',
    'DataFetcherManager',
    'DataFetchError',
    'MarketType',
    'detect_market_type',
    'AkshareFetcher',
    'EfinanceFetcher',
    'YfinanceFetcher',
    'TenguFetcher',
]

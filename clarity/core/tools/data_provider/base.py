# -*- coding: utf-8 -*-
"""
数据源基类与管理器 - 支持多市场
===================================

设计模式：策略模式 (Strategy Pattern)
- BaseFetcher: 抽象基类，定义统一接口
- DataFetcherManager: 策略管理器，实现自动切换

支持市场：
- A股 (China A-shares)
- H股 (Hong Kong)
- US股 (NASDAQ/NYSE)
"""

from __future__ import annotations

import logging
import os
import random
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, List, Tuple

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# === 标准化列名定义 ===
STANDARD_COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']


class MarketType(Enum):
    """市场类型枚举"""
    A_SHARE = "a_share"      # A股 (上证/深证)
    HK_STOCK = "hk_stock"    # 港股
    US_STOCK = "us_stock"    # 美股 (NASDAQ/NYSE)
    UNKNOWN = "unknown"


class DataFetchError(Exception):
    """数据获取异常基类"""
    pass


class RateLimitError(DataFetchError):
    """API 速率限制异常"""
    pass


class DataSourceUnavailableError(DataFetchError):
    """数据源不可用异常"""
    pass


def detect_market_type(stock_code: str) -> MarketType:
    """
    根据股票代码自动识别市场类型
    
    规则：
    - A股: 6位数字 (600xxx, 000xxx, 300xxx, 688xxx)
    - 港股: 5位数字或 xxxxx.HK
    - 美股: 字母代码 (AAPL, NVDA)
    """
    code = stock_code.strip().upper()
    
    # 已带后缀的情况
    if '.SS' in code or '.SZ' in code:
        return MarketType.A_SHARE
    if '.HK' in code:
        return MarketType.HK_STOCK
    
    # 纯数字判断
    pure_code = code.replace('.', '')
    if pure_code.isdigit():
        if len(pure_code) == 6:
            # A股：6位数字
            return MarketType.A_SHARE
        elif len(pure_code) == 5:
            # 港股：5位数字
            return MarketType.HK_STOCK
    
    # 字母代码 -> 美股
    if code.isalpha() or (code.replace('-', '').replace('.', '').isalnum() and not code.isdigit()):
        return MarketType.US_STOCK
    
    return MarketType.UNKNOWN


class BaseFetcher(ABC):
    """
    数据源抽象基类
    
    职责：
    1. 定义统一的数据获取接口
    2. 提供数据标准化方法
    3. 实现通用的技术指标计算
    """
    
    name: str = "BaseFetcher"
    priority: int = 99
    supported_markets: List[MarketType] = []
    
    @abstractmethod
    def _fetch_raw_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从数据源获取原始数据（子类必须实现）"""
        pass
    
    @abstractmethod
    def _normalize_data(self, df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """标准化数据列名（子类必须实现）"""
        pass
    
    def supports_market(self, market_type: MarketType) -> bool:
        """检查是否支持指定市场"""
        return market_type in self.supported_markets
    
    def get_daily_data(
        self, 
        stock_code: str, 
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 60
    ) -> pd.DataFrame:
        """
        获取日线数据（统一入口）
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期（可选）
            end_date: 结束日期（可选，默认今天）
            days: 获取天数（当 start_date 未指定时使用）
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        if start_date is None:
            start_dt = datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days * 2)
            start_date = start_dt.strftime('%Y-%m-%d')
        
        logger.info(f"[{self.name}] 获取 {stock_code} 数据: {start_date} ~ {end_date}")
        
        try:
            raw_df = self._fetch_raw_data(stock_code, start_date, end_date)
            
            if raw_df is None or raw_df.empty:
                raise DataFetchError(f"[{self.name}] 未获取到 {stock_code} 的数据")
            
            df = self._normalize_data(raw_df, stock_code)
            df = self._clean_data(df)
            df = self._calculate_indicators(df)
            
            logger.info(f"[{self.name}] {stock_code} 获取成功，共 {len(df)} 条数据")
            return df
            
        except Exception as e:
            logger.error(f"[{self.name}] 获取 {stock_code} 失败: {str(e)}")
            raise DataFetchError(f"[{self.name}] {stock_code}: {str(e)}") from e
    
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """数据清洗"""
        df = df.copy()
        
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=['close', 'volume'])
        df = df.sort_values('date', ascending=True).reset_index(drop=True)
        
        return df
    
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        df = df.copy()
        
        # 移动平均线
        df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['ma10'] = df['close'].rolling(window=10, min_periods=1).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()
        df['ma60'] = df['close'].rolling(window=60, min_periods=1).mean()
        
        # 量比
        avg_volume_5 = df['volume'].rolling(window=5, min_periods=1).mean()
        df['volume_ratio'] = df['volume'] / avg_volume_5.shift(1)
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # 保留2位小数
        for col in ['ma5', 'ma10', 'ma20', 'ma60', 'volume_ratio', 'rsi']:
            if col in df.columns:
                df[col] = df[col].round(2)
        
        return df
    
    @staticmethod
    def random_sleep(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """智能随机休眠（防封禁）"""
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)


class DataFetcherManager:
    """
    数据源策略管理器
    
    职责：
    1. 管理多个数据源（按优先级排序）
    2. 根据市场类型选择合适的数据源
    3. 自动故障切换（Failover）
    """
    
    def __init__(self, fetchers: Optional[List[BaseFetcher]] = None):
        self._fetchers: List[BaseFetcher] = []
        
        if fetchers:
            self._fetchers = sorted(fetchers, key=lambda f: f.priority)
        else:
            self._init_default_fetchers()
    
    def _init_default_fetchers(self) -> None:
        """初始化默认数据源列表"""
        from .akshare_fetcher import AkshareFetcher
        from .efinance_fetcher import EfinanceFetcher
        from .yfinance_fetcher import YfinanceFetcher
        
        self._fetchers = [
            AkshareFetcher(),
            EfinanceFetcher(),
            YfinanceFetcher(),
        ]

        # Optional: Tengu FIRM (US equities + fundamentals/filings/insider/13F/
        # congressional). Opt-in — only activates when a TENGU_API_KEY is present,
        # so default behavior is unchanged. Free key: https://tengu.co/api
        if os.getenv("TENGU_API_KEY") or os.getenv("FIRM_API_KEY"):
            from .tengu_fetcher import TenguFetcher
            self._fetchers.append(TenguFetcher())

        self._fetchers.sort(key=lambda f: f.priority)
        logger.info(f"已初始化 {len(self._fetchers)} 个数据源: " + 
                   ", ".join([f.name for f in self._fetchers]))
    
    def get_daily_data(
        self, 
        stock_code: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        days: int = 60
    ) -> Tuple[pd.DataFrame, str]:
        """
        获取日线数据（自动选择数据源和故障切换）
        
        Returns:
            Tuple[DataFrame, str]: (数据, 成功的数据源名称)
        """
        market_type = detect_market_type(stock_code)
        logger.info(f"检测到市场类型: {market_type.value} for {stock_code}")
        
        # 按市场类型过滤数据源
        suitable_fetchers = [
            f for f in self._fetchers 
            if f.supports_market(market_type)
        ]
        
        if not suitable_fetchers:
            # 如果没有专门支持的，使用所有数据源尝试
            suitable_fetchers = self._fetchers
        
        errors = []
        for fetcher in suitable_fetchers:
            try:
                logger.info(f"尝试使用 [{fetcher.name}] 获取 {stock_code}...")
                df = fetcher.get_daily_data(
                    stock_code=stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    days=days
                )
                
                if df is not None and not df.empty:
                    return df, fetcher.name
                    
            except Exception as e:
                error_msg = f"[{fetcher.name}] 失败: {str(e)}"
                logger.warning(error_msg)
                errors.append(error_msg)
                continue
        
        error_summary = f"所有数据源获取 {stock_code} 失败:\n" + "\n".join(errors)
        raise DataFetchError(error_summary)
    
    @property
    def available_fetchers(self) -> List[str]:
        """返回可用数据源名称列表"""
        return [f.name for f in self._fetchers]

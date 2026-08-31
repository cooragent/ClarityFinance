#!/usr/bin/env python3
"""FastAPI interface for the Financial Intelligence Agent.

This module provides RESTful API endpoints for all agent functionalities.
"""

import json
import logging
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
try:
    from dotenv import load_dotenv
    env_paths = [
        Path(__file__).parent / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            break
    else:
        load_dotenv()
except ImportError:
    pass

from clarity.core import (
    AgentConfig,
    FinancialAgentOrchestrator,
    TaskType,
)
from clarity.core.tools.dashboard_scanner import DashboardScanner
from clarity.core.tools.backtest_tools import run_backtest
from clarity.core.tools.featured_portfolios import follow_featured_portfolio, get_featured_portfolios
from clarity.core.tools.hotspot_tools import find_related_stocks, get_today_hotspots
from clarity.core.tools.my_holdings import (
    add_watchlist,
    buy_virtual_capital,
    holdings_performance,
    holdings_snapshot,
    invest_capital,
    remove_holding,
    set_position,
)
from clarity.core.tools.portfolio_evolution import _atomic_json, _read_json, _state_exists, create_portfolio, continue_portfolio
from clarity.core.vibe_client import VibeTradingClient
from clarity.core.notification import NotificationService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
HOTSPOTS_CACHE_FILE = RUNTIME_DIR / "latest_hotspots.json"
DASHBOARD_CACHE_FILE = RUNTIME_DIR / "latest_dashboard.json"
HOTSPOTS_CACHE_LIMIT = 100
HOTSPOTS_CACHE_VERSION = 2

# FastAPI app
app = FastAPI(
    title="Financial Intelligence Agent API",
    description="RESTful API for stock analysis, holdings tracking, screening, and dashboard",
    version="1.0.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Pydantic Models ====================

class ModelSelection(BaseModel):
    """Model selection configuration"""
    provider: str = Field(default="openai", description="LLM provider (openai or qwen)")


class AnalyzeRequest(BaseModel):
    """Request model for stock analysis"""
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    trade_date: Optional[str] = Field(None, description="Trade date in YYYY-MM-DD format")
    model: Optional[str] = Field("openai", description="LLM provider (openai or qwen)")


class TrackRequest(BaseModel):
    """Request model for holdings tracking"""
    investor_name: str = Field(..., description="Investor name (e.g., Warren Buffett)")
    trade_date: Optional[str] = Field(None, description="Trade date in YYYY-MM-DD format")
    model: Optional[str] = Field("openai", description="LLM provider (openai or qwen)")


class ScreenRequest(BaseModel):
    """Request model for stock screening"""
    criteria: str = Field(..., description="Screening criteria (e.g., high dividend yield)")
    trade_date: Optional[str] = Field(None, description="Trade date in YYYY-MM-DD format")
    model: Optional[str] = Field("openai", description="LLM provider (openai or qwen)")


class AskRequest(BaseModel):
    """Request model for natural language query"""
    query: str = Field(..., description="Natural language query")
    model: Optional[str] = Field("openai", description="LLM provider (openai or qwen)")


class DashboardRequest(BaseModel):
    """Request model for dashboard scan"""
    markets: Optional[List[str]] = Field(["A股", "美股"], description="Markets to scan")
    top_n: int = Field(10, description="Number of top stocks to recommend")
    push: bool = Field(False, description="Push report to notification channels")
    push_channels: Optional[List[str]] = Field(None, description="Specific channels to push to")


class HotspotStocksRequest(BaseModel):
    """Request model for finding stocks related to a hotspot."""
    title: str = Field(..., min_length=1, description="Hotspot event title")
    limit: int = Field(8, ge=1, le=20, description="Maximum number of stocks")


class PortfolioCreateRequest(BaseModel):
    profile: str = Field(..., min_length=1, max_length=40)
    markets: List[str] = Field(default=["美股"])
    sectors: List[str] = Field(default=["科技", "消费"])
    risk: str = Field(default="均衡")
    portfolio_size: int = Field(default=5, ge=2, le=20)
    target_return_pct: float = Field(default=12, gt=0, le=200)
    max_drawdown_pct: float = Field(default=20, gt=0, le=100)
    trading_cost_pct: float = Field(default=0.15, ge=0, le=10)
    start: str
    end: str
    rounds: int = Field(default=3, ge=0, le=20)
    custom_tickers: str = ""


class PortfolioContinueRequest(BaseModel):
    rounds: int = Field(default=3, ge=1, le=20)
    end: Optional[str] = None


class FeaturedFollowRequest(BaseModel):
    profile_prefix: str = Field(default="Follow", min_length=1, max_length=20)
    risk: str = Field(default="均衡")
    portfolio_size: int = Field(default=5, ge=2, le=20)
    target_return_pct: float = Field(default=12, gt=0, le=200)
    max_drawdown_pct: float = Field(default=20, gt=0, le=100)
    trading_cost_pct: float = Field(default=0.15, ge=0, le=10)
    years: int = Field(default=3, ge=1, le=20)
    rounds: int = Field(default=3, ge=1, le=20)
    end: Optional[str] = None
    capital_usd: float = Field(default=100_000, gt=0)


class HoldingRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=15)
    name: str = Field(default="", max_length=100)
    quantity: Optional[float] = Field(default=None, ge=0)
    avg_cost: Optional[float] = Field(default=None, ge=0)


class CapitalInvestmentRequest(BaseModel):
    capital_usd: float = Field(..., gt=0)
    name: str = Field(default="", max_length=100)


class VirtualCapitalRequest(BaseModel):
    packs: int = Field(default=1, ge=1, le=100)


class BacktestRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=15)
    start: str
    end: str
    fast: int = Field(default=20, ge=2, le=500)
    slow: int = Field(default=60, ge=3, le=1000)
    initial_cash: float = Field(default=100000, gt=0)
    commission_pct: float = Field(default=0.1, ge=0, le=10)
    slippage_pct: float = Field(default=0.05, ge=0, le=10)


class VibeSessionRequest(BaseModel):
    title: str = Field(default="Clarity 量化研究", min_length=1, max_length=100)


class VibeMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=20000)


class TaskResponse(BaseModel):
    """Response model for async tasks"""
    success: bool
    task_id: Optional[str] = None
    message: str
    data: Optional[Dict[str, Any]] = None


class AnalysisResult(BaseModel):
    """Response model for analysis results"""
    success: bool
    task_type: str
    target: str
    trade_date: str
    report: Optional[str] = None
    execution_summary: Optional[Dict[str, Any]] = None
    files: Optional[Dict[str, str]] = None
    error: Optional[str] = None


class DashboardResult(BaseModel):
    """Response model for dashboard results"""
    success: bool
    date: str
    market_overviews: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    summary: str
    markdown: Optional[str] = None
    notification_sent: bool = False


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    timestamp: str
    version: str


# ==================== Helper Functions ====================

def _apply_model_selection(model: str) -> None:
    """Apply LLM model selection"""
    selected = (model or "openai").lower()

    if selected == "openai":
        os.environ["LLM_PROVIDER"] = "openai"
        os.environ["LLM_BACKEND_URL"] = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        openai_model = os.getenv("OPENAI_MODEL")
        openai_deep_model = os.getenv("OPENAI_DEEP_MODEL")
        if openai_model:
            os.environ["QUICK_THINK_LLM"] = openai_model
        if openai_deep_model:
            os.environ["DEEP_THINK_LLM"] = openai_deep_model
    elif selected == "qwen":
        os.environ["LLM_PROVIDER"] = "qwen"
        os.environ["LLM_BACKEND_URL"] = os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        qwen_model = os.getenv("QWEN_MODEL", "qwen-latest")
        qwen_deep_model = os.getenv("QWEN_DEEP_MODEL", qwen_model)
        os.environ["QUICK_THINK_LLM"] = qwen_model
        os.environ["DEEP_THINK_LLM"] = qwen_deep_model

        qwen_api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        openai_api_key = os.getenv("OPENAI_API_KEY", "")
        if qwen_api_key and (not openai_api_key or openai_api_key.startswith("your_")):
            os.environ["OPENAI_API_KEY"] = qwen_api_key

    try:
        from clarity.dataflows.config import reload_config_from_env
        reload_config_from_env()
    except Exception:
        pass


def _generate_dashboard_markdown(result: dict) -> str:
    """Generate beautiful markdown report from dashboard scan result."""
    lines = []
    date = result.get("date", datetime.now().strftime("%Y-%m-%d"))

    # Header
    lines.append(f"# 📊 每日决策仪表盘")
    lines.append(f"> 生成时间: {date} {datetime.now().strftime('%H:%M:%S')}")
    lines.append("")

    # Market Overview
    lines.append("## 🌐 市场概览")
    lines.append("")

    overviews = result.get("market_overviews", [])
    if overviews:
        lines.append("| 市场 | 指数 | 点位 | 涨跌幅 | 上涨家数 | 下跌家数 | 成交额(亿) |")
        lines.append("|:----:|:----:|-----:|-------:|---------:|---------:|-----------:|")
        for ov in overviews:
            if isinstance(ov, dict):
                market = ov.get("market_type", "-")
                index_name = ov.get("index_name", "-")
                index_value = ov.get("index_value", 0)
                change = ov.get("index_change_pct", 0)
                up = ov.get("up_count", 0)
                down = ov.get("down_count", 0)
                amount = ov.get("total_amount", 0)
                change_emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
                lines.append(
                    f"| {market} | {index_name} | {index_value:,.2f} | "
                    f"{change_emoji} {change:+.2f}% | {up} | {down} | {amount:,.1f} |"
                )
    else:
        lines.append("_暂无市场数据_")

    lines.append("")

    # Top Recommendations
    lines.append("## 🏆 今日值得关注")
    lines.append("")

    recommendations = result.get("recommendations", [])
    if recommendations:
        lines.append("| 排名 | 代码 | 名称 | 市场 | 现价 | 涨跌幅 | 评分 | 信号 | 推荐理由 |")
        lines.append("|:----:|:----:|:----:|:----:|-----:|-------:|:----:|:----:|:---------|")

        for i, rec in enumerate(recommendations, 1):
            code = rec.get("code", "-")
            name = rec.get("name", "-")
            market = rec.get("market", "-")
            price = rec.get("current_price", 0)
            change = rec.get("change_pct", 0)
            score = rec.get("score", 0)
            signal = rec.get("signal", "-")
            reasons = rec.get("reasons", [])

            # Signal emoji
            signal_map = {
                "极具潜力": "🚀",
                "值得关注": "📈",
                "观望": "⏸️",
                "谨慎对待": "📉",
                "风险较高": "🔻",
            }
            signal_emoji = signal_map.get(signal, "❓")

            # Score color
            if score >= 80:
                score_display = f"**{score}**"
            elif score >= 60:
                score_display = f"{score}"
            else:
                score_display = f"_{score}_"

            # Change emoji
            change_emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"

            # Reasons (first 2)
            reason_text = "; ".join(reasons[:2]) if reasons else "-"

            lines.append(
                f"| {i} | `{code}` | {name} | {market} | "
                f"{price:.2f} | {change_emoji} {change:+.2f}% | "
                f"{score_display} | {signal_emoji} {signal} | {reason_text} |"
            )
    else:
        lines.append("_暂无推荐股票_")

    lines.append("")

    # Summary
    summary = result.get("summary", "")
    if summary:
        lines.append("## 📝 市场总结")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*本报告由 Clarity 金融智能体自动生成，仅供参考，不构成投资建议。*")
    lines.append("")

    return "\n".join(lines)


def _dashboard_rows(values: list[Any]) -> list[dict[str, Any]]:
    """Normalize scanner dataclasses at the HTTP boundary."""
    return [asdict(value) if is_dataclass(value) else value for value in values]


# ==================== API Endpoints ====================

@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - Health check"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0"
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0"
    )


@app.get("/api/v1/hotspots")
async def today_hotspots(limit: int = Query(10, ge=1, le=100), refresh: bool = Query(False)):
    """Get today's top news events."""
    try:
        result = _read_json(HOTSPOTS_CACHE_FILE, {}) if _state_exists(HOTSPOTS_CACHE_FILE) else {}
        if refresh or result.get("date") != datetime.now().strftime("%Y-%m-%d") or result.get("cache_limit") != HOTSPOTS_CACHE_LIMIT or result.get("cache_version") != HOTSPOTS_CACHE_VERSION:
            result = await get_today_hotspots(HOTSPOTS_CACHE_LIMIT)
            result["cache_limit"] = HOTSPOTS_CACHE_LIMIT
            result["cache_version"] = HOTSPOTS_CACHE_VERSION
            _atomic_json(HOTSPOTS_CACHE_FILE, result)
        hotspots = result.get("hotspots", [])
        return {**result, "hotspots": hotspots[:limit], "has_more": len(hotspots) > limit}
    except Exception as e:
        logger.error("Error loading today's hotspots: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/v1/hotspots/stocks")
async def hotspot_stocks(request: HotspotStocksRequest):
    """Find stocks related to one hotspot event."""
    try:
        return await find_related_stocks(request.title, request.limit)
    except Exception as e:
        logger.error("Error searching hotspot stocks: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


def _json_portfolio(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: json.loads(value.to_json(orient="records", date_format="iso")) if hasattr(value, "to_json") else value
        for key, value in result.items()
    }


@app.post("/api/v1/portfolio/evolve")
async def create_evolving_portfolio(request: PortfolioCreateRequest):
    """Create a preference profile, baseline it, then test bounded Candidates."""
    try:
        return _json_portfolio(create_portfolio(**request.model_dump()))
    except Exception as e:
        logger.error("Error creating evolving portfolio: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/portfolio/evolve/{profile}")
async def continue_evolving_portfolio(profile: str, request: PortfolioContinueRequest):
    """Refresh market data and continue the saved portfolio evolution loop."""
    try:
        return _json_portfolio(continue_portfolio(profile, request.rounds, request.end))
    except Exception as e:
        logger.error("Error continuing portfolio evolution: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/portfolio/featured")
async def featured_portfolios():
    """List the ten public portfolios shown by default in the UI."""
    return get_featured_portfolios()


@app.post("/api/v1/portfolio/featured/{featured_id}/follow")
async def follow_public_portfolio(featured_id: str, request: FeaturedFollowRequest):
    """Seed or continue a self-evolving portfolio from public holdings."""
    try:
        return _json_portfolio(follow_featured_portfolio(featured_id, **request.model_dump()))
    except Exception as e:
        logger.error("Error following featured portfolio: %s", e, exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/holdings")
async def my_holdings():
    """Return saved positions with current quotes and P&L."""
    return holdings_snapshot()


@app.get("/api/v1/holdings/performance")
async def my_holdings_performance(days: int = Query(90, ge=7, le=365)):
    """Return daily portfolio return series for the current positions."""
    return holdings_performance(days)


@app.post("/api/v1/holdings")
async def save_holding(request: HoldingRequest):
    """Add a symbol to the watchlist or update a manually entered position."""
    try:
        if request.quantity is None and request.avg_cost is None:
            add_watchlist(request.ticker, request.name)
        elif request.quantity is None or request.avg_cost is None:
            raise ValueError("数量和平均成本必须同时填写")
        else:
            set_position(request.ticker, request.quantity, request.avg_cost, request.name)
        return holdings_snapshot()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/holdings/{ticker}/invest")
async def invest_in_holding(ticker: str, request: CapitalInvestmentRequest):
    """Increase one simulated position using available USD capital."""
    try:
        return invest_capital(ticker, request.capital_usd, request.name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/account/virtual-capital")
async def purchase_virtual_capital(request: VirtualCapitalRequest):
    """Buy $1m of simulated capital for each virtual $10 pack."""
    try:
        return buy_virtual_capital(request.packs)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/v1/holdings/{ticker}")
async def delete_holding(ticker: str):
    """Remove a symbol from My Holdings."""
    try:
        return {"holdings": remove_holding(ticker)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/backtest")
async def backtest(request: BacktestRequest):
    """Run the built-in moving-average strategy."""
    try:
        return _json_portfolio(run_backtest(**request.model_dump()))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/vibe/status")
async def vibe_status():
    """Report whether the separately running Vibe-Trading kernel is reachable."""
    client = VibeTradingClient()
    try:
        return await client.status()
    except Exception as e:
        return {"connected": False, "url": client.base_url, "error": str(e)}


@app.post("/api/v1/vibe/sessions")
async def create_vibe_session(request: VibeSessionRequest):
    try:
        return await VibeTradingClient().create_session(request.title)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vibe-Trading 不可用：{e}")


@app.post("/api/v1/vibe/sessions/{session_id}/messages")
async def send_vibe_message(session_id: str, request: VibeMessageRequest):
    try:
        return await VibeTradingClient().send_message(session_id, request.content)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vibe-Trading 请求失败：{e}")


@app.get("/api/v1/vibe/sessions/{session_id}/messages")
async def get_vibe_messages(session_id: str):
    try:
        return await VibeTradingClient().messages(session_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vibe-Trading 请求失败：{e}")


@app.get("/api/v1/vibe/sessions/{session_id}/events")
async def vibe_session_events(session_id: str):
    async def proxy():
        try:
            async for chunk in VibeTradingClient().events(session_id):
                yield chunk
        except Exception as exc:
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n".encode()

    return StreamingResponse(proxy(), media_type="text/event-stream")


@app.post("/api/v1/analyze", response_model=AnalysisResult)
async def analyze_stock(request: AnalyzeRequest):
    """
    Analyze a stock

    - **ticker**: Stock ticker symbol (e.g., AAPL, TSLA)
    - **trade_date**: Optional trade date in YYYY-MM-DD format
    - **model**: LLM provider (openai or qwen)
    """
    try:
        _apply_model_selection(request.model)

        config = AgentConfig(llm_provider=os.getenv("LLM_PROVIDER", "openai"))
        orchestrator = FinancialAgentOrchestrator(config)

        trade_date = request.trade_date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Analyzing stock: {request.ticker}, date: {trade_date}")

        result = await orchestrator.run(
            task_type=TaskType.STOCK_ANALYSIS,
            target=request.ticker,
            trade_date=trade_date,
        )

        return AnalysisResult(
            success=result.get("success", False),
            task_type="STOCK_ANALYSIS",
            target=request.ticker,
            trade_date=trade_date,
            report=result.get("report"),
            execution_summary=result.get("execution_summary"),
            files=result.get("files"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Error analyzing stock: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/track", response_model=AnalysisResult)
async def track_investor(request: TrackRequest):
    """
    Track an investor's holdings

    - **investor_name**: Investor name (e.g., Warren Buffett)
    - **trade_date**: Optional trade date in YYYY-MM-DD format
    - **model**: LLM provider (openai or qwen)
    """
    try:
        _apply_model_selection(request.model)

        config = AgentConfig(llm_provider=os.getenv("LLM_PROVIDER", "openai"))
        orchestrator = FinancialAgentOrchestrator(config)

        trade_date = request.trade_date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Tracking investor: {request.investor_name}, date: {trade_date}")

        result = await orchestrator.run(
            task_type=TaskType.HOLDINGS_TRACKING,
            target=request.investor_name,
            trade_date=trade_date,
        )

        return AnalysisResult(
            success=result.get("success", False),
            task_type="HOLDINGS_TRACKING",
            target=request.investor_name,
            trade_date=trade_date,
            report=result.get("report"),
            execution_summary=result.get("execution_summary"),
            files=result.get("files"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Error tracking investor: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/screen", response_model=AnalysisResult)
async def screen_stocks(request: ScreenRequest):
    """
    Screen stocks based on criteria

    - **criteria**: Screening criteria (e.g., high dividend yield tech stocks)
    - **trade_date**: Optional trade date in YYYY-MM-DD format
    - **model**: LLM provider (openai or qwen)
    """
    try:
        _apply_model_selection(request.model)

        config = AgentConfig(llm_provider=os.getenv("LLM_PROVIDER", "openai"))
        orchestrator = FinancialAgentOrchestrator(config)

        trade_date = request.trade_date or datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Screening stocks: {request.criteria}, date: {trade_date}")

        result = await orchestrator.run(
            task_type=TaskType.STOCK_SCREENING,
            target=request.criteria,
            trade_date=trade_date,
        )

        return AnalysisResult(
            success=result.get("success", False),
            task_type="STOCK_SCREENING",
            target=request.criteria,
            trade_date=trade_date,
            report=result.get("report"),
            execution_summary=result.get("execution_summary"),
            files=result.get("files"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Error screening stocks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/ask", response_model=AnalysisResult)
async def ask_query(request: AskRequest):
    """
    Process a natural language query

    - **query**: Natural language query (e.g., 分析一下苹果公司的股票)
    - **model**: LLM provider (openai or qwen)
    """
    try:
        _apply_model_selection(request.model)

        config = AgentConfig(llm_provider=os.getenv("LLM_PROVIDER", "openai"))
        orchestrator = FinancialAgentOrchestrator(config)

        logger.info(f"Processing query: {request.query}")

        result = await orchestrator.run_from_natural_language(request.query)

        return AnalysisResult(
            success=result.get("success", False),
            task_type="NATURAL_LANGUAGE",
            target=request.query,
            trade_date=datetime.now().strftime("%Y-%m-%d"),
            report=result.get("report"),
            execution_summary=result.get("execution_summary"),
            files=result.get("files"),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/dashboard", response_model=DashboardResult)
async def run_dashboard(request: DashboardRequest, background_tasks: BackgroundTasks):
    """
    Run daily dashboard scan

    - **markets**: Markets to scan (default: ["A股", "美股"])
    - **top_n**: Number of top stocks to recommend (default: 10)
    - **push**: Push report to notification channels (default: False)
    - **push_channels**: Specific channels to push to (optional)
    """
    try:
        logger.info(f"Running dashboard scan for markets: {request.markets}, top_n: {request.top_n}")

        scanner = DashboardScanner()
        result = scanner.scan_market(markets=request.markets, top_n=request.top_n)
        result["market_overviews"] = _dashboard_rows(result.get("market_overviews", []))
        result["recommendations"] = _dashboard_rows(result.get("recommendations", []))

        # Generate markdown report
        markdown = _generate_dashboard_markdown(result)
        result["markdown"] = markdown

        # Save to file
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        default_file = RUNTIME_DIR / f"dashboard_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        default_file.write_text(markdown, encoding="utf-8")

        logger.info(f"Dashboard report saved to: {default_file}")

        # Push notification in background if requested
        notification_sent = False
        if request.push:
            def send_notification():
                notification = NotificationService()
                if not notification.is_available():
                    logger.warning("No notification channels configured")
                    return False

                if request.push_channels:
                    success = False
                    for channel_name in request.push_channels:
                        channel_lower = channel_name.lower()
                        if "wechat" in channel_lower or "微信" in channel_lower:
                            success = notification.send_to_wechat(markdown) or success
                        elif "feishu" in channel_lower or "飞书" in channel_lower:
                            success = notification.send_to_feishu(markdown) or success
                        elif "telegram" in channel_lower:
                            success = notification.send_to_telegram(markdown) or success
                        elif "email" in channel_lower or "邮件" in channel_lower:
                            success = notification.send_to_email(markdown) or success
                        elif "pushover" in channel_lower:
                            success = notification.send_to_pushover(markdown) or success
                        elif "custom" in channel_lower or "webhook" in channel_lower:
                            success = notification.send_to_custom(markdown) or success
                    return success
                else:
                    return notification.send(markdown)

            background_tasks.add_task(send_notification)
            notification_sent = True

        response = DashboardResult(
            success=True,
            date=result.get("date", datetime.now().strftime("%Y-%m-%d")),
            market_overviews=result.get("market_overviews", []),
            recommendations=result.get("recommendations", []),
            summary=result.get("summary", ""),
            markdown=markdown,
            notification_sent=notification_sent,
        )
        _atomic_json(DASHBOARD_CACHE_FILE, response.model_dump(mode="json"))
        return response
    except Exception as e:
        logger.error(f"Error running dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/dashboard/latest")
async def latest_dashboard():
    """Return the most recently completed dashboard scan."""
    if _state_exists(DASHBOARD_CACHE_FILE):
        return _read_json(DASHBOARD_CACHE_FILE, {})
    reports = sorted(RUNTIME_DIR.glob("dashboard_*.md"), reverse=True)
    return {"markdown": reports[0].read_text(encoding="utf-8")} if reports else {}


@app.get("/api/v1/notification/channels")
async def get_notification_channels():
    """Get configured notification channels"""
    try:
        notification = NotificationService()
        return {
            "available": notification.is_available(),
            "channels": notification.get_channel_names(),
        }
    except Exception as e:
        logger.error(f"Error getting notification channels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


frontend_dist = Path(__file__).parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/app", StaticFiles(directory=frontend_dist, html=True), name="react-app")


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn

    # Default to port 8000
    port = int(os.getenv("API_PORT", "8000"))
    host = os.getenv("API_HOST", "0.0.0.0")

    uvicorn.run(
        "api:app",
        host=host,
        port=port,
        reload=True,
        log_level="info",
    )

#!/usr/bin/env python3
"""
Clarity Web UI - 金融分析智能体 Web 界面

基于 Gradio 构建的现代化 Web 界面，支持：
- 股票分析
- 持仓跟踪
- 股票筛选
- 自然语言查询
- 决策仪表盘
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

# Bypass proxy for localhost (fix Gradio startup issue)
os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except (ImportError, PermissionError, OSError):
    pass

import gradio as gr
import pandas as pd

from clarity.core import (
    AgentConfig,
    FinancialAgentOrchestrator,
    TaskType,
)
from clarity.core.tools.dashboard_scanner import DashboardScanner
from clarity.core.tools.backtest_tools import run_backtest
from clarity.core.tools.featured_portfolios import (
    FEATURED_PORTFOLIOS,
    follow_featured_portfolio,
    get_featured_portfolios,
)
from clarity.core.tools.hotspot_tools import find_related_stocks, get_today_hotspots
from clarity.core.tools.my_holdings import add_holdings, holdings_snapshot, remove_holding, set_position
from clarity.core.tools.portfolio_evolution import create_portfolio, continue_portfolio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global orchestrator instance
_orchestrator = None


def get_orchestrator():
    """Get or create orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        config = AgentConfig()
        _orchestrator = FinancialAgentOrchestrator(config)
    return _orchestrator


# ========== 今日热点 ==========

def load_today_hotspots():
    """Load and format today's top 10 events."""
    try:
        result = asyncio.run(get_today_hotspots())
        hotspots = result["hotspots"]
        lines = [
            "# 🔥 今日 10 大热点事件",
            "",
            f"> 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for item in hotspots:
            title = str(item["title"]).replace("|", "\\|")
            link = item.get("link", "")
            lines.append(f"## {item['rank']}. [{title}]({link})")
            lines.append(f"> {item.get('source') or '未知来源'} · {item.get('published') or '时间未知'}")
            if item.get("summary"):
                lines.append(str(item["summary"]))
            lines.append("")

        updates = [
            gr.update(value=f"{i + 1}. {item['title'][:22]}", visible=i < len(hotspots))
            if i < len(hotspots) else gr.update(visible=False)
            for i, item in enumerate((hotspots + [{}] * 10)[:10])
        ]
        return "\n".join(lines), hotspots, *updates
    except Exception as exc:
        logger.error("Error loading today's hotspots: %s", exc, exc_info=True)
        return f"❌ 热点获取失败：{exc}", [], *[gr.update(visible=False) for _ in range(10)]


def search_hotspot_stocks(hotspots: list, index: int):
    """Find stocks for one hotspot selected by its button."""
    if index >= len(hotspots):
        return "请先刷新今日热点。", {}, *[gr.update(visible=False) for _ in range(8)]
    event = hotspots[index]
    try:
        result = asyncio.run(find_related_stocks(str(event["title"])))
        lines = [f"# 📈 相关股票：{result['event']}", ""]
        if result["stocks"]:
            lines += [
                "| 代码 | 名称 | 市场 | 关联线索 |",
                "|:---:|:---|:---:|:---|",
            ]
            for stock in result["stocks"]:
                relation = stock["relation"].replace("|", "\\|")
                lines.append(
                    f"| `{stock['symbol']}` | {stock['name']} | {stock['market']} | {relation} |"
                )
        else:
            lines.append("暂未检索到明确关联的上市公司。")

        if result["news"]:
            lines += ["", "## 关联财经报道", ""]
            for item in result["news"]:
                lines.append(f"- [{item['title']}]({item['link']}) — {item['publisher']}")
        lines += ["", "*搜索相关性不代表投资建议，请核实事件与公司的实际业务关联。*"]
        updates = [
            gr.update(value=f"＋ 加入持仓 {stock['symbol']}", visible=True)
            if i < len(result["stocks"]) else gr.update(visible=False)
            for i, stock in enumerate((result["stocks"] + [{}] * 8)[:8])
        ]
        return "\n".join(lines), result, *updates
    except Exception as exc:
        logger.error("Error searching stocks for hotspot: %s", exc, exc_info=True)
        return f"❌ 相关股票搜索失败：{exc}", {}, *[gr.update(visible=False) for _ in range(8)]


def add_hotspot_stock(result: dict, index: int):
    stocks = result.get("stocks", []) if result else []
    if index >= len(stocks):
        return "请先搜索相关股票。"
    stock = stocks[index]
    add_holdings([stock], "今日热点", str(result.get("event", "")))
    return f"✅ `{stock['symbol']}` 已加入“我的持仓”（数量未知，标记为待建仓）。"


def quick_add_holding(ticker: str, source: str = "股票分析"):
    try:
        add_holdings([{"ticker": ticker}], source)
        return f"✅ `{ticker.strip().upper()}` 已加入“我的持仓”（数量未知，标记为待建仓）。"
    except Exception as exc:
        return f"❌ 加入失败：{exc}"


# ========== 策略回测 ==========

def backtest_strategy(ticker, start, end, fast, slow, cash, commission, slippage):
    """Run the built-in moving-average strategy and format its results."""
    try:
        result = run_backtest(
            ticker.strip().upper(),
            start,
            end,
            fast=int(fast),
            slow=int(slow),
            initial_cash=float(cash),
            commission_pct=float(commission),
            slippage_pct=float(slippage),
        )
        summary = f"""# 🧪 {result['ticker']} 策略回测

> {result['start']} 至 {result['end']} · 数据源：{result['data_source']}

| 指标 | 结果 | 指标 | 结果 |
|:---|---:|:---|---:|
| 策略收益 | **{result['total_return_pct']:+.2f}%** | 买入持有 | {result['benchmark_return_pct']:+.2f}% |
| 期末资产 | {result['final_value']:,.2f} | 最大回撤 | {result['max_drawdown_pct']:.2f}% |
| 夏普率 | {result['sharpe']:.2f} | 胜率 | {result['win_rate_pct']:.1f}% |
| 已平仓交易 | {result['closed_trades']} | 初始资金 | {result['initial_cash']:,.2f} |

*金叉后下一交易日开盘买入，死叉后下一交易日开盘清仓；结果仅供策略验证。*
"""
        return summary, result["curve"], result["orders"]
    except Exception as exc:
        logger.error("Backtest failed: %s", exc, exc_info=True)
        return f"❌ 回测失败：{exc}", None, None


# ========== 自演进组合 ==========

def _format_portfolio_evolution(result):
    metrics = result["metrics"]
    benchmark = result["benchmark_metrics"]
    params = result["params"]
    summary = f"""# 🧬 {result['profile']} · V{result['version']}

> 偏好评分：**{result['score']:.2f}/100** · 股票池：{len(result['universe'])} 只

| 指标 | 策略组合 | 等权基准 |
|:---|---:|---:|
| 年化收益 | **{metrics['annual_return'] * 100:+.2f}%** | {benchmark['annual_return'] * 100:+.2f}% |
| 总收益 | {metrics['total_return'] * 100:+.2f}% | {benchmark['total_return'] * 100:+.2f}% |
| 最大回撤 | {metrics['max_drawdown'] * 100:.2f}% | {benchmark['max_drawdown'] * 100:.2f}% |
| 夏普率 | {metrics['sharpe']:.2f} | {benchmark['sharpe']:.2f} |

**当前策略：** 动量 {params['momentum_days']} 日 · 波动率 {params['volatility_days']} 日 · 每 {params['rebalance_days']} 日再平衡 · 现金缓冲 {params['cash_buffer'] * 100:.0f}%

*仅当固定验证集上的偏好评分严格提高时，新候选才晋级；不构成投资建议。*
"""
    portfolio = pd.DataFrame(
        [{"股票": item["ticker"], "目标权重": f"{item['weight'] * 100:.2f}%"} for item in result["portfolio"]]
    )
    history = result["history"]
    if not history.empty:
        history = history[["time", "version", "score", "annual_return_pct", "max_drawdown_pct", "decision"]].rename(
            columns={"time": "时间", "version": "版本", "score": "评分", "annual_return_pct": "年化收益%", "max_drawdown_pct": "最大回撤%", "decision": "决策"}
        )
    return summary, portfolio, result["curve"], history


def create_evolving_portfolio(profile, markets, sectors, risk, size, target, drawdown, cost, years, rounds, custom):
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=int(years * 365))).strftime("%Y-%m-%d")
        result = create_portfolio(
            profile, markets, sectors, risk, int(size), float(target), float(drawdown),
            float(cost), start, end, int(rounds), custom,
        )
        return _format_portfolio_evolution(result)
    except Exception as exc:
        logger.error("Portfolio creation failed: %s", exc, exc_info=True)
        return f"❌ 组合创建失败：{exc}", None, None, None


def continue_evolving_portfolio(profile, rounds):
    try:
        return _format_portfolio_evolution(continue_portfolio(profile, int(rounds)))
    except Exception as exc:
        logger.error("Portfolio evolution failed: %s", exc, exc_info=True)
        return f"❌ 继续演进失败：{exc}", None, None, None


def follow_featured(featured_id, profile, risk, size, target, drawdown, cost, years, rounds):
    try:
        result = follow_featured_portfolio(
            featured_id, profile, risk, int(size), float(target), float(drawdown),
            float(cost), int(years), int(rounds),
        )
        source = result["source_holdings"]
        holdings = pd.DataFrame(
            [{"股票": item["ticker"], "名称": item["name"], "披露权重": f"{item['weight_pct']:.2f}%", "最新动作": item["activity"]} for item in source["holdings"]]
        )
        summary, portfolio, curve, history = _format_portfolio_evolution(result)
        summary = (
            f"> 已 Follow **{source['manager']}** · {source['period']} · 持仓日期 {source['portfolio_date']} · [公开来源]({source['source_url']}) · 已自动同步“我的持仓”\n\n"
            + summary
        )
        return holdings, summary, portfolio, curve, history
    except Exception as exc:
        logger.error("Following featured portfolio failed: %s", exc, exc_info=True)
        return None, f"❌ Follow 失败：{exc}", None, None, None


# ========== 我的持仓 ==========

def _holding_outputs():
    snapshot = holdings_snapshot()
    totals = snapshot["totals"]

    def total(key):
        return " · ".join(f"{currency} {values[key]:,.2f}" for currency, values in totals.items()) or "—"

    summary = f"""
<div class="holding-cards">
  <div class="holding-card"><span>持仓资产</span><strong>{snapshot['count']}</strong></div>
  <div class="holding-card"><span>当前市值</span><strong>{total('market_value')}</strong></div>
  <div class="holding-card"><span>今日盈亏</span><strong>{total('day_gain')}</strong></div>
  <div class="holding-card"><span>累计盈亏</span><strong>{total('total_gain')}</strong></div>
</div>
<small>多市场资产按原交易币种分别汇总；“待建仓”项目需录入数量和平均成本后才计入盈亏。</small>
"""
    table = pd.DataFrame(
        [
            {
                "股票": row["ticker"], "名称": row.get("name") or row["ticker"], "状态": row["status"],
                "数量": row["quantity"], "平均成本": row["avg_cost"], "最新价": row["last_price"],
                "币种": row["currency"], "市值": row["market_value"], "今日%": row["day_change_pct"],
                "累计盈亏": row["total_gain"], "收益率%": row["total_gain_pct"],
                "目标权重%": row.get("target_weight_pct"), "来源": " / ".join(row.get("sources", [])),
            }
            for row in snapshot["holdings"]
        ]
    )
    allocation = pd.DataFrame(
        [
            {
                "股票": row["ticker"],
                "权重": row["allocation_pct"] or float(row.get("target_weight_pct") or 0),
            }
            for row in snapshot["holdings"]
        ]
    )
    return summary, table, allocation


def refresh_my_holdings():
    try:
        return _holding_outputs()
    except Exception as exc:
        logger.error("Loading holdings failed: %s", exc, exc_info=True)
        return f"❌ 持仓加载失败：{exc}", None, None


def save_my_position(ticker, name, quantity, avg_cost):
    try:
        set_position(ticker, float(quantity), float(avg_cost), name)
        return "✅ 持仓已保存。", *_holding_outputs()
    except Exception as exc:
        return f"❌ 保存失败：{exc}", *refresh_my_holdings()


def delete_my_position(ticker):
    try:
        remove_holding(ticker)
        return "✅ 已从我的持仓移除。", *_holding_outputs()
    except Exception as exc:
        return f"❌ 移除失败：{exc}", *refresh_my_holdings()


# ========== 股票分析 (流式输出) ==========

def analyze_stock_streaming(ticker: str, trade_date: str = None):
    """
    Analyze a stock with streaming output.
    """
    import time
    
    if not ticker.strip():
        yield "❌ 请输入股票代码"
        return
    
    ticker = ticker.strip().upper()
    date = trade_date if trade_date else datetime.now().strftime("%Y-%m-%d")
    
    # 开始动画
    yield f"# 📈 {ticker} 股票分析\n\n"
    yield f"> 🕐 分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    yield "---\n\n"
    
    try:
        # 阶段 1: 获取数据
        yield "## ⏳ 正在分析...\n\n"
        yield f"**⠋ 正在获取 {ticker} 的历史数据...**\n\n"
        time.sleep(0.5)
        
        # 使用 DashboardScanner 进行分析
        scanner = DashboardScanner()
        
        # 检测市场类型
        from clarity.core.tools.data_provider import detect_market_type, MarketType
        market_type = detect_market_type(ticker)
        
        if market_type == MarketType.A_SHARE:
            market = "A股"
        elif market_type == MarketType.US_STOCK:
            market = "美股"
        elif market_type == MarketType.HK_STOCK:
            market = "港股"
        else:
            market = "未知"
        
        yield f"  📍 检测到市场: {market}\n"
        yield f"  📥 正在下载K线数据...\n\n"
        
        # 阶段 2: 技术分析
        yield f"**⠹ 正在计算技术指标...**\n\n"
        time.sleep(0.3)
        
        rec = scanner._analyze_stock(ticker, market)
        
        if rec is None:
            yield f"\n❌ **无法获取 {ticker} 的数据**\n\n"
            yield "可能原因：\n"
            yield "- 股票代码不正确\n"
            yield "- 数据源暂时不可用\n"
            yield "- 该股票已停牌或退市\n"
            return
        
        yield "  ✅ 均线指标 (MA5/MA10/MA20/MA60)\n"
        yield "  ✅ 动量指标 (RSI/MACD/KDJ)\n"
        yield "  ✅ 趋势指标 (ADX/BIAS)\n"
        yield "  ✅ 波动指标 (ATR)\n"
        yield "  ✅ 支撑/阻力位\n\n"
        
        # 阶段 3: 生成检查清单
        yield f"**⠼ 正在生成交易检查清单...**\n\n"
        time.sleep(0.3)
        
        cl = rec.checklist
        yield f"  📋 检查清单: ✅{cl.pass_count()} ⚠️{cl.warning_count()} ❌{cl.fail_count()}\n\n"
        
        yield "---\n\n"
        yield "## ✅ 分析完成！\n\n"
        
        # 阶段 4: 输出详细报告
        yield f"# 📈 {rec.name} (`{rec.code}`) 分析报告\n\n"
        yield f"> 市场: {rec.market} | 数据来源: {rec.data_source}\n\n"
        
        # 核心信息
        yield "## 📊 核心指标\n\n"
        yield "| 指标 | 数值 | 指标 | 数值 |\n"
        yield "|:-----|-----:|:-----|-----:|\n"
        yield f"| **现价** | ¥{rec.current_price:.2f} | **涨跌幅** | {rec.change_pct:+.2f}% |\n"
        yield f"| **评分** | {rec.score}/100 | **信号** | {rec.signal.value} |\n"
        yield f"| **乖离率** | {rec.bias:+.1f}% | **RSI** | {rec.rsi:.0f} |\n"
        yield f"| **ADX** | {rec.adx:.1f} | **量比** | {rec.volume_ratio:.2f} |\n\n"
        
        # 精确点位
        yield "## 📍 精确点位\n\n"
        yield "| 买入价 | 止损价 | 目标价 | 盈亏比 |\n"
        yield "|-------:|-------:|-------:|:------:|\n"
        yield f"| ¥{cl.entry_price:.2f} | ¥{cl.stop_loss:.2f} | ¥{cl.target_price:.2f} | {cl.risk_reward_ratio:.1f}:1 |\n\n"
        
        yield f"- **支撑位**: ¥{rec.support:.2f}\n"
        yield f"- **阻力位**: ¥{rec.resistance:.2f}\n\n"
        
        # 均线状态
        yield "## 📈 均线分析\n\n"
        if rec.ma5 > rec.ma10 > rec.ma20:
            yield "**✅ 多头排列** - MA5 > MA10 > MA20\n\n"
        elif rec.ma5 < rec.ma10 < rec.ma20:
            yield "**❌ 空头排列** - MA5 < MA10 < MA20\n\n"
        else:
            yield "**⚠️ 均线交叉** - 趋势不明朗\n\n"
        
        yield f"| MA5 | MA10 | MA20 | MA60 |\n"
        yield f"|----:|-----:|-----:|-----:|\n"
        yield f"| {rec.ma5:.2f} | {rec.ma10:.2f} | {rec.ma20:.2f} | {rec.ma60:.2f} |\n\n"
        
        # MACD
        yield "## 📊 MACD 分析\n\n"
        if rec.macd_hist > 0:
            yield f"**{'✅ 金叉向上' if rec.macd > rec.macd_signal else '⚠️ 金叉但动能减弱'}**\n\n"
        else:
            yield f"**{'❌ 死叉向下' if rec.macd < rec.macd_signal else '⚠️ 死叉但有反弹迹象'}**\n\n"
        
        yield f"- MACD: {rec.macd:.2f}\n"
        yield f"- 信号线: {rec.macd_signal:.2f}\n"
        yield f"- 柱状图: {rec.macd_hist:+.2f}\n\n"
        
        # KDJ
        yield "## 📉 KDJ 分析\n\n"
        yield f"| K | D | J |\n"
        yield f"|--:|--:|--:|\n"
        yield f"| {rec.kdj_k:.1f} | {rec.kdj_d:.1f} | {rec.kdj_j:.1f} |\n\n"
        
        if rec.kdj_k > rec.kdj_d:
            yield "**✅ KDJ 金叉**\n\n"
        else:
            yield "**❌ KDJ 死叉**\n\n"
        
        # 检查清单
        yield "## 📋 交易检查清单\n\n"
        yield "### 趋势确认\n"
        yield f"- {cl.ma_alignment} MA 排列\n"
        yield f"- {cl.macd_cross} MACD 状态\n"
        yield f"- {cl.trend_strength} 趋势强度 (ADX={rec.adx:.1f})\n"
        yield f"- {cl.price_position} 价格位置\n\n"
        
        yield "### 风险控制\n"
        yield f"- {cl.bias_check} 乖离率 ({rec.bias:+.1f}%)\n"
        yield f"- {cl.volatility_ok} 波动率\n"
        yield f"- {cl.volume_confirm} 量价配合\n"
        yield f"- {cl.stop_loss_clear} 止损清晰\n\n"
        
        yield "### 买入时机\n"
        yield f"- {cl.rsi_zone} RSI 区间 ({rec.rsi:.0f})\n"
        yield f"- {cl.kdj_signal} KDJ 信号\n"
        yield f"- {cl.support_near} 支撑位距离\n"
        yield f"- {cl.pullback_buy} 回调买入\n\n"
        
        yield "### 盈利空间\n"
        yield f"- {cl.upside_room} 上涨空间\n"
        yield f"- {cl.risk_reward} 盈亏比 ({cl.risk_reward_ratio:.1f}:1)\n\n"
        
        # 风险提示
        if abs(rec.bias) > 5:
            yield "---\n\n"
            yield f"## ⚠️ 风险提示\n\n"
            yield f"**乖离率 {rec.bias:+.1f}% 超过 5%，存在追高风险！**\n\n"
        
        # 分析要点
        yield "---\n\n"
        yield "## 📝 分析要点\n\n"
        for reason in rec.reasons:
            if reason and not reason.startswith("📍") and not reason.startswith("   "):
                yield f"- {reason}\n"
        
        yield "\n---\n\n"
        yield f"*本报告由 Clarity 金融智能体生成，仅供参考，不构成投资建议。*\n"
        
    except Exception as e:
        logger.error(f"Error analyzing {ticker}: {e}", exc_info=True)
        yield f"\n\n❌ **分析出错**: {str(e)}\n"


def analyze_stock(ticker: str, trade_date: str = None):
    """Non-streaming version for backwards compatibility."""
    result = ""
    for chunk in analyze_stock_streaming(ticker, trade_date):
        result += chunk
    return result


# ========== 持仓跟踪 (流式输出) ==========

def track_holdings_streaming(investor_name: str, trade_date: str = None):
    """Track investor holdings with streaming output."""
    import time
    
    if not investor_name.strip():
        yield "❌ 请输入投资者姓名"
        return
    
    investor = investor_name.strip()
    date = trade_date if trade_date else datetime.now().strftime("%Y-%m-%d")
    
    yield f"# 🔍 {investor} 持仓跟踪\n\n"
    yield f"> 🕐 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    yield "---\n\n"
    
    yield "## ⏳ 正在查询...\n\n"
    
    # 模拟步骤
    steps = [
        ("⠋ 搜索投资者公开持仓信息...", 1.0),
        ("⠹ 解析 SEC 13F 报告...", 0.8),
        ("⠼ 获取最新持仓变动...", 0.6),
        ("⠴ 分析持仓策略...", 0.5),
        ("⠧ 生成报告...", 0.3),
    ]
    
    for step_text, delay in steps:
        yield f"**{step_text}**\n\n"
        time.sleep(delay)
    
    try:
        orchestrator = get_orchestrator()
        
        # 使用 asyncio 运行异步函数
        async def _run():
            return await orchestrator.run(
                task_type=TaskType.HOLDINGS_TRACKING,
                target=investor,
                trade_date=date,
            )
        
        result = asyncio.run(_run())
        
        yield "---\n\n"
        
        if result.get("success"):
            report = result.get("report", "跟踪完成，但未生成报告")
            yield f"## ✅ 查询完成！\n\n"
            yield report
        else:
            error = result.get("error", "未知错误")
            yield f"## ❌ 跟踪失败\n\n{error}\n"
            
    except Exception as e:
        logger.error(f"Error tracking {investor}: {e}", exc_info=True)
        yield f"\n\n❌ **跟踪出错**: {str(e)}\n"


def track_holdings(investor_name: str, trade_date: str = None):
    """Non-streaming version."""
    result = ""
    for chunk in track_holdings_streaming(investor_name, trade_date):
        result += chunk
    return result


# ========== 股票筛选 (流式输出) ==========

def screen_stocks_streaming(criteria: str, trade_date: str = None):
    """Screen stocks with streaming output."""
    import time
    
    if not criteria.strip():
        yield "❌ 请输入筛选条件"
        return
    
    criteria = criteria.strip()
    date = trade_date if trade_date else datetime.now().strftime("%Y-%m-%d")
    
    yield f"# 🔎 股票筛选\n\n"
    yield f"> 筛选条件: **{criteria}**\n\n"
    yield f"> 🕐 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    yield "---\n\n"
    
    yield "## ⏳ 正在筛选...\n\n"
    
    # 模拟步骤
    steps = [
        ("⠋ 解析筛选条件...", 0.5),
        ("⠹ 获取股票列表...", 0.8),
        ("⠼ 应用筛选规则...", 1.0),
        ("⠴ 计算技术指标...", 0.8),
        ("⠧ 排序并生成结果...", 0.5),
    ]
    
    for step_text, delay in steps:
        yield f"**{step_text}**\n\n"
        time.sleep(delay)
    
    try:
        orchestrator = get_orchestrator()
        
        async def _run():
            return await orchestrator.run(
                task_type=TaskType.STOCK_SCREENING,
                target=criteria,
                trade_date=date,
            )
        
        result = asyncio.run(_run())
        
        yield "---\n\n"
        
        if result.get("success"):
            report = result.get("report", "筛选完成，但未生成报告")
            yield f"## ✅ 筛选完成！\n\n"
            yield report
        else:
            error = result.get("error", "未知错误")
            yield f"## ❌ 筛选失败\n\n{error}\n"
            
    except Exception as e:
        logger.error(f"Error screening stocks: {e}", exc_info=True)
        yield f"\n\n❌ **筛选出错**: {str(e)}\n"


def screen_stocks(criteria: str, trade_date: str = None):
    """Non-streaming version."""
    result = ""
    for chunk in screen_stocks_streaming(criteria, trade_date):
        result += chunk
    return result


# ========== 自然语言查询 (流式输出) ==========

def ask_query_streaming(query: str):
    """Process natural language query with streaming output."""
    import time
    
    if not query.strip():
        yield "❌ 请输入查询内容"
        return
    
    query = query.strip()
    
    yield f"# 💬 智能问答\n\n"
    yield f"> **问题**: {query}\n\n"
    yield f"> 🕐 查询时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    yield "---\n\n"
    
    yield "## ⏳ 正在思考...\n\n"
    
    # 模拟思考步骤
    steps = [
        ("⠋ 理解问题意图...", 0.5),
        ("⠹ 确定任务类型...", 0.4),
        ("⠼ 收集相关数据...", 0.8),
        ("⠴ 分析并生成回答...", 0.6),
    ]
    
    for step_text, delay in steps:
        yield f"**{step_text}**\n\n"
        time.sleep(delay)
    
    try:
        orchestrator = get_orchestrator()
        
        async def _run():
            return await orchestrator.run_from_natural_language(query)
        
        result = asyncio.run(_run())
        
        yield "---\n\n"
        
        if result.get("success"):
            report = result.get("report", "查询完成，但未生成报告")
            yield f"## ✅ 回答完成！\n\n"
            yield report
        else:
            error = result.get("error", "未知错误")
            yield f"## ❌ 查询失败\n\n{error}\n"
            
    except Exception as e:
        logger.error(f"Error processing query: {e}", exc_info=True)
        yield f"\n\n❌ **查询出错**: {str(e)}\n"


def ask_query(query: str):
    """Non-streaming version."""
    result = ""
    for chunk in ask_query_streaming(query):
        result += chunk
    return result


# ========== 决策仪表盘 (流式输出) ==========

def run_dashboard_streaming(markets: list, top_n: int = 10):
    """
    Run dashboard scan with streaming output.
    
    使用 yield 逐步输出结果，让用户看到执行进度。
    """
    import time
    
    if not markets:
        markets = ["A股", "美股"]
    
    # 动画帧
    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    
    try:
        # ===== 阶段 1: 初始化 =====
        yield "# 📊 每日决策仪表盘\n\n"
        yield f"> 🕐 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        yield "---\n\n"
        yield "## ⏳ 正在扫描...\n\n"
        
        scanner = DashboardScanner()
        
        # ===== 阶段 2: 扫描市场概览 =====
        yield "### 📡 获取市场概览\n\n"
        
        all_overviews = []
        all_candidates = []
        
        for i, market in enumerate(markets):
            # 显示当前正在扫描的市场
            yield f"**{spinner_frames[i % len(spinner_frames)]} 正在扫描 {market} 市场...**\n\n"
            time.sleep(0.3)  # 小延迟让用户看到动画
            
            try:
                if market == 'A股':
                    overview = scanner._scan_a_share()
                    yield f"  ✅ {market} 大盘数据获取成功\n"
                elif market == '美股':
                    overview = scanner._scan_us_market()
                    yield f"  ✅ {market} 大盘数据获取成功\n"
                elif market == '港股':
                    overview = scanner._scan_hk_market()
                    yield f"  ✅ {market} 大盘数据获取成功\n"
                else:
                    overview = None
                
                if overview:
                    all_overviews.append(overview)
                    # 显示概览信息
                    if hasattr(overview, 'index_name'):
                        change_emoji = "🟢" if overview.index_change_pct > 0 else "🔴" if overview.index_change_pct < 0 else "⚪"
                        yield f"  📈 {overview.index_name}: {overview.index_value:,.2f} ({change_emoji} {overview.index_change_pct:+.2f}%)\n"
                    yield "\n"
                    
            except Exception as e:
                yield f"  ⚠️ {market} 大盘获取失败: {str(e)[:50]}\n\n"
        
        yield "---\n\n"
        
        # ===== 阶段 3: 扫描个股 =====
        yield "### 🔍 扫描热门股票\n\n"
        
        for market in markets:
            yield f"**{spinner_frames[0]} 正在扫描 {market} 热门股票...**\n\n"
            
            try:
                if market == 'A股':
                    hot_stocks = scanner._get_hot_a_shares(limit=50)
                    yield f"  📋 获取到 {len(hot_stocks)} 只 A股 热门股票\n"
                    yield "  ⏳ 正在分析技术指标...\n\n"
                    
                    # 进度条模拟
                    analyzed = 0
                    for j, code in enumerate(hot_stocks):
                        try:
                            rec = scanner._analyze_stock(code, 'A股')
                            if rec and rec.score >= 50:
                                all_candidates.append(rec)
                            analyzed += 1
                            
                            # 每分析10只股票更新一次进度
                            if (j + 1) % 10 == 0 or j == len(hot_stocks) - 1:
                                progress = (j + 1) / len(hot_stocks) * 100
                                bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
                                yield f"  [{bar}] {progress:.0f}% ({j+1}/{len(hot_stocks)})\n"
                                
                        except Exception:
                            pass
                    
                    yield f"  ✅ A股 分析完成，找到 {len([c for c in all_candidates if c.market == 'A股'])} 只值得关注\n\n"
                    
                elif market == '美股':
                    hot_stocks = scanner._get_hot_us_stocks(limit=50)
                    yield f"  📋 获取到 {len(hot_stocks)} 只 美股 热门股票\n"
                    yield "  ⏳ 正在分析技术指标...\n\n"
                    
                    analyzed = 0
                    for j, code in enumerate(hot_stocks):
                        try:
                            rec = scanner._analyze_stock(code, '美股')
                            if rec and rec.score >= 50:
                                all_candidates.append(rec)
                            analyzed += 1
                            
                            if (j + 1) % 10 == 0 or j == len(hot_stocks) - 1:
                                progress = (j + 1) / len(hot_stocks) * 100
                                bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
                                yield f"  [{bar}] {progress:.0f}% ({j+1}/{len(hot_stocks)})\n"
                                
                        except Exception:
                            pass
                    
                    yield f"  ✅ 美股 分析完成，找到 {len([c for c in all_candidates if c.market == '美股'])} 只值得关注\n\n"
                    
                elif market == '港股':
                    hot_stocks = scanner._get_hot_hk_stocks(limit=30)
                    yield f"  📋 获取到 {len(hot_stocks)} 只 港股 热门股票\n"
                    yield "  ⏳ 正在分析技术指标...\n\n"
                    
                    for j, code in enumerate(hot_stocks):
                        try:
                            rec = scanner._analyze_stock(code, '港股')
                            if rec and rec.score >= 50:
                                all_candidates.append(rec)
                            
                            if (j + 1) % 10 == 0 or j == len(hot_stocks) - 1:
                                progress = (j + 1) / len(hot_stocks) * 100
                                bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
                                yield f"  [{bar}] {progress:.0f}% ({j+1}/{len(hot_stocks)})\n"
                                
                        except Exception:
                            pass
                    
                    yield f"  ✅ 港股 分析完成，找到 {len([c for c in all_candidates if c.market == '港股'])} 只值得关注\n\n"
                    
            except Exception as e:
                yield f"  ❌ {market} 扫描失败: {str(e)[:100]}\n\n"
        
        yield "---\n\n"
        
        # ===== 阶段 4: 排序并生成报告 =====
        yield "### 📊 生成分析报告\n\n"
        yield f"**{spinner_frames[3]} 正在对 {len(all_candidates)} 只值得关注进行排序...**\n\n"
        
        # 排序
        all_candidates.sort(key=lambda x: x.score, reverse=True)
        top_candidates = all_candidates[:top_n]
        
        yield f"  ✅ 筛选出 Top {len(top_candidates)} 值得关注\n\n"
        
        # 构建结果
        result = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'market_overviews': [ov.to_dict() if hasattr(ov, 'to_dict') else ov for ov in all_overviews],
            'recommendations': [c.to_dict() for c in top_candidates],
            'summary': '',
        }
        
        # ===== 阶段 5: 清空之前的进度信息，输出最终报告 =====
        yield "\n---\n\n"
        yield "## ✅ 扫描完成！\n\n"
        
        # 生成最终的 markdown 报告
        final_report = generate_dashboard_markdown(result)
        yield final_report
        
    except Exception as e:
        logger.error(f"Error running dashboard: {e}", exc_info=True)
        yield f"\n\n❌ **仪表盘扫描出错**: {str(e)}\n"


def run_dashboard(markets: list, top_n: int = 10):
    """Non-streaming version for backwards compatibility."""
    if not markets:
        markets = ["A股", "美股"]
    
    try:
        scanner = DashboardScanner()
        result = scanner.scan_market(markets=markets, top_n=top_n)
        markdown = generate_dashboard_markdown(result)
        return markdown
    except Exception as e:
        logger.error(f"Error running dashboard: {e}", exc_info=True)
        return f"❌ 仪表盘扫描出错: {str(e)}"


def generate_dashboard_markdown(result: dict) -> str:
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
        lines.append("| 市场 | 指数 | 点位 | 涨跌幅 | 上涨家数 | 下跌家数 |")
        lines.append("|:----:|:----:|-----:|-------:|---------:|---------:|")
        for ov in overviews:
            if isinstance(ov, dict):
                market = ov.get("market_type", "-")
                index_name = ov.get("index_name", "-")
                index_value = ov.get("index_value", 0)
                change = ov.get("index_change_pct", 0)
                up = ov.get("up_count", 0)
                down = ov.get("down_count", 0)
                change_emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"
                lines.append(
                    f"| {market} | {index_name} | {index_value:,.2f} | "
                    f"{change_emoji} {change:+.2f}% | {up} | {down} |"
                )
    else:
        lines.append("_暂无市场数据_")

    lines.append("")

    # Top Recommendations
    lines.append("## 🏆 今日值得关注 Top 10")
    lines.append("")

    recommendations = result.get("recommendations", [])
    if recommendations:
        lines.append("| 排名 | 代码 | 名称 | 市场 | 现价 | 涨跌幅 | 评分 | 信号 |")
        lines.append("|:----:|:----:|:----:|:----:|-----:|-------:|:----:|:----:|")

        signal_map = {
            "极具潜力": "🚀",
            "值得关注": "📈",
            "观望": "⏸️",
            "谨慎对待": "📉",
            "风险较高": "🔻",
        }

        for i, rec in enumerate(recommendations, 1):
            code = rec.get("code", "-")
            name = rec.get("name", "-")
            market = rec.get("market", "-")
            price = rec.get("current_price", 0)
            change = rec.get("change_pct", 0)
            score = rec.get("score", 0)
            signal = rec.get("signal", "-")
            signal_emoji = signal_map.get(signal, "❓")
            change_emoji = "🔴" if change < 0 else "🟢" if change > 0 else "⚪"

            lines.append(
                f"| {i} | `{code}` | {name} | {market} | "
                f"{price:.2f} | {change_emoji} {change:+.2f}% | "
                f"{score} | {signal_emoji} {signal} |"
            )

        lines.append("")

        # Detailed analysis for top 3
        lines.append("### 📋 重点推荐详情")
        lines.append("")

        for i, rec in enumerate(recommendations[:3], 1):
            code = rec.get("code", "-")
            name = rec.get("name", "-")
            market = rec.get("market", "-")
            price = rec.get("current_price", 0)
            score = rec.get("score", 0)
            signal = rec.get("signal", "-")
            reasons = rec.get("reasons", [])
            data_source = rec.get("data_source", "-")
            
            # 关键点位
            entry_price = rec.get("entry_price", price)
            stop_loss = rec.get("stop_loss", 0)
            target_price = rec.get("target_price", 0)
            risk_reward = rec.get("risk_reward_ratio", 0)
            
            # 检查清单统计
            checklist_pass = rec.get("checklist_pass", 0)
            checklist_warn = rec.get("checklist_warn", 0)
            checklist_fail = rec.get("checklist_fail", 0)
            
            # 关键指标
            bias = rec.get("bias", 0)
            rsi = rec.get("rsi", 50)
            adx = rec.get("adx", 0)
            macd_hist = rec.get("macd_hist", 0)

            lines.append(f"#### {i}. {name} (`{code}`) - {market}")
            lines.append("")
            lines.append(f"| 指标 | 数值 | 指标 | 数值 |")
            lines.append(f"|:-----|-----:|:-----|-----:|")
            lines.append(f"| **现价** | ¥{price:.2f} | **评分** | {score}/100 |")
            lines.append(f"| **乖离率** | {bias:+.1f}% | **RSI** | {rsi:.0f} |")
            lines.append(f"| **ADX** | {adx:.1f} | **MACD柱** | {macd_hist:+.2f} |")
            lines.append("")
            
            # 关键点位（精确点位）
            lines.append("**📍 精确点位**")
            lines.append("")
            lines.append(f"| 买入价 | 止损价 | 目标价 | 盈亏比 |")
            lines.append(f"|-------:|-------:|-------:|:------:|")
            lines.append(f"| ¥{entry_price:.2f} | ¥{stop_loss:.2f} | ¥{target_price:.2f} | {risk_reward:.1f}:1 |")
            lines.append("")
            
            # 检查清单统计
            lines.append(f"**📋 检查清单**: ✅{checklist_pass} ⚠️{checklist_warn} ❌{checklist_fail}")
            lines.append("")
            
            # 推荐理由（过滤空行和点位信息，因为已单独展示）
            if reasons:
                lines.append("**分析要点**:")
                for reason in reasons:
                    if reason and not reason.startswith("📍") and not reason.startswith("   "):
                        lines.append(f"- {reason}")
            
            lines.append("")
            lines.append(f"*数据来源: {data_source}*")
            lines.append("")
            lines.append("---")
            lines.append("")
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

    return "\n".join(lines)


# ========== 构建 Web UI ==========

def create_ui():
    """Create the Gradio UI."""
    
    # Custom CSS for better styling
    custom_css = """
    .gradio-container {
        font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    .gr-button-primary {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: none !important;
    }
    .gr-button-primary:hover {
        background: linear-gradient(135deg, #764ba2 0%, #667eea 100%) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    .markdown-text h1 {
        color: #1a1a2e;
        border-bottom: 2px solid #667eea;
        padding-bottom: 10px;
    }
    .markdown-text h2 {
        color: #16213e;
        margin-top: 20px;
    }
    .tab-nav button {
        font-weight: 600 !important;
    }
    .tab-nav button.selected {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
    }
    .holding-cards { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
    .holding-card { padding: 16px; border: 1px solid #e2e8f0; border-radius: 14px; background: linear-gradient(145deg, #ffffff, #f8fafc); }
    .holding-card span { display: block; color: #64748b; font-size: 0.85rem; margin-bottom: 8px; }
    .holding-card strong { font-size: 1.25rem; color: #172554; }
    @media (max-width: 720px) { .holding-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    """
    
    # Store theme and css for launch()
    theme = gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="purple",
        neutral_hue="slate",
    )
    
    with gr.Blocks(title="Clarity - 金融分析智能体") as demo:
        # Store theme and css as attributes for launch
        demo._custom_theme = theme
        demo._custom_css = custom_css
        
        # Header
        gr.Markdown(
            """
            <div style="text-align: center; padding: 20px 0;">
                <h1 style="font-size: 2.5em; margin-bottom: 10px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                    🔮 Clarity
                </h1>
                <p style="font-size: 1.2em; color: #666;">
                    基于 Claude-skill 架构的金融分析智能体
                </p>
                <p style="color: #888; font-size: 0.9em;">
                    Powered by <a href="https://www.cooragent.com/" target="_blank" style="color: #667eea;">Cooragent</a>
                </p>
            </div>
            """
        )
        
        with gr.Tabs():

            # ===== 今日热点 Tab =====
            with gr.TabItem("🔥 今日热点", id="hotspots"):
                gr.Markdown("### 梳理今日 10 大热点，一键搜索关联股票")
                hotspot_state = gr.State([])
                related_stocks_state = gr.State({})

                with gr.Row():
                    with gr.Column(scale=1):
                        hotspot_refresh = gr.Button(
                            "🔥 刷新今日热点", variant="primary", size="lg"
                        )
                        gr.Markdown("**点击任一热点即可搜索相关股票：**")
                        hotspot_buttons = [
                            gr.Button(f"热点 {i + 1}", visible=False)
                            for i in range(10)
                        ]

                    with gr.Column(scale=3):
                        hotspot_output = gr.Markdown(
                            value="点击「刷新今日热点」获取今日榜单...",
                            elem_classes=["markdown-text"],
                            height=520,
                        )
                        hotspot_stocks_output = gr.Markdown(
                            value="点击左侧热点搜索相关股票...",
                            elem_classes=["markdown-text"],
                            height=420,
                        )
                        hotspot_add_buttons = []
                        for offset in (0, 4):
                            with gr.Row():
                                hotspot_add_buttons.extend(
                                    gr.Button(f"加入持仓 {i + 1}", visible=False)
                                    for i in range(offset, offset + 4)
                                )
                        hotspot_add_status = gr.Markdown()

                hotspot_refresh.click(
                    fn=load_today_hotspots,
                    outputs=[hotspot_output, hotspot_state, *hotspot_buttons],
                )
                for i, button in enumerate(hotspot_buttons):
                    button.click(
                        fn=lambda hotspots, index=i: search_hotspot_stocks(hotspots, index),
                        inputs=hotspot_state,
                        outputs=[hotspot_stocks_output, related_stocks_state, *hotspot_add_buttons],
                    )
                for i, button in enumerate(hotspot_add_buttons):
                    button.click(
                        fn=lambda result, index=i: add_hotspot_stock(result, index),
                        inputs=related_stocks_state,
                        outputs=hotspot_add_status,
                    )
            
            # ===== 决策仪表盘 Tab =====
            with gr.TabItem("📊 决策仪表盘", id="dashboard"):
                gr.Markdown("### 每日市场扫描，发现值得关注票")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        dashboard_markets = gr.CheckboxGroup(
                            choices=["A股", "美股", "港股"],
                            value=["A股", "美股"],
                            label="扫描市场",
                        )
                        dashboard_top_n = gr.Slider(
                            minimum=5,
                            maximum=30,
                            value=10,
                            step=5,
                            label="推荐数量",
                        )
                        dashboard_btn = gr.Button(
                            "🔍 开始扫描",
                            variant="primary",
                            size="lg",
                        )
                    
                    with gr.Column(scale=3):
                        dashboard_output = gr.Markdown(
                            value="点击「开始扫描」生成今日决策仪表盘...",
                            elem_classes=["markdown-text"],
                            height=600,
                        )
                
                dashboard_btn.click(
                    fn=run_dashboard_streaming,
                    inputs=[dashboard_markets, dashboard_top_n],
                    outputs=dashboard_output,
                )
            
            # ===== 股票分析 Tab =====
            with gr.TabItem("📈 股票分析", id="analyze"):
                gr.Markdown("### 深度分析特定股票的技术面、基本面、新闻和市场情绪")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        analyze_ticker = gr.Textbox(
                            label="股票代码",
                            placeholder="例如: AAPL, NVDA, 600519",
                            lines=1,
                        )
                        analyze_date = gr.Textbox(
                            label="交易日期（可选）",
                            placeholder="YYYY-MM-DD，留空使用今天",
                            lines=1,
                        )
                        analyze_btn = gr.Button(
                            "🔍 开始分析",
                            variant="primary",
                            size="lg",
                        )
                        analyze_add = gr.Button("＋ 加入我的持仓")
                        analyze_add_status = gr.Markdown()
                        
                        gr.Markdown(
                            """
                            **支持的股票代码格式：**
                            - 美股: `AAPL`, `NVDA`, `TSLA`
                            - A股: `600519`, `000001`, `300750`
                            - 港股: `00700`, `09988`
                            """
                        )
                    
                    with gr.Column(scale=3):
                        analyze_output = gr.Markdown(
                            value="输入股票代码后点击「开始分析」...",
                            elem_classes=["markdown-text"],
                            height=600,  # 设置固定高度，使内容可滚动
                        )
                
                analyze_btn.click(
                    fn=analyze_stock_streaming,
                    inputs=[analyze_ticker, analyze_date],
                    outputs=analyze_output,
                )
                analyze_add.click(
                    fn=quick_add_holding,
                    inputs=analyze_ticker,
                    outputs=analyze_add_status,
                )

            # ===== 自演进组合 Tab =====
            with gr.TabItem("🧬 自演进组合", id="portfolio-evolution"):
                gr.Markdown("### 根据投资偏好生成组合，并用持续回测决定策略版本是否晋级")
                featured = get_featured_portfolios()
                gr.Dataframe(
                    value=[[item["rank"], item["name"], item["fund"], item["style"]] for item in featured],
                    headers=["排名", "明星投资人 / 基金", "公开披露主体", "风格"],
                    label="默认展示：全球 10 大明星投资人 / 基金公开美股组合",
                    interactive=False,
                )
                featured_buttons = []
                for offset in (0, 5):
                    with gr.Row():
                        for item in FEATURED_PORTFOLIOS[offset : offset + 5]:
                            featured_buttons.append(gr.Button(f"＋ Follow {item['name']}"))
                gr.Markdown("*Follow 会读取最新公开披露持仓，以其前 20 只股票作为种子，并按下方偏好持续回测；披露有时滞，不等于实时交易。*")
                with gr.Row():
                    with gr.Column(scale=1):
                        evolution_profile = gr.Textbox(label="组合名称", value="我的组合")
                        evolution_risk = gr.Radio(["保守", "均衡", "进取"], value="均衡", label="风险偏好")
                        evolution_markets = gr.CheckboxGroup(["A股", "港股", "美股"], value=["美股"], label="市场")
                        evolution_sectors = gr.CheckboxGroup(["科技", "消费", "医疗", "金融", "能源"], value=["科技", "消费"], label="偏好行业")
                        evolution_custom = gr.Textbox(label="自定义股票池（可选）", placeholder="AAPL, MSFT, NVDA")
                        with gr.Row():
                            evolution_size = gr.Number(label="持仓数量", value=5, precision=0)
                            evolution_years = gr.Number(label="回测年数", value=3, precision=0)
                        with gr.Row():
                            evolution_target = gr.Number(label="目标年化 (%)", value=12)
                            evolution_drawdown = gr.Number(label="最大容忍回撤 (%)", value=20)
                        with gr.Row():
                            evolution_cost = gr.Number(label="单边交易成本 (%)", value=0.15)
                            evolution_rounds = gr.Number(label="本次演进轮数", value=3, precision=0)
                        with gr.Row():
                            evolution_create = gr.Button("✨ 创建组合", variant="primary")
                            evolution_continue = gr.Button("🔁 继续演进")
                        gr.Markdown("同名组合会持续保存版本；可通过 REST API 定时调用“继续演进”。")

                    with gr.Column(scale=3):
                        evolution_summary = gr.Markdown("填写偏好后创建组合...")
                        featured_holdings = gr.Dataframe(label="已 Follow 的公开持仓", interactive=False)
                        evolution_portfolio = gr.Dataframe(label="当前目标组合", interactive=False)
                        evolution_curve = gr.LinePlot(
                            x="date", y="value", color="series",
                            title="验证集净值：策略组合 vs 等权基准", y_title="累计净值", height=360,
                        )
                        evolution_history = gr.Dataframe(label="已晋级版本", interactive=False)

                evolution_outputs = [evolution_summary, evolution_portfolio, evolution_curve, evolution_history]
                evolution_create.click(
                    fn=create_evolving_portfolio,
                    inputs=[evolution_profile, evolution_markets, evolution_sectors, evolution_risk, evolution_size, evolution_target, evolution_drawdown, evolution_cost, evolution_years, evolution_rounds, evolution_custom],
                    outputs=evolution_outputs,
                )
                evolution_continue.click(
                    fn=continue_evolving_portfolio,
                    inputs=[evolution_profile, evolution_rounds],
                    outputs=evolution_outputs,
                )
                for button, item in zip(featured_buttons, FEATURED_PORTFOLIOS):
                    button.click(
                        fn=lambda profile, risk, size, target, drawdown, cost, years, rounds, featured_id=item["id"]: follow_featured(
                            featured_id, profile, risk, size, target, drawdown, cost, years, rounds
                        ),
                        inputs=[evolution_profile, evolution_risk, evolution_size, evolution_target, evolution_drawdown, evolution_cost, evolution_years, evolution_rounds],
                        outputs=[featured_holdings, *evolution_outputs],
                    )

            # ===== 我的持仓 Tab =====
            with gr.TabItem("💼 我的持仓", id="my-holdings") as my_holdings_tab:
                gr.Markdown("### 我的持仓\n集中查看手动添加、热点发现和明星组合 Follow 的股票。")
                my_holdings_summary = gr.Markdown(
                    '<div class="holding-cards"><div class="holding-card"><span>持仓资产</span><strong>—</strong></div><div class="holding-card"><span>当前市值</span><strong>—</strong></div><div class="holding-card"><span>今日盈亏</span><strong>—</strong></div><div class="holding-card"><span>累计盈亏</span><strong>—</strong></div></div>'
                )
                with gr.Row():
                    with gr.Column(scale=3):
                        my_holdings_table = gr.Dataframe(label="持仓明细", interactive=False)
                    with gr.Column(scale=2):
                        my_holdings_allocation = gr.BarPlot(
                            x="股票", y="权重", title="组合分布：实际权重 / 待建仓目标权重",
                            y_title="权重 (%)", height=360,
                        )
                with gr.Row():
                    my_ticker = gr.Textbox(label="股票代码", placeholder="NVDA")
                    my_name = gr.Textbox(label="名称（可选）", placeholder="NVIDIA")
                    my_quantity = gr.Number(label="数量", value=0, minimum=0)
                    my_avg_cost = gr.Number(label="平均成本", value=0, minimum=0)
                with gr.Row():
                    my_save = gr.Button("保存 / 更新", variant="primary")
                    my_delete = gr.Button("移除")
                    my_refresh = gr.Button("刷新行情")
                my_holdings_status = gr.Markdown()
                my_holdings_outputs = [my_holdings_summary, my_holdings_table, my_holdings_allocation]
                my_holdings_tab.select(fn=refresh_my_holdings, outputs=my_holdings_outputs)
                my_refresh.click(fn=refresh_my_holdings, outputs=my_holdings_outputs)
                my_save.click(
                    fn=save_my_position,
                    inputs=[my_ticker, my_name, my_quantity, my_avg_cost],
                    outputs=[my_holdings_status, *my_holdings_outputs],
                )
                my_delete.click(
                    fn=delete_my_position,
                    inputs=my_ticker,
                    outputs=[my_holdings_status, *my_holdings_outputs],
                )

            # ===== 策略回测 Tab =====
            with gr.TabItem("🧪 策略回测", id="backtest"):
                gr.Markdown("### 用历史行情验证均线交叉策略")
                default_end = datetime.now().strftime("%Y-%m-%d")
                default_start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

                with gr.Row():
                    with gr.Column(scale=1):
                        backtest_ticker = gr.Textbox(label="股票代码", value="AAPL")
                        backtest_start = gr.Textbox(label="开始日期", value=default_start)
                        backtest_end = gr.Textbox(label="结束日期", value=default_end)
                        with gr.Row():
                            backtest_fast = gr.Number(label="快均线", value=10, precision=0)
                            backtest_slow = gr.Number(label="慢均线", value=30, precision=0)
                        backtest_cash = gr.Number(label="初始资金", value=100000)
                        with gr.Row():
                            backtest_commission = gr.Number(label="佣金 (%)", value=0.1)
                            backtest_slippage = gr.Number(label="滑点 (%)", value=0.05)
                        backtest_btn = gr.Button("▶️ 开始回测", variant="primary", size="lg")

                    with gr.Column(scale=3):
                        backtest_summary = gr.Markdown("填写参数后点击「开始回测」...")
                        backtest_curve = gr.LinePlot(
                            x="date",
                            y="value",
                            color="series",
                            title="策略净值与买入持有基准",
                            y_title="资产净值",
                            height=360,
                        )
                        backtest_orders = gr.Dataframe(label="交易明细", interactive=False)

                backtest_btn.click(
                    fn=backtest_strategy,
                    inputs=[
                        backtest_ticker,
                        backtest_start,
                        backtest_end,
                        backtest_fast,
                        backtest_slow,
                        backtest_cash,
                        backtest_commission,
                        backtest_slippage,
                    ],
                    outputs=[backtest_summary, backtest_curve, backtest_orders],
                )
            
            # ===== 持仓跟踪 Tab =====
            with gr.TabItem("🔍 持仓跟踪", id="track"):
                gr.Markdown("### 追踪知名投资者的最新持仓变化")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        track_investor = gr.Textbox(
                            label="投资者姓名",
                            placeholder="例如: Warren Buffett",
                            lines=1,
                        )
                        track_date = gr.Textbox(
                            label="交易日期（可选）",
                            placeholder="YYYY-MM-DD，留空使用今天",
                            lines=1,
                        )
                        track_btn = gr.Button(
                            "🔍 开始跟踪",
                            variant="primary",
                            size="lg",
                        )
                        
                        gr.Markdown(
                            """
                            **热门投资者：**
                            - Warren Buffett
                            - Ray Dalio
                            - Cathie Wood
                            - Michael Burry
                            """
                        )
                    
                    with gr.Column(scale=3):
                        track_output = gr.Markdown(
                            value="输入投资者姓名后点击「开始跟踪」...",
                            elem_classes=["markdown-text"],
                            height=600,
                        )
                
                track_btn.click(
                    fn=track_holdings_streaming,
                    inputs=[track_investor, track_date],
                    outputs=track_output,
                )
            
            # ===== 股票筛选 Tab =====
            with gr.TabItem("🔎 股票筛选", id="screen"):
                gr.Markdown("### 根据自定义条件筛选符合要求的股票")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        screen_criteria = gr.Textbox(
                            label="筛选条件",
                            placeholder="例如: 高股息科技股",
                            lines=3,
                        )
                        screen_date = gr.Textbox(
                            label="交易日期（可选）",
                            placeholder="YYYY-MM-DD，留空使用今天",
                            lines=1,
                        )
                        screen_btn = gr.Button(
                            "🔍 开始筛选",
                            variant="primary",
                            size="lg",
                        )
                        
                        gr.Markdown(
                            """
                            **筛选条件示例：**
                            - 高股息科技股
                            - PE低于15的蓝筹股
                            - 近期突破新高的股票
                            - high dividend yield tech stocks
                            """
                        )
                    
                    with gr.Column(scale=3):
                        screen_output = gr.Markdown(
                            value="输入筛选条件后点击「开始筛选」...",
                            elem_classes=["markdown-text"],
                            height=600,
                        )
                
                screen_btn.click(
                    fn=screen_stocks_streaming,
                    inputs=[screen_criteria, screen_date],
                    outputs=screen_output,
                )
            
            # ===== 智能问答 Tab =====
            with gr.TabItem("💬 智能问答", id="ask"):
                gr.Markdown("### 用自然语言提问，获取智能分析")
                
                with gr.Row():
                    with gr.Column(scale=1):
                        ask_query_input = gr.Textbox(
                            label="您的问题",
                            placeholder="例如: 分析一下苹果公司的股票",
                            lines=4,
                        )
                        ask_btn = gr.Button(
                            "🚀 获取答案",
                            variant="primary",
                            size="lg",
                        )
                        
                        gr.Markdown(
                            """
                            **问题示例：**
                            - 分析一下苹果公司的股票
                            - 巴菲特最近买了什么股票？
                            - 推荐几只高股息的科技股
                            - What are the best AI stocks?
                            """
                        )
                    
                    with gr.Column(scale=3):
                        ask_output = gr.Markdown(
                            value="输入问题后点击「获取答案」...",
                            elem_classes=["markdown-text"],
                            height=600,
                        )
                
                ask_btn.click(
                    fn=ask_query_streaming,
                    inputs=[ask_query_input],
                    outputs=ask_output,
                )
        
        # Footer
        gr.Markdown(
            """
            <div style="text-align: center; padding: 30px 0 10px 0; color: #888; font-size: 0.85em;">
                <p>
                    ⭐ <a href="https://github.com/cooragent/Clarity" target="_blank" style="color: #667eea;">GitHub</a> |
                    🌐 <a href="https://www.cooragent.com/" target="_blank" style="color: #667eea;">Cooragent</a> |
                    📝 <a href="https://github.com/cooragent/Clarity/issues" target="_blank" style="color: #667eea;">反馈问题</a>
                </p>
                <p style="margin-top: 5px;">
                    本工具仅供参考，不构成投资建议
                </p>
            </div>
            """
        )
    
    return demo


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Clarity Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=7860, help="Port to bind to")
    parser.add_argument("--share", action="store_true", help="Create a public link")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    print(f"""
    ╔══════════════════════════════════════════════════════════╗
    ║                                                          ║
    ║   🔮 Clarity - 金融分析智能体 Web UI                      ║
    ║                                                          ║
    ║   Local:   http://localhost:{args.port}                       ║
    ║   Network: http://{args.host}:{args.port}                       ║
    ║                                                          ║
    ║   Powered by Cooragent                                   ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)
    
    demo = create_ui()
    
    # Get theme and css from demo attributes (Gradio 6.0 compatibility)
    theme = getattr(demo, '_custom_theme', None)
    css = getattr(demo, '_custom_css', None)
    
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        show_error=True,
        theme=theme,
        css=css,
    )


if __name__ == "__main__":
    main()

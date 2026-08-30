# Clarity

<p align="center">
  <strong>基于原生 Claude-skill 架构的金融分析智能体</strong>
</p>

<p align="center">
  <a href="./README.md"><strong>English</strong></a> | <strong>简体中文</strong>
</p>
<p align="center">
  <a href="./README.md">👉 Switch to English</a>
</p>

<p align="center">
  <a href="https://www.cooragent.com/">
    <img src="https://img.shields.io/badge/Powered%20by-Cooragent-blue?style=flat-square" alt="Powered by Cooragent">
  </a>
  <a href="https://github.com/cooragent/Clarity/stargazers">
    <img src="https://img.shields.io/github/stars/cooragent/Clarity?style=flat-square" alt="GitHub Stars">
  </a>
  <a href="https://github.com/cooragent/Clarity/issues">
    <img src="https://img.shields.io/github/issues/cooragent/Clarity?style=flat-square" alt="GitHub Issues">
  </a>
</p>

<p align="center">
  <a href="#功能特性">功能特性</a> •
  <a href="#快速开始">快速开始</a> •
  <a href="#使用方法">使用方法</a> •
  <a href="#工作流程">工作流程</a> •
  <a href="#架构设计">架构设计</a>
</p>

> 🌟 **如果这个项目对您有帮助，请给我们一个 Star！您的支持是我们持续改进的动力！**
> 
> 💡 **欢迎提出 Issue 或 PR，我们非常重视您的反馈和建议！**

---

## 简介

Clarity 是一个基于 **原生 Claude-skill** 架构的金融分析智能体，支持股票分析、持仓追踪、筛选策略和决策仪表盘。采用 **Planning-with-Files** 模式，通过多智能体协作完成复杂的金融分析任务。

### 核心特点

- 🧠 **Claude-skill 原生架构** - 遵循 Anthropic 推荐的智能体设计模式
- 🌐 **多市场全覆盖** - A 股、港股、美股数据源自动切换
- 📊 **6 大专业智能体** - 基本面、技术面、新闻、情绪、持仓、筛选
- 🔔 **多渠道推送** - 企业微信、飞书、Telegram、邮件等
- 🚀 **REST API & Web UI** - 完整的接口和图形界面

---

## 数据源

Clarity 整合了多个金融数据源，根据市场类型自动选择最优数据源：

| 数据类型 | 数据源 | 市场覆盖 | 说明 |
|:--------|:------|:---------|:-----|
| **A 股行情** | AkShare | 沪深主板、科创板、创业板 | 实时数据 |
| **A 股行情** | EFinance | 沪深主板、科创板、创业板 | 备选数据源 |
| **全球行情** | yFinance | 美股、港股、A 股 | 全球市场 |
| **财务数据** | SimFin | 美股 | 财报数据 |
| **新闻资讯** | Finnhub | 全球 | 公司新闻 |
| **新闻资讯** | Google News | 全球 | 聚合新闻 |
| **社交情绪** | Reddit | 全球 | 社区讨论 |
| **技术指标** | Stockstats | 全球 | 技术分析 |
| **网页搜索** | Serper API | 全球 | 增强搜索能力 |
| **内容提取** | Jina AI | 全球 | 网页解析 |

**数据源优先级策略：**
- **A 股**：AkShare (优先) → EFinance (备选) → yFinance (兜底)
- **港股**：yFinance
- **美股**：yFinance + Finnhub + SimFin

---

## 功能特性

| 功能 | 描述 |
|:-----|:-----|
| **股票分析** | 技术面 + 基本面 + 新闻 + 市场情绪四维度深度分析 |
| **持仓跟踪** | 追踪 Warren Buffett 等知名投资者的最新持仓变化 |
| **股票筛选** | 基于自然语言描述筛选符合条件的股票 |
| **决策仪表盘** | 每日自动扫描市场并推荐值得关注的股票 |
| **多渠道推送** | 分析报告自动推送到企业微信、飞书、Telegram 等 |

---

## 快速开始

### 安装

```bash
git clone https://github.com/your-org/Clarity.git
cd Clarity

# 使用 uv（推荐）
uv sync
```

### 配置

创建 `.env` 文件：

```bash
# ===== 必需配置 =====
OPENAI_API_KEY=your_openai_api_key           # OpenAI API（或兼容接口）
FINNHUB_API_KEY=your_finnhub_api_key         # Finnhub 新闻数据（免费层可用）

# ===== 可选：增强搜索（推荐配置）=====
SERPER_API_KEY=your_serper_api_key           # Google 搜索 API
JINA_API_KEY=your_jina_api_key               # 网页内容提取

# ===== 可选：通知推送 =====
WECHAT_WEBHOOK_URL=https://qyapi.weixin.qq.com/...     # 企业微信
FEISHU_WEBHOOK_URL=https://open.feishu.cn/...          # 飞书
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...                   # Telegram
TELEGRAM_CHAT_ID=123456789
EMAIL_SENDER=your@qq.com                               # 邮件
EMAIL_PASSWORD=授权码

# ===== 可选：Qwen 模型（阿里通义千问）=====
QWEN_API_KEY=your_dashscope_api_key
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-latest
# 使用方式：uv run run_agent.py --model qwen analyze AAPL
```

---

## 使用方法

### REST API

Clarity 提供了完整的 RESTful API 接口，支持所有核心功能。

```bash
# 启动 API 服务器
uv run python api.py

# 自定义端口和地址
API_PORT=8000 API_HOST=0.0.0.0 uv run python api.py
```

API 服务启动后，访问 http://localhost:8000/docs 查看交互式 API 文档。

#### API 端点

| 端点 | 方法 | 描述 | 示例 |
|:-----|:-----|:-----|:-----|
| `/health` | GET | 健康检查 | - |
| `/api/v1/analyze` | POST | 股票分析 | `{"ticker": "AAPL", "model": "openai"}` |
| `/api/v1/track` | POST | 持仓跟踪 | `{"investor_name": "Warren Buffett"}` |
| `/api/v1/screen` | POST | 股票筛选 | `{"criteria": "high dividend yield"}` |
| `/api/v1/ask` | POST | 自然语言查询 | `{"query": "分析苹果公司"}` |
| `/api/v1/dashboard` | POST | 决策仪表盘 | `{"markets": ["A股"], "top_n": 10}` |
| `/api/v1/notification/channels` | GET | 获取通知渠道 | - |

#### 使用示例

```bash
# 分析股票
curl -X POST "http://localhost:8000/api/v1/analyze" \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "model": "openai"}'

# 追踪投资者持仓
curl -X POST "http://localhost:8000/api/v1/track" \
  -H "Content-Type: application/json" \
  -d '{"investor_name": "Warren Buffett"}'

# 决策仪表盘（推送通知）
curl -X POST "http://localhost:8000/api/v1/dashboard" \
  -H "Content-Type: application/json" \
  -d '{"markets": ["A股", "美股"], "top_n": 10, "push": true}'
```

#### Python 客户端示例

```python
import httpx
import asyncio

async def analyze_stock(ticker: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/analyze",
            json={"ticker": ticker, "model": "openai"}
        )
        return response.json()

# 运行
result = asyncio.run(analyze_stock("AAPL"))
print(result["report"])
```

### Web UI

```bash
# 构建 React 前端
cd frontend
npm install
npm run build
cd ..

# 启动 Clarity API 和构建后的前端
uv run uvicorn api:app --host 127.0.0.1 --port 8000
```

访问 http://localhost:8000/app/。开发前端时可在 `frontend/` 内运行
`npm run dev`，Vite 会把 API 请求代理到 8000 端口。

原 Gradio 页面仍作为备用入口保留：`uv run python webui.py`。

#### 可选：Vibe-Trading 量化内核

在独立的 Python 3.11+ 环境启动 Vibe-Trading，再让 Clarity 连接它：

```bash
# Vibe-Trading 进程
vibe-trading serve --port 8899

# Clarity 进程
VIBE_TRADING_URL=http://127.0.0.1:8899 \
  uv run uvicorn api:app --host 127.0.0.1 --port 8000
```

Clarity 通过 `/api/v1/vibe/*` 代理会话、消息和事件流；热点、分析、组合、持仓和回测等原有能力不依赖 Vibe，可独立运行。

### CLI 命令

```bash
# 分析股票
uv run python run_agent.py analyze AAPL
uv run python run_agent.py analyze NVDA --date 2025-01-15
uv run python run_agent.py --model qwen analyze AAPL

# 跟踪投资者持仓
uv run python run_agent.py track "Warren Buffett"

# 筛选股票
uv run python run_agent.py screen "high dividend yield tech stocks"

# 自然语言查询
uv run python run_agent.py ask "分析一下苹果公司的股票"

# 决策仪表盘
uv run python run_agent.py dashboard                           # 扫描 A股+美股
uv run python run_agent.py dashboard -m A股 港股              # 扫描指定市场
uv run python run_agent.py dashboard -n 20 -o report.md       # 推荐20只，保存到文件
uv run python run_agent.py dashboard --push                   # 扫描并推送通知
uv run python run_agent.py dashboard -p --push-to wechat      # 仅推送到企业微信
```

### Python 代码

```python
import asyncio
from clarity import FinancialAgentOrchestrator, AgentConfig, TaskType

async def main():
    orchestrator = FinancialAgentOrchestrator()

    # 分析股票
    result = await orchestrator.run(
        task_type=TaskType.STOCK_ANALYSIS,
        target="AAPL",
    )
    print(result["report"])

asyncio.run(main())
```

```python
# 使用通知服务
from clarity.core import NotificationService

notification = NotificationService()
notification.send("# 测试报告\n这是 Markdown 格式的消息")
```

---

## 工作原理

### Planning-with-Files 模式

系统使用三个持久化文件管理长任务，解决 LLM "遗忘"问题：

| 文件 | 作用 |
|:-----|:-----|
| `task_plan.md` | 任务计划、阶段状态、智能体分配 |
| `findings.md` | 研究发现、API 数据、分析结果 |
| `progress.md` | 执行日志、错误记录、重试追踪 |

**执行流程：** MasterAgent 规划 → WorkingAgent 执行 → SubAgents 分工 → StateChecker 验证 → 生成报告

---

## 架构设计

### 核心智能体

| 智能体 | 职责 |
|:-------|:-----|
| **MasterAgent** | 任务规划、结果合成 |
| **WorkingAgent** | 执行协调、流程控制 |
| **StateChecker** | 状态验证、错误重试 |
| **Fundamentals Analyst** | 财务报表、基本面分析 |
| **Technical Analyst** | 技术指标（MACD、RSI、布林带）|
| **News Analyst** | 新闻收集与情感分析 |
| **Sentiment Analyst** | 社交媒体情绪监控 |
| **Holdings Hunter** | 机构持仓追踪（SEC 13F）|
| **Alpha Hound** | 股票筛选与评分 |

### 目录结构

```
Clarity/
├── api.py               # REST API 服务器
├── frontend/            # React/Vite Web 界面
├── webui.py             # 旧版 Gradio 备用界面
├── run_agent.py         # CLI 命令行工具
└── clarity/
    ├── core/            # 核心智能体与工具
    │   └── vibe_client.py # Vibe-Trading HTTP 边界
    └── dataflows/       # 数据源集成
```

---

## 支持与贡献

本项目由 Cooragent 团队提供技术支持。Cooragent 是自演进的多智能体平台，致力于让每个人都能成为 Agent 的指挥官。

### 🌟 支持我们

如果这个项目对您有帮助，请：

- ⭐ **给项目点个 Star** - 这是对我们最大的鼓励！
- 🐛 **提交 Issue** - 报告 Bug 或提出功能建议
- 🔀 **提交 PR** - 欢迎贡献代码和文档改进
- 💬 **加入社区** - 与其他用户交流使用经验

### 📮 联系我们

- 🌐 飞书: [cooragent](https://applink.feishu.cn/client/chat/chatter/add_by_link?link_token=251mf86f-8106-4361-81aa-05fa856abc05)
- 📧 问题反馈：请通过 [GitHub Issues](https://github.com/cooragent/Clarity/issues) 提交

---

## Star History

<a href="https://star-history.com/#cooragent/Clarity&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=cooragent/Clarity&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=cooragent/Clarity&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=cooragent/Clarity&type=Date" />
 </picture>
</a>

import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import {
  Activity, BarChart3, Bot, BrainCircuit, ChevronRight, CircleDollarSign,
  ExternalLink, Flame, LayoutDashboard, LineChart as LineIcon, ListFilter, Menu, Plus,
  Maximize2, Radar, RefreshCw, Search, Send, Star, Trash2, UserRoundSearch, WalletCards, X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { del, get, post } from "./api";

type Json = Record<string, any>;
type Page = "vibe" | "hotspots" | "dashboard" | "analyze" | "evolve" | "holdings" | "backtest" | "track" | "screen" | "ask";

const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const yearsAgo = (years: number) => new Date(Date.now() - years * 365 * 864e5).toISOString().slice(0, 10);
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const fmt = (value: unknown, digits = 2) => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: digits });

const nav: { id: Page; label: string; icon: typeof Bot; group: string }[] = [
  { id: "holdings", label: "我的持仓", icon: WalletCards, group: "工作台" },
  { id: "hotspots", label: "今日热点", icon: Flame, group: "工作台" },
  { id: "dashboard", label: "决策仪表盘", icon: LayoutDashboard, group: "工作台" },
  { id: "track", label: "持仓追踪", icon: UserRoundSearch, group: "工作台" },
  { id: "ask", label: "智能问答", icon: Radar, group: "工作台" },
  { id: "screen", label: "股票筛选", icon: ListFilter, group: "研究" },
  { id: "analyze", label: "个股分析", icon: Search, group: "研究" },
  { id: "backtest", label: "策略探索", icon: LineIcon, group: "研究" },
  { id: "evolve", label: "自演进策略", icon: BrainCircuit, group: "研究" },
  { id: "vibe", label: "Vibe 量化", icon: Bot, group: "量化" },
];

const pageMeta: Record<Page, [string, string]> = {
  vibe: ["Vibe 量化", "把复杂策略研究交给独立运行的 Vibe-Trading"],
  hotspots: ["今日热点", "梳理全球 10 大事件，并搜索关联股票"],
  dashboard: ["决策仪表盘", "扫描市场，生成今日关注清单"],
  analyze: ["个股分析", "多智能体基本面与交易研究"],
  evolve: ["自演进策略", "根据偏好持续回测并迭代参数"],
  holdings: ["我的持仓", "统一管理关注标的与真实仓位"],
  backtest: ["策略探索", "验证策略的收益、风险与交易记录"],
  track: ["持仓追踪", "Follow 全球明星科技大佬与基金，并研究公开持仓"],
  screen: ["股票筛选", "用自然语言描述你的选股条件"],
  ask: ["智能问答", "让 Clarity 选择合适的金融研究工作流"],
};

function Button({ children, busy, secondary = false, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; secondary?: boolean }) {
  return <button className={secondary ? "button secondary" : "button"} disabled={busy || props.disabled} {...props}>{busy && <RefreshCw size={15} className="spin" />}{children}</button>;
}

function ErrorBox({ error }: { error: string }) {
  return error ? <div className="error">{error}</div> : null;
}

function Card({ title, action, children, className = "" }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`card ${className}`}>
    {(title || action) && <div className="card-head"><h2>{title}</h2>{action}</div>}
    {children}
  </section>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}</label>;
}

function Markdown({ value }: { value?: string }) {
  return value ? <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown></div> : null;
}

function Table({ rows }: { rows?: Json[] }) {
  if (!rows?.length) return <div className="empty">暂无数据</div>;
  const columns = Object.keys(rows[0]);
  return <div className="table-wrap"><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>
    {rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{typeof row[key] === "object" ? JSON.stringify(row[key]) : String(row[key] ?? "-")}</td>)}</tr>)}
  </tbody></table></div>;
}

function Metrics({ items }: { items: { label: string; value: ReactNode; tone?: string }[] }) {
  return <div className="metrics">{items.map((item) => <div className="metric" key={item.label}><span>{item.label}</span><strong className={item.tone || ""}>{item.value}</strong></div>)}</div>;
}

function Curve({ rows }: { rows?: Json[] }) {
  if (!rows?.length) return null;
  const grouped = Object.values(rows.reduce((acc: Record<string, Json>, row) => {
    const date = String(row.date || "").slice(0, 10);
    acc[date] ||= { date };
    acc[date][row.series] = Number(row.value);
    return acc;
  }, {}));
  const series = [...new Set(rows.map((row) => row.series))];
  const colors = ["#f47b20", "#4ea1ff", "#55c798"];
  return <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={grouped} margin={{ top: 10, right: 12, left: 4, bottom: 0 }}>
    <CartesianGrid stroke="#25303d" vertical={false} /><XAxis dataKey="date" tick={{ fill: "#7f8b9a", fontSize: 11 }} minTickGap={35} /><YAxis tick={{ fill: "#7f8b9a", fontSize: 11 }} domain={["auto", "auto"]} />
    <Tooltip contentStyle={{ background: "#151d28", border: "1px solid #2a3645", borderRadius: 8 }} /><Legend />
    {series.map((name, i) => <Line key={name} type="monotone" dataKey={name} stroke={colors[i % colors.length]} dot={false} strokeWidth={2} />)}
  </LineChart></ResponsiveContainer></div>;
}

function AddHolding({ ticker, name = "" }: { ticker: string; name?: string }) {
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  async function add() {
    setBusy(true); setFailed(false);
    try { await post("/api/v1/holdings", { ticker, name }); setDone(true); }
    catch { setFailed(true); }
    finally { setBusy(false); }
  }
  return <Button secondary busy={busy} onClick={add} disabled={done}>{done ? "已加入" : failed ? "重试加入" : <><Plus size={14} /> 加入持仓</>}</Button>;
}

function VibePage() {
  const [status, setStatus] = useState<Json>({});
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState<Json[]>([]);
  const [prompt, setPrompt] = useState("研究 NVDA 最近一年的趋势，提出一套可回测的策略并说明风险");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = () => get<Json>("/api/v1/vibe/status").then(setStatus).catch((e) => setError(e.message));
  useEffect(() => { void refresh(); }, []);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    if (!prompt.trim()) return;
    setBusy(true); setError("");
    try {
      let id = sessionId;
      if (!id) {
        const session = await post<Json>("/api/v1/vibe/sessions", { title: "Clarity 量化研究" });
        id = session.session_id || session.id;
        setSessionId(id);
      }
      const before = messages.length;
      await post(`/api/v1/vibe/sessions/${id}/messages`, { content: prompt });
      for (let i = 0; i < 40; i += 1) {
        await sleep(1500);
        const next = await get<Json[]>(`/api/v1/vibe/sessions/${id}/messages`);
        setMessages(next);
        if (next.length > before && next.some((item, index) => index >= before && item.role === "assistant")) break;
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="stack">
    <div className="hero-grid">
      <Card className="hero-card">
        <div className="eyebrow"><Bot size={16} /> 独立量化内核</div>
        <h1>从自然语言到策略验证</h1>
        <p>Clarity 负责研究、组合与持仓；Vibe-Trading 在独立进程中负责复杂量化任务，两者通过 HTTP API 解耦。</p>
        <div className="status-row"><span className={`status-dot ${status.connected ? "online" : ""}`} />{status.connected ? `已连接 ${status.version || ""}` : "Vibe-Trading 未启动"}<button className="icon-button" onClick={refresh} aria-label="刷新连接"><RefreshCw size={15} /></button></div>
      </Card>
      <Card title="运行边界">
        <div className="kernel-flow"><span>Clarity React</span><ChevronRight /><span>FastAPI 代理</span><ChevronRight /><span>Vibe Kernel</span></div>
        <p className="muted">内核地址：{status.url || "http://127.0.0.1:8899"}</p>
      </Card>
    </div>
    <Card title="新建量化任务">
      <form onSubmit={send} className="prompt-box"><textarea aria-label="量化任务" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={4} /><Button busy={busy} type="submit"><Send size={15} />运行任务</Button></form>
      <div className="chips">{["回测 NVDA 动量策略", "比较 AAPL 与 MSFT 风险收益", "构建低回撤科技组合"].map((value) => <button key={value} onClick={() => setPrompt(value)}>{value}</button>)}</div>
      <ErrorBox error={error} />
    </Card>
    {messages.length > 0 && <Card title="任务对话"><div className="messages">{messages.map((message, index) => <div key={message.id || index} className={`message ${message.role || "assistant"}`}><small>{message.role === "user" ? "你" : "Vibe"}</small><Markdown value={typeof message.content === "string" ? message.content : JSON.stringify(message.content)} /></div>)}</div></Card>}
  </div>;
}

function HotspotsPage() {
  const [data, setData] = useState<Json>({});
  const [related, setRelated] = useState<Json>({});
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const loaded = useRef(false);
  async function load(limit = 10, refresh = false) {
    if (refresh) { setSelected(""); setRelated({}); }
    setBusy(true); setError("");
    try { setData(await get<Json>(`/api/v1/hotspots?limit=${limit}${refresh ? "&refresh=true" : ""}`)); }
    catch (e) { if (refresh) localStorage.removeItem("hotspots-refreshed"); setError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    if (loaded.current) return;
    loaded.current = true;
    const key = "hotspots-refreshed";
    const refresh = localStorage.getItem(key) !== today;
    if (refresh) localStorage.setItem(key, today);
    void load(10, refresh);
  }, []);
  async function search(title: string) {
    setSelected(title); setBusy(true); setError("");
    try { setRelated(await post<Json>("/api/v1/hotspots/stocks", { title, limit: 8 })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="hotspot-layout">
    <Card title={`${data.date || today} · 全球热点`} action={<Button secondary busy={busy} onClick={() => load(10, true)}><RefreshCw size={14} />刷新</Button>}>
      <div className="hotspot-list">{(data.hotspots || []).map((item: Json, index: number) => <article key={item.link || index} className={`hotspot ${selected === item.title ? "selected" : ""}`}>
        <strong>{String(index + 1).padStart(2, "0")}</strong><a href={item.link} target="_blank" rel="noreferrer"><b>{item.title}</b><small>{item.source} · {item.published} · 查看原文 <ExternalLink size={11} /></small></a><Button secondary busy={busy && selected === item.title} onClick={() => search(item.title)}>相关股票</Button>
      </article>)}</div>
      {data.has_more && <div className="more-hotspots"><Button secondary busy={busy} onClick={() => load((data.hotspots || []).length + 10)}>更多热点事件</Button></div>}
      <ErrorBox error={error} />
    </Card>
    <Card title="关联股票" className="related-panel">{selected ? <><p className="muted">股票识别与趋势图来源：东方财富行情</p><ul className="related-stock-list">{(related.stocks || []).map((stock: Json) => <li className="related-stock" key={stock.symbol}><a href={stock.chart_url} target="_blank" rel="noreferrer"><div><strong>{stock.symbol}</strong><span>{stock.name}</span></div><small>{stock.market} · {stock.relation}</small><ExternalLink size={15} /></a><AddHolding ticker={stock.symbol} name={stock.name} /></li>)}</ul>{!busy && !(related.stocks || []).length && <div className="empty">暂未找到明确关联的上市公司</div>}</> : <div className="empty">点击新闻右侧的“相关股票”查询</div>}</Card>
  </div>;
}

function DashboardPage() {
  const [markets, setMarkets] = useState(["A股", "美股"]);
  const [topN, setTopN] = useState(10);
  const [result, setResult] = useState<Json>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { get<Json>("/api/v1/dashboard/latest").then(setResult).catch((e) => setError(e.message)); }, []);
  async function run() { setBusy(true); setError(""); try { setResult(await post<Json>("/api/v1/dashboard", { markets, top_n: topN, push: false })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  return <div className="stack"><Card title="扫描参数"><div className="inline-form"><div className="checks">{["A股", "美股", "港股"].map((market) => <label key={market}><input type="checkbox" checked={markets.includes(market)} onChange={() => setMarkets(markets.includes(market) ? markets.filter((x) => x !== market) : [...markets, market])} />{market}</label>)}</div><Field label="推荐数量"><input type="number" min="1" max="50" value={topN} onChange={(e) => setTopN(Number(e.target.value))} /></Field><Button busy={busy} onClick={run}><Activity size={15} />开始扫描</Button></div><ErrorBox error={error} /></Card>{result.markdown && <Card><Markdown value={result.markdown} /></Card>}</div>;
}

function AgentReportPage({ kind }: { kind: "analyze" | "track" | "screen" | "ask" }) {
  const configs = {
    analyze: { label: "股票代码", placeholder: "NVDA", key: "ticker", button: "开始分析" },
    track: { label: "投资者 / 基金", placeholder: "Warren Buffett", key: "investor_name", button: "开始跟踪" },
    screen: { label: "筛选条件", placeholder: "高 ROE、低负债的科技公司", key: "criteria", button: "开始筛选" },
    ask: { label: "问题", placeholder: "分析英伟达近期投资价值", key: "query", button: "发送问题" },
  } as const;
  const config = configs[kind];
  const [value, setValue] = useState("");
  const [model, setModel] = useState("openai");
  const [date, setDate] = useState(today);
  const [result, setResult] = useState<Json>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function run(event: FormEvent) {
    event.preventDefault(); if (!value.trim()) return;
    setBusy(true); setError("");
    try { setResult(await post<Json>(`/api/v1/${kind}`, { [config.key]: value, model, ...(kind !== "ask" ? { trade_date: date } : {}) })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="stack"><Card title="研究任务"><form onSubmit={run} className="form-grid"><Field label={config.label}><input value={value} onChange={(e) => setValue(e.target.value)} placeholder={config.placeholder} /></Field>{kind !== "ask" && <Field label="研究日期"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>}<Field label="模型"><select value={model} onChange={(e) => setModel(e.target.value)}><option value="openai">OpenAI</option><option value="qwen">Qwen</option></select></Field><Button busy={busy} type="submit"><Search size={15} />{config.button}</Button></form><ErrorBox error={error} /></Card>{kind === "analyze" && result.target && <div className="action-strip"><span>将 {result.target} 加入我的持仓</span><AddHolding ticker={result.target} /></div>}{(result.report || result.error) && <Card><Markdown value={result.report || result.error} /></Card>}</div>;
}

function EvolutionResult({ result }: { result: Json }) {
  if (!result.profile) return null;
  const m = result.metrics || {};
  return <div className="stack"><Metrics items={[
    { label: "偏好得分", value: fmt(result.score) }, { label: "年化收益", value: `${fmt(m.annual_return * 100)}%`, tone: m.annual_return >= 0 ? "positive" : "negative" },
    { label: "最大回撤", value: `${fmt(m.max_drawdown * 100)}%` }, { label: "夏普比率", value: fmt(m.sharpe) },
  ]} /><Card title={`${result.profile} · v${result.version}`}><Curve rows={result.curve} /><h3>当前组合</h3><Table rows={(result.portfolio || []).map((x: Json) => ({ 股票: x.ticker, 权重: `${fmt(x.weight * 100)}%` }))} />{result.source_holdings?.holdings?.length > 0 && <><h3>Follow 的公开持仓</h3><Table rows={result.source_holdings.holdings} /></>}<h3>已晋级版本</h3><Table rows={result.history} /></Card></div>;
}

function TrackingPage() {
  const [featured, setFeatured] = useState<Json[]>([]);
  const [result, setResult] = useState<Json>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { get<Json[]>("/api/v1/portfolio/featured").then(setFeatured).catch((e) => setError(e.message)); }, []);
  async function follow(id: string) {
    setBusy(id); setError("");
    try { setResult(await post<Json>(`/api/v1/portfolio/featured/${id}/follow`, { profile_prefix: "Follow", risk: "均衡", portfolio_size: 5, target_return_pct: 12, max_drawdown_pct: 20, trading_cost_pct: 0.15, years: 3, rounds: 3, end: today })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  return <div className="stack"><Card title="全球明星科技大佬 / 基金"><p className="muted">首次 Follow 默认投入 $100,000，并按公开权重同步到“我的持仓”；重复 Follow 不会重复扣减股本。</p><div className="featured-grid">{featured.map((item) => <article className="featured" key={item.id}><span className="rank">#{item.rank}</span><Star size={18} /><h3>{item.name}</h3><p>{item.fund}</p><small>{item.style}</small><Button busy={busy === item.id} onClick={() => follow(item.id)}>一键 Follow</Button></article>)}</div><ErrorBox error={error} /></Card><EvolutionResult result={result} /><AgentReportPage kind="track" /></div>;
}

function EvolvePage() {
  const [result, setResult] = useState<Json>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [markets, setMarkets] = useState(["美股"]);
  const [sectors, setSectors] = useState(["科技", "消费"]);
  const [form, setForm] = useState({ profile: "我的科技组合", risk: "均衡", portfolio_size: 5, target_return_pct: 12, max_drawdown_pct: 20, trading_cost_pct: 0.15, start: yearsAgo(3), end: today, rounds: 3, custom_tickers: "NVDA,AAPL,MSFT,GOOGL,AMZN,META" });
  const set = (key: string, value: string | number) => setForm({ ...form, [key]: value });
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy("create"); setError("");
    try { setResult(await post<Json>("/api/v1/portfolio/evolve", { ...form, markets, sectors })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  async function evolve() {
    setBusy("continue"); setError("");
    try { setResult(await post<Json>(`/api/v1/portfolio/evolve/${encodeURIComponent(result.profile || form.profile)}`, { rounds: form.rounds, end: form.end })); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(""); }
  }
  return <div className="stack">
    <Card title="创建偏好组合"><form onSubmit={create} className="form-grid wide"><Field label="组合名称"><input value={form.profile} onChange={(e) => set("profile", e.target.value)} /></Field><Field label="风险偏好"><select value={form.risk} onChange={(e) => set("risk", e.target.value)}><option>保守</option><option>均衡</option><option>进取</option></select></Field><Field label="市场"><div className="checks">{["A股", "港股", "美股"].map((x) => <label key={x}><input type="checkbox" checked={markets.includes(x)} onChange={() => setMarkets(markets.includes(x) ? markets.filter((v) => v !== x) : [...markets, x])} />{x}</label>)}</div></Field><Field label="偏好行业"><div className="checks">{["科技", "消费", "医疗", "金融", "能源"].map((x) => <label key={x}><input type="checkbox" checked={sectors.includes(x)} onChange={() => setSectors(sectors.includes(x) ? sectors.filter((v) => v !== x) : [...sectors, x])} />{x}</label>)}</div></Field><Field label="持仓数量"><input type="number" min="2" max="20" value={form.portfolio_size} onChange={(e) => set("portfolio_size", Number(e.target.value))} /></Field><Field label="目标年化 %"><input type="number" value={form.target_return_pct} onChange={(e) => set("target_return_pct", Number(e.target.value))} /></Field><Field label="最大回撤 %"><input type="number" value={form.max_drawdown_pct} onChange={(e) => set("max_drawdown_pct", Number(e.target.value))} /></Field><Field label="交易成本 %"><input type="number" step="0.01" value={form.trading_cost_pct} onChange={(e) => set("trading_cost_pct", Number(e.target.value))} /></Field><Field label="开始日期"><input type="date" value={form.start} onChange={(e) => set("start", e.target.value)} /></Field><Field label="结束日期"><input type="date" value={form.end} onChange={(e) => set("end", e.target.value)} /></Field><Field label="演进轮数"><input type="number" min="0" max="20" value={form.rounds} onChange={(e) => set("rounds", Number(e.target.value))} /></Field><Field label="自选股票"><input value={form.custom_tickers} onChange={(e) => set("custom_tickers", e.target.value)} /></Field><Button busy={busy === "create"} type="submit"><BrainCircuit size={15} />创建并演进</Button><Button secondary busy={busy === "continue"} type="button" onClick={evolve}>继续演进</Button></form><ErrorBox error={error} /></Card>
    <EvolutionResult result={result} />
  </div>;
}

const pieColors = ["#f47b20", "#4ea1ff", "#55c798", "#a980ff", "#f2c14e", "#e96f92", "#58c4d8", "#9fc45b"];

function HoldingsOverview({ rows, onRemove, onInvest }: { rows: Json[]; onRemove: (ticker: string) => void; onInvest: (ticker: string, name: string) => void }) {
  const currencies = [...new Set(rows.map((item) => item.currency))];
  const [currency, setCurrency] = useState(currencies[0] || "USD");
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => { if (currencies.length && !currencies.includes(currency)) setCurrency(currencies[0]); }, [currencies.join(","), currency]);
  useEffect(() => {
    if (!fullscreen) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setFullscreen(false); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [fullscreen]);

  const selected = rows.filter((item) => item.currency === currency);
  const usesMarketValue = selected.some((item) => item.market_value > 0);
  const pieRows: Json[] = selected.filter((item) => usesMarketValue ? item.market_value > 0 : item.target_weight_pct > 0).map((item): Json => ({ ...item, share_value: usesMarketValue ? item.market_value : item.target_weight_pct, label: `${item.ticker} · ${item.name || item.status}` }));
  const total = pieRows.reduce((sum, item) => sum + item.share_value, 0);
  const content = <div className="portfolio-overview">
    <div className="pie-panel">
      {pieRows.length ? <><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={pieRows} dataKey="share_value" nameKey="label" innerRadius="52%" outerRadius="82%" paddingAngle={2}>{pieRows.map((item, index) => <Cell key={item.ticker} fill={pieColors[index % pieColors.length]} />)}</Pie><Tooltip formatter={(value: number, name: string) => [`${fmt(value)} ${usesMarketValue ? currency : "目标权重"} · ${fmt(Number(value) / total * 100)}%`, name]} contentStyle={{ background: "#273548", border: "1px solid #4a5d75", borderRadius: 8, boxShadow: "0 8px 24px #0006" }} /></PieChart></ResponsiveContainer><div className="pie-center"><small>{usesMarketValue ? `${currency} 总市值` : "目标组合"}</small><strong>{usesMarketValue ? fmt(total) : `${fmt(total)}%`}</strong></div></> : <div className="empty">录入持仓数量后显示占比</div>}
    </div>
    <div className="holding-table"><div className="table-wrap"><table><thead><tr><th>股票</th><th>最新价</th><th>持仓市值</th><th>{usesMarketValue ? "占比" : "目标权重"}</th><th>当日盈亏</th><th>累计盈亏</th><th /></tr></thead><tbody>{selected.map((item) => <tr key={item.ticker}><td><button className="stock-select" onClick={() => onInvest(item.ticker, item.name)} title="点击增加股本"><strong>{item.ticker}</strong><small>{item.name || item.status}</small></button></td><td>{item.last_price ? `${fmt(item.last_price)} ${item.currency}${item.quote_stale ? " · 缓存" : ""}` : "行情不可用"}</td><td>{fmt(item.market_value)} {item.currency}</td><td>{fmt(usesMarketValue ? item.allocation_pct : item.target_weight_pct)}%</td><td className={item.day_gain >= 0 ? "positive" : "negative"}>{fmt(item.day_gain)}</td><td className={item.total_gain >= 0 ? "positive" : "negative"}>{fmt(item.total_gain)}<small>{fmt(item.total_gain_pct)}%</small></td><td><button className="icon-button danger" onClick={() => onRemove(item.ticker)} aria-label={`删除 ${item.ticker}`}><Trash2 size={16} /></button></td></tr>)}</tbody></table></div></div>
  </div>;
  const actions = <div className="overview-actions"><div className="currency-tabs">{currencies.map((item) => <button className={item === currency ? "active" : ""} key={item} onClick={() => setCurrency(item)}>{item}</button>)}</div><Button secondary onClick={() => setFullscreen(true)}><Maximize2 size={14} />全屏</Button></div>;

  return <><Card title="持仓占比 Overview" action={actions}>{content}</Card>{fullscreen && <div className="fullscreen-backdrop" role="dialog" aria-modal="true" aria-label="持仓占比全屏视图" onClick={() => setFullscreen(false)}><section className="fullscreen-card" onClick={(event) => event.stopPropagation()}><div className="card-head"><h2>持仓占比 Overview · {currency}</h2><button className="icon-button" onClick={() => setFullscreen(false)} aria-label="退出全屏"><X size={18} /></button></div>{content}</section></div>}</>;
}

function HoldingsPage() {
  const [data, setData] = useState<Json>({ holdings: [], totals: {} });
  const [performance, setPerformance] = useState<Json>({ curve: [] });
  const [form, setForm] = useState({ ticker: "", name: "", quantity: 0, avg_cost: 0 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() { setBusy(true); setError(""); try { setData(await get<Json>("/api/v1/holdings")); void get<Json>("/api/v1/holdings/performance?days=90").then(setPerformance).catch((e) => setError(e.message)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  useEffect(() => { void load(); }, []);
  async function save(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { await post<Json>("/api/v1/holdings", form); setForm({ ticker: "", name: "", quantity: 0, avg_cost: 0 }); await load(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function remove(ticker: string) { try { await del(`/api/v1/holdings/${ticker}`); await load(); } catch (e) { setError((e as Error).message); } }
  async function invest(ticker: string, name: string) { const value = window.prompt(`是否为 ${ticker} 增加股本？请输入投入金额（USD）`, "10000"); if (value === null) return; const capital = Number(value); if (!(capital > 0)) { setError("请输入大于 0 的股本金额"); return; } setBusy(true); setError(""); try { setData(await post<Json>(`/api/v1/holdings/${encodeURIComponent(ticker)}/invest`, { capital_usd: capital, name })); void get<Json>("/api/v1/holdings/performance?days=90").then(setPerformance); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  async function buyCoins() { if (!window.confirm("支付虚拟 $10，兑换模拟股本 $1,000,000？")) return; setBusy(true); setError(""); try { setData(await post<Json>("/api/v1/account/virtual-capital", { packs: 1 })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  const account = data.account || {};
  const totals = [{ label: "模拟账户总权益", value: `$${fmt(account.portfolio_equity_usd)}` }, { label: "可用股本", value: `$${fmt(account.available_capital_usd)}` }, { label: "已投入股本", value: `$${fmt(account.invested_capital_usd)}` }, { label: "累计盈亏", value: `$${fmt(Number(account.realized_pnl_usd || 0) + Number(account.unrealized_pnl_usd || 0))}`, tone: Number(account.realized_pnl_usd || 0) + Number(account.unrealized_pnl_usd || 0) >= 0 ? "positive" : "negative" }];
  return <div className="stack"><div className="holdings-toolbar"><span className="persisted"><span className="status-dot online" />SQLite 已保存 · 不可变快照</span><div className="overview-actions"><Button secondary busy={busy} onClick={buyCoins}><CircleDollarSign size={14} />虚拟 $10 → 股本 $1M</Button><Button secondary busy={busy} onClick={load}><RefreshCw size={14} />刷新行情</Button></div></div><Metrics items={totals} /><ErrorBox error={error} />{(data.holdings || []).length ? <HoldingsOverview rows={data.holdings} onRemove={remove} onInvest={invest} /> : <Card><div className="empty">还没有持仓，可从热点、分析或 Follow 组合加入。</div></Card>}<Card title="每日收益变化 · 最近 90 个交易日"><p className="muted">点击上方任一股票即可选择投入股本；盈利会增加可用股本，亏损会减少可用股本。</p>{performance.curve?.length ? <Curve rows={performance.curve} /> : <div className="empty">正在计算收益曲线，或暂时没有可用行情</div>}</Card><Card title="手动校准持仓"><form onSubmit={save} className="form-grid"><Field label="股票代码"><input required value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} placeholder="NVDA" /></Field><Field label="名称"><input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field><Field label="数量"><input type="number" min="0" step="any" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: Number(e.target.value) })} /></Field><Field label="平均成本"><input type="number" min="0" step="any" value={form.avg_cost} onChange={(e) => setForm({ ...form, avg_cost: Number(e.target.value) })} /></Field><Button busy={busy} type="submit"><Plus size={15} />保存</Button></form></Card></div>;
}

function BacktestPage() {
  const [form, setForm] = useState({ ticker: "NVDA", start: yearsAgo(3), end: today, fast: 20, slow: 60, initial_cash: 100000, commission_pct: 0.1, slippage_pct: 0.05 });
  const [result, setResult] = useState<Json>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: string, value: string | number) => setForm({ ...form, [key]: value });
  async function run(event: FormEvent) { event.preventDefault(); setBusy(true); setError(""); try { setResult(await post<Json>("/api/v1/backtest", form)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); } }
  return <div className="stack"><Card title="SMA 双均线策略"><form onSubmit={run} className="form-grid wide"><Field label="股票代码"><input value={form.ticker} onChange={(e) => set("ticker", e.target.value.toUpperCase())} /></Field><Field label="开始日期"><input type="date" value={form.start} onChange={(e) => set("start", e.target.value)} /></Field><Field label="结束日期"><input type="date" value={form.end} onChange={(e) => set("end", e.target.value)} /></Field><Field label="快均线"><input type="number" min="2" value={form.fast} onChange={(e) => set("fast", Number(e.target.value))} /></Field><Field label="慢均线"><input type="number" min="3" value={form.slow} onChange={(e) => set("slow", Number(e.target.value))} /></Field><Field label="初始资金"><input type="number" value={form.initial_cash} onChange={(e) => set("initial_cash", Number(e.target.value))} /></Field><Field label="佣金 %"><input type="number" step="0.01" value={form.commission_pct} onChange={(e) => set("commission_pct", Number(e.target.value))} /></Field><Field label="滑点 %"><input type="number" step="0.01" value={form.slippage_pct} onChange={(e) => set("slippage_pct", Number(e.target.value))} /></Field><Button busy={busy} type="submit"><BarChart3 size={15} />运行回测</Button></form><ErrorBox error={error} /></Card>{result.ticker && <><Metrics items={[{ label: "策略收益", value: `${fmt(result.total_return_pct)}%`, tone: result.total_return_pct >= 0 ? "positive" : "negative" }, { label: "买入持有", value: `${fmt(result.benchmark_return_pct)}%` }, { label: "最大回撤", value: `${fmt(result.max_drawdown_pct)}%` }, { label: "夏普比率", value: fmt(result.sharpe) }, { label: "期末资产", value: fmt(result.final_value) }]} /><Card title={`${result.ticker} · ${result.start} 至 ${result.end}`}><Curve rows={result.curve} /><h3>交易记录</h3><Table rows={result.orders} /></Card></>}</div>;
}

function App() {
  const [page, setPage] = useState<Page>("holdings");
  const [menu, setMenu] = useState(false);
  const [backend, setBackend] = useState(false);
  useEffect(() => { get("/health").then(() => setBackend(true)).catch(() => setBackend(false)); }, []);
  const pages: Record<Page, ReactNode> = { vibe: <VibePage />, hotspots: <HotspotsPage />, dashboard: <DashboardPage />, analyze: <AgentReportPage kind="analyze" />, evolve: <EvolvePage />, holdings: <HoldingsPage />, backtest: <BacktestPage />, track: <TrackingPage />, screen: <AgentReportPage kind="screen" />, ask: <AgentReportPage kind="ask" /> };
  let lastGroup = "";
  return <div className="app-shell">
    <aside className={menu ? "sidebar open" : "sidebar"}>
      <div className="brand"><div className="brand-mark"><CircleDollarSign size={22} /></div><div><strong>Clarity</strong><span>Finance OS</span></div><button className="close-menu" onClick={() => setMenu(false)} aria-label="关闭菜单"><X /></button></div>
      <nav>{nav.map((item) => { const showGroup = item.group !== lastGroup; lastGroup = item.group; const Icon = item.icon; return <div key={item.id}>{showGroup && <div className="nav-group">{item.group}</div>}<button className={page === item.id ? "active" : ""} onClick={() => { setPage(item.id); setMenu(false); }}><Icon size={17} />{item.label}</button></div>; })}</nav>
      <div className="sidebar-foot"><span className={`status-dot ${backend ? "online" : ""}`} />Clarity API {backend ? "正常" : "离线"}</div>
    </aside>
    {menu && <button className="scrim" onClick={() => setMenu(false)} aria-label="关闭菜单" />}
    <main><header><button className="menu-button" onClick={() => setMenu(true)} aria-label="打开菜单"><Menu /></button><div><h1>{pageMeta[page][0]}</h1><p>{pageMeta[page][1]}</p></div><div className="live-pill"><Activity size={14} /> LIVE</div></header><div className="page">{pages[page]}</div></main>
  </div>;
}

export default App;

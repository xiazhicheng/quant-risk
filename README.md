# Quant-Risk

**AI 选股/风控 Skill（Claude Code · Codex · ZCode 通用）— A股+港股波段推荐与全生命周期风控。**

> 🎯 **下载即用**：一行命令安装为 AI Skill，放进 skills 目录重启即可对话使用（依赖由 AI 首次运行时自动安装，几十 MB）：
>
> ```bash
> bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)"
> # Windows: irm https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.ps1 | iex
> ```
>
> 装完后对 AI 说「推荐今日 A股+港股」或「帮我分析 600388」即可。脚本亦可直接命令行运行（见[快速开始](#快速开始)）。

> 🎯 **核心卖点一：结合持仓给调仓建议**
> 
> 输入你的持仓（对话描述/截图/记忆自动读取），系统自动诊断每只标的的风险状况，给出明确的**持有/止损/减仓/加仓**结论，并生成**调仓路线图**（Mermaid 流程图）——标注卖出哪些释放多少资金、T+2 回款时间、买入哪些标的及具体仓位比例。
>
> 🎯 **核心卖点二：一图胜千言**
>
> 所有分析报告**拒绝纯文本表格**，全部使用 Mermaid 图：
> - 🏛 **大师辩论（时序图）** — 段永平/巴菲特/芒格/李录 5 方对抗，每维度展示数据→结论→质疑→回应
> - 🔧 **技术面（流程图）** — 趋势/缠论/价量/支撑 4 个子图，数据一目了然
> - 🔥 **情绪面（用户旅程图）** — 板块/量能/价格/综合 4 阶段直观展示市场情绪
> - ⚠️ **一票否决（时序图）** — 逆向检验→镜子测试→操作建议，逐项过筛
> - 🏆 **评分总览（排名图）** — TOP10 标的横向对比，评分结构清晰
> - 🔗 **产业链全景图（流程图）** — 上中下游+竞争格局+卡脖子标注

> **V2.0（2026-09-08）**：主看 **A 股 + 港股**（美股已移出维护）。默认**纯技术波段推荐**——方向引擎从缠论整体替换为**道氏理论**（收盘价摆动点 + 高点/低点序列判趋势），四维评分（日线趋势30 + 日线量价资金25 + 日线道氏20 + 30分钟道氏25 = 100），并落地**道氏三步操作框架**（①定方向=收盘价摆动点只做多；②验健康=涨放量/回调缩量+上证深证创业板同步；③找信号=收盘价未跌破前低则趋势延续）与**三阶段定位**（吸筹/公众参与/派发，缩量新高降级）；**卖出用移动止盈替代预测目标**（跌破前低或自高回撤 2ATR 离场）；每只标的附**同花顺式三tab简介**（📋简况 / 📊财务 / 🎯看点 / 📌近期动态，港股行业/板块/公告免费源已接入）。旧六维评分+缠论 5:3:2 保留在 `--mode value` legacy 路径。

## 投资理念

> ⚠️ 以下为 **V1 价值评分体系（legacy）** 理念，保留仅供旧报告复现（`--mode value`）；**当前默认波段体系见上文 V2.0 段**（道氏四维评分 + 三档状态 + 移动止盈，纯技术筛选，不参与基本面评分）。

> **六维评分(基本面,50分) + 缠论(技术面,30分) + 热点(情绪面,20分) = 100分（5:3:2）**
>
> **强制结论制**：每项分析必须给出可操作的结论（买/卖/持有/止损），严禁"可关注""值得关注"等模糊表述。
>
> **不怕冲突**：大师视角（段永平/巴菲特/芒格/李录）之间的质疑和答辩要尖锐直接，用户喜欢看 LLM 吵架，不要和稀泥。
>
> **数据诚实**：缺失数据直接说"数据缺失"，严禁编造"暂无""—"等占位符。
>
> **扣分可见**：六维评分表中，若维度因大师质疑被扣分，评分列显示 `X.X/10 ↓-0.5`，扣分原因追加到大师视角列。
>
> **一图胜千言**：所有分析报告优先使用 Mermaid 图而非纯表格。目前包含 4 种 Mermaid 图类型：
> - **产业链全景图（流程图+子图）**：上中下游子图+竞争格局+核心财务数据，边框颜色区分层级
> - **大师辩论（时序图）**：5 参与者，每维度 6 步骤 2 轮辩论，数据源标注在节点中
> - **一票否决（时序图）**：漏斗/逆向/镜子逐项检查后汇总结论
> - **技术面/情绪面（流程图）**：4 个子图展示，每条数据标注数据源
> - 图的目的是减少文字阅读负担，表格只作为补充。
> 
> > **数据源标注**：Mermaid 图中每条数据均标注来源（数据源: 腾讯行情/东财/年报等），区分原始数据与 LLM 解读。

> **基本面一票否决**：营收<-30%、净利<-30%、PE<-10、负债率>90%、ROE<0 等 8 条规则，不达标标的在进入评分池前直接淘汰
>
> 本项目基于 [global-stock-data](https://github.com/simonlin1212/global-stock-data) 改进，在原项目「美股港股全栈数据工具包」基础上，扩展了全生命周期风控框架和缠论模块。
>
> 行业研究与产业链分析借鉴了 [ai-berkshire](https://github.com/xbtlin/ai-berkshire) 的行业研究 SOP 和行业漏斗筛选 SOP，包括四大师独立裁决框架、产业链全景图 Mermaid 输出、芒格式逆向检验、镜子测试等。
>
> 兼容 Claude Code · Codex · OpenClaw

## 快速开始

**方式一：安装为 AI Skill（推荐，下载即用）**

```bash
# macOS / Linux：一键安装到 ~/.claude/skills/quant-risk
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)"
# Windows
irm https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.ps1 | iex
# 其他客户端：install_skill.sh --dest ~/.codex/skills/quant-risk（Codex）
#                      --dest ~/.agents/skills/quant-risk（ZCode）
```

装完后**重启 AI 客户端**，对话中直接说「推荐今日 A股+港股」或「帮我分析 600388」。首次执行时 AI 会自动 `uv sync` 安装依赖（几十 MB，约 1-3 分钟）。

> 手动同步亦可：`git clone https://github.com/xiazhicheng/quant-risk.git && cp -r SKILL.md scripts ~/.claude/skills/quant-risk/`

**方式二：Docker 一键运行（零环境要求，脚本直跑）**

```bash
docker pull ghcr.io/xiazhicheng/quant-risk:latest
docker run --rm -v $(pwd)/report:/app/report quant-risk daily --markets cn,hk   # 每日信号
docker run --rm -v $(pwd)/report:/app/report quant-risk analyze 600388          # 单股分析
```

> 镜像内置 Python 3.12 + uv + 全部依赖（含 Semantica），数据源为免费公开接口无需任何 Key。`report/` 挂载到宿主机即可持久化报告/回测记录/决策凭证。

**方式三：本机直接运行 CLI（macOS / Linux / Windows）**

```bash
git clone https://github.com/xiazhicheng/quant-risk.git
cd quant-risk
bash install.sh                      # macOS/Linux：自动装 uv + Python 3.12 + 依赖
# Windows: powershell -ExecutionPolicy Bypass -File install.ps1
uv run scripts/analyze.py 03690 00268       # 分析美团+金蝶
```

**方式四：手动安装（已有 uv）**

```bash
uv sync                                         # 安装轻量依赖（默认）
uv run scripts/analyze.py 03690 00268       # 分析美团+金蝶
```

> 💡 **依赖说明**：默认 `uv sync` 安装**轻量依赖**（行情/K线/评分/回测/规则引擎，首次约几十 MB），无需任何 API Key，要求 Python 3.12+（安装脚本自动托管）。**Semantica（可选）**：需要完整影子裁决（Python 主裁决 + Semantica 影子对比 + 审计溯源）时执行 `uv sync --extra semantica`（官方全量包含 torch 等 AI 推理库，约 2.5GB）；未安装时系统自动降级为纯 Python 参考引擎（容错，功能完整）。

## ❓ 常见问题（FAQ）

**Q1：安装后跑 daily_run 全是 BLOCK / 数据缺失，是不是装坏了？**
不是。报告出现 `BLOCK：关键数据缺失/数据质量=MISSING` 是**免费数据源限流**（东财资金流/港股 30m 等公开接口高频即限流）时的 fail-closed 正常行为，系统宁可拒绝也不给假信号。稍后重跑、或分市场跑（`--markets cn` / `--markets hk`）即可恢复。

**Q2：为什么默认不装 Semantica？**
Semantica 官方全量包含 torch/faiss 等约 2.5GB AI 推理库，而本项目只用它的纯标准库 RETE。默认轻量安装（几十 MB）足够跑通全部功能（Python 主裁决 + 自动降级）；需要完整影子比对时 `uv sync --extra semantica`。

**Q3：首次运行很慢 / 卡住？**
首轮要拉全市场候选池（A股约 300 只 × 日K/30m/资金流），A股+港股串行约 1-5 分钟属正常；期间某数据源限流会有 WARN 日志，不影响其余标的。

**Q4：Windows 兼容性？**
`install.ps1` 自动装 uv + Python 3.12 + 依赖。数据层均为 HTTP 免费接口，无平台特定依赖。

**Q5：如何卸载？**
删除仓库目录即可（`rm -rf quant-risk`）；依赖装在项目内 `.venv/`，不污染系统。安装脚本创建的 uv 如需移除：`rm -rf ~/.local/bin/uv ~/.local/share/uv`。

**Q6：数据从哪来？要注册/付费吗？**
全部来自腾讯/东财/新浪/Yahoo 等免费公开接口，零注册、零 API Key。免费源高频访问有限流，属正常现象。

## MCP 接入（AI 工具调用，2026-09-09 新增）

quant-risk 提供 **MCP server**（`scripts/mcp_server.py`），把确定性操作暴露为 AI 工具（Codex / Claude Code / ZCode 直接调用，返回结构化 JSON），LLM 解读层（三tab 解读/舆情交叉验证/买卖逻辑翻译）仍由 skill 负责。**5 个工具**（全部固定 research 模式，不接实盘）：

| 工具 | 说明 | 耗时 |
|:----|:----|:----|
| `analyze_stock(code)` | 单股波段分析：四维评分/规则裁决/三档状态/止损/三tab | 30s-2min |
| `run_daily(market)` | 每日收盘工作流（单市场）：扫池→裁决→outbox→快照→报告 | 2-3min |
| `run_recommend(market)` | 波段推荐 TOP10 | 3-5min |
| `backtest_stats(days)` | 回测累计统计：胜率/分数段/状态分组 | 秒级 |
| `get_daily_report(market, date)` | 读取已生成 daily 报告全文 | 秒级 |

**接入方式一：本地 stdio（默认，推荐）**

仓库已内置配置，AI 工具自动发现：
- **ZCode**：`.zcode/config.json` 已配置（`uv run scripts/mcp_server.py`），重启 ZCode 生效
- **Claude Code**：`.mcp.json` 已配置
- **Codex**：`~/.codex/config.toml` 加 `[mcp_servers.quant-risk] command="uv" args=["run","scripts/mcp_server.py"]`

**接入方式二：Streamable HTTP（远程 / Docker / 局域网）**

```bash
uv run scripts/mcp_server.py --transport http --host 0.0.0.0 --port 8765   # 服务端
# Docker 场景（镜像已内置）：
docker run -d --name quant-risk-mcp -p 8765:8765 \
  -v $(pwd)/report:/app/report quant-risk:latest \
  scripts/mcp_server.py --transport http --host 0.0.0.0 --port 8765
```

客户端接入（`.mcp.json` / ZCode / Codex，任选其一）：

```json
{ "mcpServers": { "quant-risk": { "type": "http", "url": "http://127.0.0.1:8765/mcp" } } }
```

不支持原生 http 的客户端用 `mcp-remote` 桥（与 anysearch 同模式）：

```json
{ "mcpServers": { "quant-risk": { "command": "npx", "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp"] } } }
```

> ⚠️ 远程部署注意：streamable-http 端点在局域网/公网暴露时需自行加鉴权（token/防火墙），默认只建议 `127.0.0.1` 或内网。

## 项目结构

```
quant-risk/
├── scripts/                       # 所有代码统一在此目录
│   ├── analyze.py                 # 统一多市场分析入口（港股/A股/美股）
│   ├── analyze_swing.py           # 🎯 单股波段分析（A股/港股，复用 swing 评分核心）
│   ├── recommend.py               # 统一推荐入口：--market hk|cn|us（默认 swing 波段模式）
│   ├── portfolio.py               # 持仓诊断：uv run scripts/portfolio.py diagnose
│   ├── portfolio_report.py        # 🔥 持仓完整报告：产业链Mermaid+四大师+缠论+行业漏斗
│   ├── tech_chan.py               # 🔥 缠论深度分析 + 产业链Mermaid 输出
│   ├── tech_detail.py             # 详细技术面分析（四大师+技术面完整报告）
│   ├── chan_mtf.py                # 缠论多周期联立
│   ├── news_pulse.py              # 股价异动快速归因（14天回溯，量价+板块+公告）
│   ├── financial_rigor.py         # 金融数据精度验证（市值/估值精确验算+多源交叉验证）
│   ├── formatter.py               # 选股推荐格式化器 (Pydantic + 渲染)
│   ├── formatters/                # 四阶段风控格式化器
│   │   ├── __init__.py
│   │   ├── _base.py               # 共享基础
│   │   ├── _pretrade.py           # 投前审查
│   │   ├── _holding.py            # 持仓监控
│   │   ├── _alert.py              # 预警触发
│   │   └── _disposal.py           # 处置决策
│   └── quantrisk/                 # Python 包（scripts/quantrisk 子包）
│       ├── __init__.py            # 包入口
│       ├── recommender.py         # 共享评分/过滤引擎（meso_filter + fundamental_veto + fb/hot/ch_score）
│       ├── recommend_hk.py        # 港股选股推荐适配器
│       ├── recommend_cn.py        # A 股选股推荐适配器
│       ├── recommend_us.py        # 美股选股推荐适配器
│       ├── swing.py               # 纯技术波段评分引擎（日线趋势/量价/笔 + 30分钟线段）
│       ├── data.py                # 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC
│       ├── chan.py                # 缠论：分型→笔→线段→中枢→背驰→买卖点
│       ├── indicators.py          # 技术指标：MA/MACD/RSI/KDJ/BOLL + 支撑压力/止损止盈
│       ├── chain_renderer.py      # 产业链渲染器：Mermaid 图文本生成（纯渲染）
│       ├── screener.py            # 标的池筛选 + 批量查询
│       └── report.py              # StockAnalyzer 一键全量分析入口
├── SKILL.md                       # Skill 主定义（数据函数 + 风控模板）
├── AGENTS.md                      # 项目约定和设计决策
├── CHANGELOG.md                   # 版本记录
├── openwiki/                      # 开放知识库文档
└── README.md                      # 本文件
```

## 架构

```
共 11 层数据源 + 缠论层 + 三维风控框架

┌─ 投前审查 ─ 持仓监控 ─ 预警触发 ─ 处置决策 ─┐
│                                              │
│  数据层  data.py                              │
│  ├── 行情层    腾讯/新浪/东财 push2/mootdx    │
│  ├── K线层     腾讯(ifzq)/新浪/AYahoo/百度/TickFlow(兜底) │
│  ├── 基本面    东财/Yahoo/SEC EDGAR/同花顺    │
│  ├── 资金面    东财 push2his/两融/大宗/股东    │
│  ├── 信号层    同花顺/龙虎榜/北向/板块归属     │
│  ├── 公告层    巨潮 cninfo                    │
│  ├── 期权层    Yahoo（仅美股）                │
│  ├── SEC Filing EDGAR（仅美股）               │
│  └── 工具层    搜索/新闻/CIK/全市场列表        │
│                                              │
│  共享引擎  recommender.py                    │
	│  ├── 中观过滤   meso_filter(市值/股价硬约束)  │
│  ├── 基本面否决  fundamental_veto(营收/净利/PE/负债率等8条)│
		│  ├── 六维评分    _raw_score_one(6维度,等权求和,满分50分)   │
		│  ├── 热点评分    hot_score(满分20分)                       │
		│  └── 缠论评分    chan_score(满分30分,周线定势+日线定点)    │
│                                              │
│  分析层                                        │
│  ├── 技术指标  indicators.py (MA/MACD/RSI/KDJ)│
│  ├── 缠论     chan.py (分型→笔→中枢→买卖点)   │
│  └── 报告     report.py (StockAnalyzer)        │
│                                              │
│  市场适配器                                    │
│  ├── recommend_hk.py  港股（动态300+候选池）  │
│  ├── recommend_cn.py  A股（市值排序500只）     │
│  └── recommend_us.py  美股（S&P 500 核心）    │
└──────────────────────────────────────────────┘
```

## 波段推荐体系（A股/港股默认）

A股与港股默认运行**纯技术波段模式**，单一策略 `swing_band`，**持有时间不预设**（高抛低吸，由道氏破前低/移动止盈离场信号自然决定；`max_holding_days=60` 仅作风控上界）。评分不使用 PE、ROE、负债率、营收或净利，也不会因这些基本面字段否决标的。硬规则由 Python reference 执行，Semantica（可选）以 shadow/声明式 RETE 方式复核并记录决策链。

| 维度 | 满分 | 用途 |
|------|:----:|------|
| 日线趋势 | 30 | MA5/10/20/60 排列、价格位置、MACD 动能 |
| 日线量价/资金 | 25 | 近5日涨跌、量比、主力资金流 |
| 日线道氏 | 20 | **道氏次级趋势**：摆动点序列（高点抬高+低点抬高=升势），替代原缠论"日线笔" |
| 30分钟道氏 | 25 | **道氏小趋势**：30m 摆动点判方向，确认短线入场（缺失或与日线冲突则观望） |

**入场硬规则：** 日线道氏上升趋势为入场基础；30分钟数据为**入场优化**（有已确认30m且方向up→参与评分，缺失→不阻断、仅日线裁决，30m与日线冲突→仍观望）。要求已收盘 K 线、关键行情/指数/资金数据完整；指数或资金流缺失时禁止新开仓。

**道氏三步操作框架（2026-09-08 用户框架）：**
1. **①定方向** —— 日线**收盘价**摆动点判趋势（原则6：日内高低点是噪音，只关注收盘价）。高点/低点持续抬高 = 上升趋势（只做多）；下降/盘整 = 空仓观望。
2. **②验健康** —— 涨放量、回调缩量 = 健康（成交量确认趋势）；**A股主要指数严格同向**（上证/深证/创业板任一方向不一致即背离，禁止新开仓）；港股恒指作环境展示。
3. **③找信号** —— 以收盘价确认是否跌破最近回调低点：未跌破 = 趋势延续继续持有；跌破 = 上升趋势结束离场。
外加**三阶段定位**（吸筹/公众参与/派发）：缩量新高 = 派发迹象（强弩之末）强制降级——第二阶段可重仓、第三阶段准备跑。

**止损/移动止盈（2026-09-01 ATR 止损；09-08 移动止盈替代预测目标）：** 固定比例对波动率差异大的股票失真。`swing.py` 的 `swing_sl_tp()` 按 ATR14 计算：
- **止损** = max(现价 − 2×ATR, 摆动低点×0.985)，clamp 到 **-5%~-11%**（低波动自动收窄、高波动自动放宽）；ATR 缺失回退 -8%
- **卖出用移动止盈，不预测目标价**（道氏只描述趋势状态不预测价格）：① 跌破最近已确认的道氏前低（收盘价确认）离场；② 持仓后从**自入场以来最高收盘价**回撤 ATR 阈值离场
- 渲染展示：`止损X.XX（-Y.Y%）| 移动止盈：跌破前低Z或自高点W回撤P%离场`

**30分钟K线源链（2026-09-07 修复 Yahoo 限流）：** A股：Yahoo → 东财 push2his → 新浪 → 腾讯 mkline → mootdx；港股：Yahoo → 东财（腾讯/新浪无港股分钟接口）。任一源取到 ≥40 根即用，source 如实标注。

**风控过滤（自动）：** ST/*ST/退市股硬拦截；次新股（日K<250根）警示；候选池覆盖全市场代码段（含科创板688），按市值取前300。

```bash
uv sync                                              # 安装全部依赖（含 Semantica 官方包）
uv run scripts/recommend.py --market hk --strategy band --rule-engine shadow  # 港股波段
uv run scripts/recommend.py --market cn --rule-engine shadow                   # A股波段（默认band）
uv run scripts/daily_run.py                          # 每日收盘工作流（A股+港股，无 LLM 依赖）
uv run scripts/recommend.py --market hk --mode value  # 旧价值评分兼容模式
```

**Semantica 是必须依赖**（2026-09-09 起）：`uv sync` 默认安装官方 semantica==0.6.8（Python 主裁决 + Semantica RETE 影子交叉验证 + 审计溯源），首次下载约 **2.5GB**（含 torch/transformers/faiss 等 AI 推理库）。万一缺失（如 pip 只装核心），系统自动降级为纯 Python 参考引擎（报告头部显示 `规则：python`），评分/裁决/回测/落库不受影响——容错设计，不是可选项。⚠️ 未装 Semantica 时请勿使用 `--rule-engine semantica`——系统会 fail-closed 全部 BLOCK（故意的安全行为）。

## 价值评分体系（legacy）

`--mode value` 保留旧的六维基本面(50) + 缠论(30) + 热点(20) 三维评分链，供兼容与对照；它不再是A股与港股默认推荐逻辑。

## 使用示例

### 市场分析

```bash
uv run scripts/analyze.py 03690              # 港股 美团单只
uv run scripts/analyze.py 03690 00268 00700  # 批量
uv run scripts/analyze.py 03690 --json       # JSON输出
uv run scripts/analyze.py 600309             # A股 万华化学
uv run scripts/analyze.py AAPL               # 美股 苹果
```

### 个股波段分析（A股/港股）

```bash
uv run scripts/analyze_swing.py 600388       # A股 紫金龙净
uv run scripts/analyze_swing.py 03968        # 港股 招商银行（5位代码）
uv run scripts/analyze_swing.py 600018 01258 # 批量
```

与 `recommend.py --market cn/hk --mode swing` 同源（复用 `swing.py` 评分核心 + `data.py` 数据层），仅将"全市场扫描"改为"指定个股"：输出波段四维评分（日线趋势30+量价资金25+日线道氏20+30分钟道氏25）+ 道氏结论（规则八三要素）+ 布局状态 + 三tab简介 + 三刀筛辅助数据。

### 统一推荐（全市场扫描）

```bash
uv run scripts/recommend.py --market hk --strategy band --rule-engine shadow
uv run scripts/recommend.py --market cn --rule-engine shadow
uv run scripts/backtest_swing.py --record report/recommend-cn-20260908.md  # 兼容T+N研究统计
uv run scripts/backtest_swing.py --report --days 5,10,20
uv run scripts/backtest_swing.py --engine-report report/paper_trades.jsonl # 事件回放：扣成本/回撤/PF/持有天数分布
```

### 持仓诊断

```bash
uv run scripts/portfolio.py diagnose         # 持仓风险诊断（卖出评分）
uv run scripts/portfolio_report.py           # 🔥 持仓完整报告（产业链+四大师+缠论）
```

### Python 直接调用

```python
from scripts.quantrisk.report import StockAnalyzer
import asyncio

async def main():
    a = StockAnalyzer()
    # 港股
    meituan = await a.analyze_hk("03690")
    print(meituan["quote"]["price"], meituan["technicals"]["chan"]["chan_verdict"])
    # A股
    wly = await a.analyze_cn("000858")
    # 美股
    aapl = await a.analyze_us("AAPL")
    await a.close()

asyncio.run(main())
```

### Claude Code Skill 用法

| 场景 | 提示词 |
|------|--------|
| 投前审查 | 帮我做美团的投前风控审查 |
| 持仓检查 | 检查一下我持仓的美团风险状况 |
	| 预警响应 | 美团跌到止损线了，帮我看看要不要执行 |
	| 处置决策 | 我要清仓美团，给个处置方案 |
	| 批量审查 | 帮我审查阿里腾讯美团 3 只股票 |
	| 综合评分 | 给美团做综合评分（基本面+技术面）|

## 持仓完整报告（一键生成）

一句话「结合我的持仓，给我投资建议」，自动生成完整报告：

### 🔥 `uv run scripts/portfolio_report.py`

自动输出 8 大模块：

| 模块 | 内容 |
|:----|:------|
| **📊 组合总览** | 投入/市值/盈亏/集中度/健康度 |
| **🔧 产业链全景图** | Mermaid 格式（上游→中游→下游+竞争格局），卡脖子环节标注 |
| **🏢 四大师独立裁决** | 段永平/巴菲特/芒格/李录各自评分 + 追问 + 投票制结论 |
| **📊 行业漏斗5条硬指标** | PE/ROE/营收/净利/负债率逐条检查 |
| **⚠️ 芒格式逆向检验** | 公司级+行业级风险清单，含历史类比 |
| **🔧 缠论深度分析** | 周线定势 → 日线走势/笔/中枢/背驰/买卖点 |
| **📋 镜子测试** | 5句话说清楚为什么买 |
| **🧠 AI偏见自查** | 龙头偏好/英文偏好/故事偏好等5种自查 |

> 整合自 [ai-berkshire](https://github.com/xbtlin/ai-berkshire) 的行业研究 SOP 和行业漏斗筛选 SOP。

### 持仓投资建议

根据用户持仓信息，自动分析每只标的的风险状况，给出持有/减仓/卖出/加仓建议。

### 持仓信息输入方式（三种途径）

| 方式 | 示例 | 说明 |
|------|------|------|
| 🗣️ **对话中描述** | "我的持仓是美团1000股、腾讯500股" | 直接说出持仓明细，系统自动分析 |
| 🖼️ **图片上传** | 券商持仓截图 | 多模态大模型可自动识别图片中的持仓信息（如股数、成本价、盈亏） |
| 💾 **记忆系统自动保存** | 上一次会话中已提供过持仓 | 系统自动保存到 AgentMemory，下次无需重复输入 |

### 分析内容

一旦获取持仓信息，系统自动为每只标的输出：

| 维度 | 内容 |
|------|------|
| 📊 **六维评分** | 营收增速、ROE、毛利率、负债率、PE、净利同比、PB、股息率、净利率（6维度等权） |
| 🔧 **缠论(技术面)** | MA排列、MACD金叉/死叉、买卖点信号、周线大势 |
| 🔥 **热点(情绪面)** | 板块资金排名、个股资金流向、板块龙头、成交量、20日动量 |
| 📈 **操作建议** | 持有 / 减仓 / 卖出 / 加仓 + 具体理由（MA排列/MACD/资金流向） |

### 实操示例

```bash
# 命令行持仓诊断
uv run scripts/portfolio.py diagnose

# 或通过 AI 对话：直接说"帮我看看我的持仓"
```

> 💡 **持仓信息自动持久化**：一旦提供过持仓，系统会自动保存到记忆系统，下次会话无需重复输入。

## 依赖

项目使用 `pyproject.toml` 管理依赖，`uv` 会自动读取：

```bash
# 所有依赖已声明在 pyproject.toml 中，一行安装：
uv sync

# 依赖清单（版本已锁定）
# aiohttp==3.14.1       异步 HTTP — 数据层并行请求
# pydantic>=2.13.4      格式化器校验引擎
# tickflow==0.1.24      免费 K 线数据（备用源）
# mootdx>=0.11.7        A 股 K 线（备选源）
# requests>=2.34.2      同步 HTTP 请求
```

**Python 版本**: ≥ 3.12（已声明在 `.python-version`）

## 数据源汇总

| 数据源 | 协议 | 鉴权 | 覆盖 |
|--------|------|------|------|
| 东财 push2/datacenter | HTTPS | 零 | A股+美股+港股 行情/资金流/基本面 |
| 腾讯财经 | HTTPS | 零 | A股+美股+港股 行情；A股/港股日K前复权(ifzq.gtimg.cn) |
| 新浪财经 | HTTP | 零 | 美股/港股行情+美股K线+A股日K+三表 |
| 百度股市通 | HTTP | 零 | A股日K线（带MA）|
| Yahoo Finance | HTTPS | crumb自动 | 美股+港股 日K/30分钟K线 |
| TickFlow | HTTPS | 零 | A股+港股+美股 日K（最终兜底，已降级，8s超时快速失败）|
| 同花顺 | HTTP | 零 | 强势股/一致预期EPS |
| 巨潮 cninfo | HTTP | 零 | A股公告 |
| SEC EDGAR | HTTPS | 零 | 美股 Filing+XBRL |
| mootdx | TCP | 零 | A股K线/财务快照 |

> ⚠️ 2026-08-31 数据源调整：TickFlow（`free-api.tickflow.org` 连接不稳定）已降级为最终兜底源，所有 K 线 fallback 链前端有腾讯/新浪/百度/Yahoo 兜底，TickFlow 极少触发。新增新浪 A 股日 K（`CN_MarketData.getKLineData`）作为腾讯之后的第二源。新浪港股日 K 接口已失效，港股日 K 依赖腾讯+Yahoo。
>
> ⚠️ 2026-08-31 资金流限流修复：东财 fflow 资金流接口高并发下（如两市场脚本并行执行、400+ 只同时拉取）会**静默返回空数组**，导致波段报告"主力5日"显示 +0.00亿（实际是数据缺失而非资金为零）。`fund_flow_daily_async` 已加**全局限流信号量（并发 5）** + 空返回指数退避重试（0.5s/1s/2s，4 轮），所有资金流调用方统一受控。并行执行两市场脚本实测主力资金全部恢复真实值。另注意：部分 A 股小盘（如 600241/600318/600348）东财 fflow 本身无覆盖，长期显示 +0.00亿属数据源覆盖问题，非限流。

## 更新

```bash
git pull origin main
```

## last30days 舆情与资金热点辅助技能

集成 [last30days-skill](https://github.com/mvanhorn/last30days-skill)（v3.21.1）作为独立舆情辅助技能，辅助判断**市场舆情和资金热点**。

### 能力

跨平台并行搜索"过去 30 天人们在说什么"，按**真实人类参与度**（upvotes / likes / 真金白银赔率）评分，合成带引用的简报：

- **金融情绪源**：StockTwits（个股讨论）、Polymarket（真金白银赔率）、Reddit 投资社区
- **通用舆情源**：X/Twitter、YouTube、Hacker News、GitHub、TikTok、Instagram、arXiv、Techmeme
- 免费源（Reddit / HN / Polymarket / GitHub）零配置可用

### 安装位置

技能已软链到 ZCode 用户级技能目录 `~/.agents/skills/last30days/`，源仓库缓存在 `~/.zcode/cli/skills-cache/last30days-skill/`，便于 `git pull` 更新。

### 用法

重启 ZCode 会话后，直接用 `/last30days` 触发：

```
/last30days 港股银行板块 资金流向舆情
/last30days A股种业板块 近期讨论热度
/last30days nvidia earnings reaction
```

依赖：Python 3.12+（uv 已集成）、yt-dlp（YouTube 字幕）、Node.js（X 搜索）。yt-dlp 缺失只影响 YouTube 源，不阻塞其他源。

> 📡 适用场景：`uv run scripts/recommend.py` 输出波段 TOP10 后，用 `/last30days` 对主线板块做舆情验证，交叉确认资金情绪方向。

## FAQ

- **需要安装什么依赖？** 一键完成：`bash install.sh`（macOS/Linux）或 `powershell -ExecutionPolicy Bypass -File install.ps1`（Windows）——自动装 uv + Python 3.12 + 全部依赖（含 Semantica，首次约 2.5GB）。已有 uv 则 `uv sync` 即可，依赖清单在 `pyproject.toml`（aiohttp / pydantic / tickflow / mootdx / requests / semantica / …）。
- **Semantica 必须装吗？** 是必须依赖，`uv sync`/安装脚本自动安装（官方 semantica==0.6.8，Python 主裁决 + Semantica RETE 影子对比 + 审计溯源）。万一缺失系统自动降级为纯 Python 参考引擎，功能不受影响（容错）。装不上/不想装 AI 推理库？用 Docker 镜像（已内置）。
- **不用 uv 怎么装？** `pip install -e .`（需 Python 3.12+，自动解析含 Semantica 的全部依赖）。所有数据源为免费公开 HTTP 接口，无需注册、无需 API Key。
- **不用 Claude Code 能用吗？** 能，`uv run scripts/analyze.py 03690` 直接运行。
- **和 a-stock-data 有什么关系？** 本项目 V1.1.0 将 a-stock-data 的 A 股接口封装融入风控框架。
- **和 global-stock-data 有什么关系？** 本项目 fork 自 global-stock-data，在其数据层基础上扩展了风控框架和缠论模块。
- **和 ai-berkshire 有什么关系？** 借鉴了 [ai-berkshire](https://github.com/xbtlin/ai-berkshire) 的四大师独立裁决框架、行业研究 SOP（产业研究）和行业漏斗筛选 SOP（行业漏斗），以及芒格式逆向检验、镜子测试等分析工具。
- **Yahoo Finance 需要 API Key 吗？** 不需要，代码自动获取 crumb。
- **支持实盘交易吗？** 不，本项目仅提供风控分析工具，不连接任何交易接口。
- **持仓信息每次都要重新说吗？** 不需要。系统会自动保存持仓信息到记忆系统（AgentMemory），下次会话直接分析，无需重复输入。

## 作者

**土豆爸爸** — 公众号：**土豆爸爸讲科普**

## 赞赏

如果这个工具帮到了你的投研工作流，欢迎请作者喝杯咖啡 ☕

<div align="center">
  <img src="asset/reward.jpg" alt="赞赏码" width="200"/>
</div>

## Disclaimer

本项目仅提供数据获取与风控分析工具，不构成任何投资建议。股市有风险，投资需谨慎。

## License

Apache License 2.0 — 自由使用，注明出处即可。

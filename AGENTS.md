# quant-risk — 全生命周期风控 Skill

## 项目定位

Codex Skill，覆盖 **美股 + A 股 + 港股** 全生命周期风控：投前审查 → 持仓监控 → 预警触发 → 处置决策。

## 核心约定

- **Python 包管理**: 用 `uv add` 不用 pip
- **执行 Python**: 用 `uv run`
- **记忆系统**: AgentMemory（行为记忆） + OpenKnowledge（文档知识）双轨制
- **数据分析方法**: 三维评分 → 总得分 100 分。基本面 50 分(50%权重) > 热点 30 分(30%权重) > 缠论 20 分(20%权重)
- **📌 投资理念铁律（2026-07-20 用户明确）**：**基本面为主、技术面为辅、结合当前热点**。代码实现和所有分析必须严格贯彻此优先级——基本面权重最大(50%)且是入场决策的第一筛选条件，技术面仅作为择时参考(20%)，热点用于判断市场主线方向(30%)。**任何时候都不能只看技术面买入，基本面不合格的标的必须一票否决。** 评分阈值（≥70强烈关注）已经体现了"基本面好+热点好+技术面好"三高共振才强烈推荐的逻辑。
- **⛔ 输出格式铁律**: 脚本输出的报告必须原样展示，严禁在末尾追加手写表格或自定义分析。所有格式统一由脚本的 formatter 控制，改格式只改文件不改输出。需要补充分析时，放在脚本输出之后并用 `---` 分隔线隔开并写明"以下为补充说明"。**此规则已写入知识库 `llm_wiki/articles/quant-risk-output-format-rules.md`，每次行动前必读。**
- **📌 脚本输出粘贴强制检查（反复踩坑）**：执行脚本后，**第一步必须把 Bash/工具返回的脚本完整输出逐字复制到回复正文中**，不能只写"脚本输出完毕"就跳过。常见错误：模型拿到了工具结果但在 compose 回复时忘了粘贴，直接跳到补充说明。**写回复前自问：工具返回的每一行内容都贴到正文里了吗？确认后再发送。**
- **⛔ 脚本输出绝不加 ``` 代码块（2026-07-17 新增，已反复踩坑多次）**：脚本输出本身是 markdown（含 `|` 表格），**直接粘贴到回复正文**，绝不能包在 ``` 代码块里——加了代码块表格就会变成纯文本，渲染不出来。这条是最高优先级，已更新知识库 `articles/quant-risk-output-format-rules.md`。**写回复前自检：脚本输出的每一行都在正文中、没有被 ``` 包裹。**
- **🏷️ LLM 补充分析必须标注数据来源**（2026-07-17 新增）：在 `---` 分隔线之后的"补充说明"中，**必须标明每条信息来源**。基于脚本输出的解读写 `> 📡 数据来源: 基于脚本输出解读`；通过 web_search 独立查询的数据写 `> 📡 数据来源: web_search [URL]`。读者必须能区分哪些是原始数据、哪些是 LLM 的二次解读、哪些是外部检索补充的内容。
- **✅ 脚本输出展示标准流程（2026-07-17 新增，反复踩坑后固化）**：脚本输出必须通过 **文件落地 + Read 工具读取** 的方式展示，**禁止依赖 Bash 工具返回的 stdout 直接粘贴**（Bash 输出在某些视图下不可见）。标准三步流程：① `uv run scripts/analyze.py <code> > /tmp/report.md 2>&1` 运行脚本并把输出重定向到文件；② 用 Read 工具读取 `/tmp/report.md` 显示完整内容；③ 在 `---` 分隔线后追加 LLM 补充说明。**此流程是新会话也必须遵守的铁律，不可跳过。**

## 用户持仓读取顺序

当需要获取用户持仓信息时，按以下优先级依次查找，找到即停：

1. **当前会话上下文** — 用户在本轮对话中已提及的持仓
2. **外部记忆系统** — AgentMemory（通过 MCP JSON-RPC 协议调用 `memory_recall`，**查询方法详见知识库** `/Users/xiazhicheng/project/llm_wiki/articles/agentmemory-mcp-query-method.md`），搜索关键词 `portfolio` / `持仓` / `holding`
3. **询问用户** — 以上均无数据时，要求用户自行提供持仓信息

## 用户持仓自动保存规则

**触发时机**（满足任一即执行保存）：

1. **用户主动提供或更新持仓信息时** — 用户明确说出"我的持仓是..."、"买入/卖出了XX"等
2. **持仓诊断/风控分析完成后** — 分析结果涉及持仓变动建议时
3. **会话结束时** — 本会话中持仓信息发生过变更

**保存操作（写入 AgentMemory）：**

通过 MCP JSON-RPC 调用 `memory_save`，参数：
   - `content`: 完整的持仓 JSON 内容（账户总览 + 各标的明细）
   - `type`: `"preference"`
   - `concepts`: `["portfolio", "持仓", user_name, ...]`

**注意：** 不要等待用户说"保存"才执行。上述触发时机到来时，自动执行保存。

## 架构速览 (V1.6.0)

所有代码统一在 `scripts/` 目录下，`quantrisk` 作为 `scripts/quantrisk/` 子包存在。

```
scripts/
├── analyze_hk.py              港股全量分析脚本
├── portfolio.py               持仓诊断工具
├── chan_mtf.py                缠论多周期联立分析
├── formatter.py               选股推荐格式化器 (Pydantic + 渲染)
├── formatters/                四阶段风控格式化器
│   ├── __init__.py
│   ├── _base.py               共享: FormatValidationError + 校验/渲染工具
│   ├── _pretrade.py           投前审查: format_pretrade()
│   ├── _holding.py            持仓监控: format_holding()
│   ├── _alert.py              预警触发: format_alert()
│   └── _disposal.py           处置决策: format_disposal()
└── quantrisk/                 Python 模块（scripts/quantrisk 子包）
    ├── recommend_hk.py        港股选股推荐适配器
    ├── recommend_cn.py        A股选股推荐适配器
    ├── recommend_us.py        美股选股推荐适配器
    ├── recommender.py         共享过滤/评分引擎
    ├── data.py                数据层 — 行情/K线/基本面/资金面/信号/公告/期权/SEC/工具 + TickFlow
    ├── chan.py                缠论 — 分型→笔→线段→中枢→背驰→买卖点
    ├── indicators.py          技术指标 — MA/MACD/RSI/KDJ/BOLL + 缠论 re-export
    ├── screener.py            标的池筛选 + 批量查询
    ├── report.py              StockAnalyzer 一键全量分析入口
    └── __init__.py            包入口
```

## 数据源优先级

| 数据类型 | 主源 | 备选 | 备注 |
|---------|------|------|------|
| A股行情 | 腾讯(不封IP) | 东财 push2 | — |
| A股日K | 腾讯(前复权) | 百度(带MA) / mootdx / TickFlow | — |
| 港股行情 | 腾讯(78字段) | 新浪(25字段) | — |
| 港股日K | Yahoo | **TickFlow**(备选) | Yahoo港股经常缺数据 |
| 美股行情 | 腾讯(71字段) | 新浪(36字段) | — |
| 美股日K | 新浪 / Yahoo | TickFlow(备选) | — |
| 基本面(港股A股) | 东财 datacenter | Yahoo(key stats) | — |
| 基本面(美股) | Yahoo | — | — |
| 缠论K线 | Yahoo / 腾讯 / 新浪 | **TickFlow**(数据最全) | TickFlow支持前复权 |

**TickFlow** (免费免注册): 官方 SDK `pip install tickflow`，`TickFlow.free()` 模式
- 免费提供历史日K/周K/月K/季K/年K，无需 API Key
- 支持 A股(`.SH`/`.SZ`/`.BJ`) + 港股(`.HK`) + 美股(`.US`)
- 支持前复权 (`adjust=True`)
- 不支持实时行情和分钟级K线（free模式）
- 文档: https://docs.tickflow.org

## 关键设计决策

- **代码从 SKILL.md 提取为 Python 模块**: V1.2.0 将之前散落在 SKILL.md 文本中的函数正式提取为可导入的 Python 包。V1.6.0 进一步重构评分系统为 100 分制、增加基本面 debug 明细、选股→定价→择时三段式输出、持仓择时判断。
- **所有代码统一在 scripts/ 目录**: 脚本入口 `scripts/*.py`，Python 模块 `scripts/quantrisk/*.py`，不再保留顶层 `quantrisk/` 目录
- **data.py 四合一**: HTTP 会话管理 + 行情层(8函数) + K线层(6函数) + 基本面/资金面/信号等(30函数)合并为一个文件，GitHub 浏览一目了然
- **scripts/ 入口**: 可直接 `uv run scripts/analyze_hk.py 03690` 运行，无需 pip install
- **A股行情主力**: 腾讯 (不封IP) > 东财 push2
- **A股日K**: 腾讯 (前复权) > 百度 (带MA) / mootdx (多周期)
- **缠论背驰**: MACD面积对比, 阈值15%, 强背驰50%
- **缠论中枢**: 至少3段重叠 (min_overlap=3)
- **标准化笔**: 分型间距≥4根K线, 同向取极端值
- **数据获取**: 全部 aiohttp 异步, batch_*() 并行查询
- **标的池筛选**: 四层流程：①宏观扫描(板块排名→候选池) → ②中观过滤(市值/股价硬约束) → ③基本面一票否决(营收< -30%或净利< -30%或PE严重负值直接淘汰，贯彻"基本面为主") → ④微观评分(基本面×10+热点×6+缠论×4，满分100)
- **评分系统 V2（2026-07-20 重构）**:
  - 基础分从 3.0 降到 2.0，每个维度分 5-7 个 tier，调整幅度 ±1.0~2.0
  - 新增基本面维度：PB 市净率、股息率、净利率（从腾讯行情78字段提取）
  - 权重公式：`fb_w = fb_pct×10 + hot_w = hot_pct×6 + ch_w = ch_pct×4`，满分 100 分
  - 百分位排名（`percentile_score_all`）在**未 clamp 的原始分**上操作，扩大区分度
  - 热点评分细化：板块排名/个股资金流向/20日动量各 5-8 档
  - 新增 20 日累计资金流向分析（`batch_hk_capital_flow_20d_async`）
  - 建议阈值：≥70 强烈关注，≥56 可关注，≥44 观察，<44 回避
- **基本面一票否决（2026-07-20 新增）**：
  - 在评分之前增加 `fundamental_veto()` 关卡，严重基本面恶化的标的不进评分池
  - 否决条件：营收同比<-30% 或 净利同比<-30% 或 PE<-10（严重亏损）
  - 否决记录在报告中"②.5 基本面一票否决"段落独立展示
  - 贯彻"基本面为主"理念：技术面和热点再强，基本面崩塌的股票也不推荐
- **输出格式「选股→定价→择时」三段式（2026-07-20 新增）**:
  - 第一步：选股（全市场扫描→中观过滤→TOP10 排名→各股评分明细）
  - 第二步：定价（入场区间→止损→目标价→估值分析）
  - 第三步：择时（推荐标的买入时机 + **持仓卖出判断**）
  - 基本面评分在详情页展示完整计算链（如 `基础2.0+营收35.5%(>30%→+1.5)+...`）
- **持仓卖出判断（2026-07-20 新增）**:
  - 当用户提供持仓信息后，择时步骤自动分析每只持仓的卖出时机
  - 输出格式：持有/减仓/卖出/加仓 + 具体理由（MA排列/MACD/资金流向）
  - 数据格式：`format_output(data, market)` 的 data 中传入 `portfolio_timing` 列表
  - 详见 `formatter.py` 的 `PortfolioTimingItem` 模型和 `_render_portfolio_timing()` 函数
- **缠论深度分析嵌入推荐模板（2026-07-21 新增）**:
  - 推荐报告的缠论部分从简略摘要升级为**周线大势 + 日K买卖点 + 笔结构**三层深度分析
  - **周线定大势**：从腾讯获取周K数据，计算周线MA60状态和缠论判定（偏多/中性/偏空）
  - **日K定买卖点**：从 `chan_risk_assessment` 提取最近底分型/顶分型价格与日期、是否站上MA5、最近笔方向
  - **买卖点 + 背驰**：展示一买/二买/三买/卖点详情，以及顶背驰/底背驰（强/弱）信号
  - 渲染位置：详情页"论据"段落后缩进展示，择时论据中追加"缠论"子段落
  - 核心数据流：`chan.py` → `chan_risk_assessment`（新增 fractals/strokes 字段）→ `recommender.py chan_score`（提取为 cd 字典）→ `recommend_hk.py build_selection_data`（填入 ch 字典）→ `formatter.py ChanDetail` 模型 → `_render_detail_block` / `_render_timing_block` 渲染
  - **关键文件变更**：`chan.py`(fractals/strokes输出) + `recommender.py`(chan_score提取深度数据) + `recommend_hk.py`(周线获取+数据传递) + `formatter.py`(ChanDetail扩展+渲染)
- **风控输出**: 每个阶段必须有明确结论 (买入/观望/拒绝 等)
- **港股行情财务字段扩展**: `hk_stock_quote_tencent_async()` 从腾讯78字段中提取10个财务字段(PE_TTM/ROE/毛利率/净利率/营收增长率/负债率/股息率)，无需额外API调用
- **推荐股票强制规则**: SKILL.md 中定义的3步强制流程(跨板块全市场扫描8板块→中观硬约束过滤→微观三维评分TOP10)，含固定输出模板，禁止跳过任何一步或单板块推荐

## 文件清单

| 文件/目录 | 用途 |
|-----------|------|
| SKILL.md | Skill 主定义 (数据函数 + 风控模板) |
| README.md | 项目说明 |
| CHANGELOG.md | 版本记录 |
| AGENTS.md | 本文件（项目约定和设计决策）|
| scripts/analyze_hk.py | 港股全量分析脚本 |
| scripts/quantrisk/recommend_hk.py | 港股选股推荐适配器 |
| scripts/quantrisk/recommend_cn.py | A股选股推荐适配器 |
| scripts/quantrisk/recommend_us.py | 美股选股推荐适配器 |
| scripts/portfolio.py | 持仓诊断工具 |
| scripts/chan_mtf.py | 缠论多周期联立分析 |
| scripts/formatter.py | 选股推荐格式化器 |
| scripts/formatters/ | 四阶段风控格式化器 |
| scripts/quantrisk/data.py | 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC/工具 + TickFlow |
| scripts/quantrisk/chan.py | 缠论：分型→笔→线段→中枢→背驰→买卖点 |
| scripts/quantrisk/indicators.py | 技术指标：MA/MACD/RSI/KDJ/BOLL/支撑压力/止损止盈 |
| scripts/quantrisk/screener.py | 标的池三层筛选 + 批量查询 |
| scripts/quantrisk/report.py | StockAnalyzer 全量分析入口 |

## 分析框架

三维评分体系（100 分制，2026-07-20 重构）：

| 维度 | 权重 | 满分 | 评分(1-5) | 核心问题 |
|------|:----:|:----:|:---------:|---------|
| 📊 基本面 | 50% | 50 | 1-5 | 估值合理吗？盈利质量如何？财务健康吗？ |
| 🔥 热点 | 30% | 30 | 1-5 | 是否在市场主线？有催化剂吗？ |
| 🔧 缠论 | 20% | 20 | 1-5 | 结构位置在哪？有买卖点信号吗？ |

**满分**：基本面 50 + 热点 30 + 缠论 20 = **100 分**

**评分流程**：
1. 原始分计算（`fb_score`/`hot_score`/`chan_score`）— 基础分 2.0，各维度加减分
2. 池内百分位排名（`percentile_score_all`）— 映射到 1~5
3. 加权得分：`fb_w = 百分位×10`，`hot_w = 百分位×6`，`ch_w = 百分位×4`
4. 总分 = `fb_w + hot_w + ch_w`

**建议阈值**：≥70 强烈关注 | ≥56 可关注 | ≥44 观察 | <44 回避

**基本面评分维度**（9 个，数据来源：腾讯行情 + 东财基本面）：
营收增速、ROE、毛利率、负债率、PE 相对估值（行业阈值）、净利同比、PB 市净率、股息率、净利率

**热点评分维度**（6 个）：
板块资金排名、个股资金流向、板块龙头、成交量、20 日动量、20 日累计资金流向

**缠论评分维度**（4 个）：
MA 排列（7 档）、MACD 金叉/死叉、MA 交叉（MA5/MA20/MA60）、缠论买卖点信号

**输出格式**（2026-07-20 重构为三段式）：
- 第一步：**选股** — 全市场扫描 → 中观过滤 → TOP10 评分明细（含基本面计算链）
- 第二步：**定价** — 入场区间 → 止损 → 目标价 → 综合建议表
- 第三步：**择时** — MA排列 → MACD → 资金流向 → 买卖时机建议

## OpenWiki

This repository has documentation located in the /openwiki directory.

Start here:
- [OpenWiki quickstart](openwiki/quickstart.md)

OpenWiki includes repository overview, architecture notes, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

When working in this repository, read the OpenWiki quickstart first, then follow its links to the relevant architecture, workflow, domain, operation, and testing notes.

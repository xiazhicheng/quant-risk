# Changelog

## V1.12.0 (2026-09-24) — 基本面门禁（只否决不加分）+ 滞后性纪律扣分降档双轨 + stale 文档清理

### 基本面门禁（grill Q1/Q5/Q6/Q11 共识，新增 `scripts/quantrisk/gate.py`）

- 基本面**只否决不加分**：不进 100 分评分（评分保持纯技术 30/25/20/25）；评分完成后**后置**评估（候选≤80只/市场 + 持仓，不扫全池，防东财限流）
- 规则分市场：A股严（净利为负/负债率>70%/营收同比<-20%/ST退市）｜港股松（退市风险/负债率>80%）；**金融业（银行/证券/保险/信托）豁免负债率规则**（notes 留痕，净利/营收/ST 照常）；财务缺失 fail-open 不否决（回测归"未评估"）
- 接入面：`swing.py` TOP10 剔除 veto + ⛔否决表 + 逐只门禁行 + `swing_validate` 拦截；`backtest_swing` veto 字段解析 + 门禁分组 + Q13 通过线判定（通过组T+20高于否决组≥2pp 且 PF≥旧策略、回撤恶化≤1pp）；`backtest_snapshot` gate 分组；`portfolio_report` 持仓"不加仓"标注（卖出仍归道氏 `_dow_verdict()`）；`analyze_swing` 单股同源评估 + ⛔状态封顶 + 上车条件"禁止新建仓"分支；`daily` 摘要门禁统计

### 滞后性纪律扣分+降档双轨（grill Q7/Q12）

- `swing_score_one` 三条纪律代码化：①动能走弱 日线趋势-6 ②高位放量滞涨（60日≥85%分位+量比>2x+当日涨幅<1%）量价-6 ③高位横盘（高位区连续≥10日振幅<4%）日线趋势-4
- 扣分写回维度分+reason 标注 `⚠️XX扣N分`，明细进 `result["discipline"]`；状态封顶"谨慎布局"，**规则引擎 ALLOW 不可翻回**（封顶在 facade 后二次生效，BLOCK/EXIT 不受影响）

### stale 文档清理（grill Q9/Q10）

- 命名与口径统一：AGENTS.md「日线笔/30分钟线段」→「日线道氏/30分钟道氏」、"基本面不参与一票否决"改为门禁铁律、缠论6/20旧诊断话术；swing-system.md L40 30m缺失口径（缺失→观望，原"不BLOCK"表述易误读）、Q2 条目升级双轨、评分表头命名、新增门禁条目；data-sources.md 缠论诊断话术
- 代码文档：formatter.py TOP10 表头 60/20/20→50/30/20（与 summary 表头 5:3:2 对齐）；recommend.py/portfolio_report.py/recommend_cn/hk docstring 去四大师旧承诺；report legend「缺失不阻断」→「缺失则观望」；README/SKILL 门禁口径
- 测试：全量 **158 通过**（+2 skipped semantica），全离线：`test_gate.py` 22 条（含金融业豁免 4 条、单股门禁 4 条）+ 滞后性纪律 `test_discipline_*` 4 条

---

## V1.11.0 (2026-09-24) — 持仓调仓逻辑全道氏化（投委会辩论移除 + 硬编码修复）

### 调仓裁决：六维评分/投委会辩论 → 道氏信号（portfolio_report.py）

- **用户明确要求**：「组合调仓的建议逻辑要大改，根据现在的道氏理论来改，不要大模型专家辩论了，那个没啥用」
- 新增 `_dow_verdict()`：按道氏三步映射持仓动作——日线下降 + 收盘破前低 → 🔴清仓；下降未破前低 → 🟡反弹至前高减半；日线震荡 → 🟡持有观察（边界定生死）；日线上升 + 动能走弱预警 → 🟡减半（滞后性纪律）；上升 + 缩量 → 🟡持有；上升 + 放量健康 → 🟢持有。**六维评分不再参与任何调仓判断**
- 删除投委会辩论：`_pm_master_debate()`（163 行）与 `_safe_float()` 一并移除；逐只渲染改为「🎯 道氏持仓裁决」（方向/量能/边界/裁决/触发价）
- `dow_detail_output()` 新增结构化返回字段 `direction/previous_low/previous_high/stage/health/divergence/vol_ratio`，供裁决层消费
- 板块替换：「组合优化建议」（六维<30 且亏损>20% 才止损）→「🎯 道氏持仓裁决总表」；「AI偏见自查清单」（硬编码标的条目）→「🔍 数据源自查」

### 硬编码修复

- **调仓路线图买入端不再写死**：原为 `01308 海丰国际` / `02698 乐舒适` / `03888 减仓 9600HKD`（上一轮持仓的残留，换持仓即全错），改为新增 `_load_top_picks()` 自动读取 `report/recommend-{cn,hk}-<date>-daily.md` 的每市场 TOP2（跳过「观望」），无报告时提示先跑 `daily_run.py`
- A股持仓名称回退修复：`analyze_holding` 名称解析加入 `result.get("name")`，解决 `002640` 显示为代码而非「跨境通」的问题
- 「基本面分析」→「基本面背景（不参与调仓裁决）」，无产业链数据时不再输出空标题

### 测试与文档

- 全量 **132 用例通过**（+2 skipped semantica 可选）；真实持仓（华润饮料/金山软件/跨境通）端到端验证：报告 490 → 312 行，无投委会/六维/偏见残留
- 同步 AGENTS.md（主题文档索引、投资建议模板、架构速览）+ `docs/agents/value-legacy.md`（portfolio_report 章节重写）
- 仍保留 legacy 路径：`--sixdim-json` / `--sixdim-render`（JSON 管道六维渲染）未随本次清理

---

## V1.10.0 (2026-09-21) — 持仓报告道氏化收敛 + TypeSafe jev 外部裁决 + 依赖清理

### 持仓报告技术面：缠论 → 道氏（portfolio_report.py）

- 调仓组合报告技术面整体收敛为道氏理论（2026-09-21 用户明确）：日线 `chan_detail_output`（笔/中枢/背驰/买卖点）→ `dow_detail_output`（道氏结论/摆动点/边界/趋势健康/三阶段，复用 swing.py 道氏核心）；周线缠论判定 → 道氏判定（周线摆动点判涨跌/震荡）
- 风控从固定止盈改为道氏移动止盈（ATR 止损 + 跌破前低/自高点回撤离场，不预测目标），与波段系统 `swing_sl_tp` 对齐
- 六维评分/投委会/产业链/情绪面保留（value legacy 逻辑）；同步更新 AGENTS.md 投资建议模板技术面段落、value-legacy/swing-system 文档

### TypeSafe jev 外部 AI 裁决（新增 scripts/jev_advice.py）

- 持仓买卖裁决双引擎：复用 analyze_swing 信号管线打包 state + questions（Choice/Score/Noul 三类结构化问题），调 `jev-latest` 独立裁决 buy/hold/reduce/sell + 组合风险
- **jev 非必需（降级设计）**：typesafe-sdk 未装 / 无 key / 调用失败时自动降级 `local_dow_action` 纯规则裁决（离场/道氏 down→sell，双 up→buy，冲突/派发→reduce，其余→hold），永不崩溃
- API key 存项目根 `.env`（已 gitignore），脚本 `_load_dotenv` 零依赖自动加载
- 主题文档 `docs/agents/jev-advice.md`：state/questions 写法规范 + 三类问题 + 降级映射 + 踩坑记录

### 依赖清理与安全

- **移除 mootdx**（其 tenacity<9 与 typesafe-sdk 的 >=9 冲突）：删 data.py 四个同步函数（30m 兜底/TDX K线/财务快照）+ 30m 源链 mootdx 段，A股基本面兜底 东财→Yahoo 两级；30m 源链收敛 Yahoo→东财→新浪→腾讯；同步 tests/test_30m_data.py（3 处）、recommend_cn.py 注释、README/docs 引用
- **安装 typesafe-sdk 0.7.0**（tenacity 升 9.1.4）
- .gitignore 新增 `.env`（API key）与 `.kimi-code/`（本地 AI 配置，含已跟踪的 mcp.json 解除跟踪）

### 测试

- 新增 tests/test_jev_advice.py（12 用例：state/questions 构建 + local_dow_action 全分支降级），全量 **132 用例通过**（+2 skipped semantica 可选）

---

## V1.9.0 (2026-09-19) — 数据可靠性加固 + CLI 硬化 + 文档一致性

### 数据可靠性加固（切片1）

- 新增港股日K统一入口 `hk_kline_async`（data.py）：腾讯 → Yahoo 两级兜底，fail-closed（两源全挂显式报错，绝不静默伪造）；收敛 5 处手写重复兜底（analyze_swing / backtest_swing / recommend_hk / portfolio）
- 静默异常日志化：`hk_fundamentals_async` 3 处 + `cn_key_indicators_async` F10 段 `except: pass` 全部加 WARN 日志
- `_get`/`_get_json` 检查 HTTP 状态码（≥400 返回空）+ JSON 解析失败不抛异常——上游限流页/HTML 不再炸调用方
- 实测记录：Yahoo chart API 对本机出口 IP 429 限流（含 crumb 流程），Yahoo 兜底为"保险"性质，网络恢复即自动生效
- 修复 `mcp_server.py` 模块级 `builtins.print` 劫持全局副作用（改为仅 stdio 运行时生效）

### CLI 硬化（切片3）

- **`analyze.py --json` 首次可用**：修复两个历史 bug——① `import json` 在 `if not json_mode` 分支内导致 UnboundLocalError；② 缠论对象图循环引用（`KLine._elements`）无法 json.dumps，新增 `_json_safe()` 通用剪环
- 未知 `--` 参数从静默忽略改为报错退出（analyze_swing.py / analyze.py）

### 文档一致性（A 层）

- SKILL.md：美股 5 处章节（行情/K线/期权/SEC）+ 缠论层标 `⚠️ DEPRECATED`；take_profit 与移动止盈决策冲突标注；腾讯 URL 501 事故域名 http→https；frontmatter 版本统一 V1.9.0
- AGENTS.md 架构速览版本号同步 V1.9.0
- CHANGELOG 补记 V1.3~V2.0 六版欠账（git 历史归档）
- 新增测试：test_hk_kline（8）/ test_fundamentals（3）/ test_cli_args（4），全量 123 用例通过

---

## V1.7.0 (2026-09-18) — 道氏波段体系 + Skill 分发重构 + MCP + 混合规则架构

> 补记（2026-09-18 从 git 历史归档 V1.3~V2.0 欠账记录，此前 CHANGELOG 仅到 V1.2.0）。原 V2.0 tag 已移除，其变更并入本版（09-08 至 09-18 全部变更）。

### 波段方向判定引擎换代（道氏替代缠论）

- 缠论（笔/线段/中枢/背驰）→ **道氏理论**：摆动点检测（`_find_pivots`）+ 道氏三句话（`_dow_trend`）+ 明确边界结论（跌破前低转空/突破前高延续）
- 评分框架（30/25/20/25）、三档状态、ATR 止损、三tab 简介全部不变
- 旧函数名 `daily_stroke_score`/`intraday_segment_score` 保留兼容别名
- `chan.py` 保留供 value/portfolio 模式使用

### 数据链路修复

- **30m K线源链化根治**：Yahoo/东财限流时 A股自动兜底 新浪/腾讯mkline/mootdx（5 源链），港股 Yahoo→东财
- **东财 fflow 限流根治**：信号量并发 + 指数退避，静默空数组不再吞
- 修复 30 分钟线段方向误判（strokes→segments 语义）

### 风控与输出

- ATR14 动态止损替代固定 -8%/+10%；**移动止盈替代预测目标**（跌破道氏前低或自高点回撤 2×ATR 离场），不再输出 take_profit/target_pct
- 新增单股波段分析脚本 `analyze_swing.py`（A股/港股，复用 swing 评分核心）

### 分发形态

- **Skill 分发重构**：`install_skill.sh`/`install_skill.ps1` 一键装为 AI Skill（下载即用），Docker 镜像（GHCR 多架构 amd64+arm64 CI）+ 本地一键安装为备选
- 仓库清理：不携带用户本地数据（`data/`/`report/`/`ve.pptx` 全部 gitignore/出库）
- README 重写为零成本 A股+港股 Skill 定位

### 架构

- **V2.1 混合规则架构**：单策略 `swing_band`（高抛低吸、持有时间由道氏+移动止盈自然决定）+ Semantica 影子裁决/决策溯源（Python 主裁决）+ 资金 MISSING fail-closed + 持有天数分布回测（`backtest_engine.py`）
- **MCP server**（`mcp_server.py`）：5 工具（analyze_stock/run_daily/run_recommend/backtest_stats/get_daily_report），双 transport（stdio + Streamable HTTP），ZCode/Claude Code 适配
- **每日收盘工作流** `daily_run.py`（无 LLM 依赖）：扫池→裁决→outbox 落库→冻结快照→报告→回测记录
- 候选池改进：A股成交额降序取 300 + 热门板块池补充（`fetch_hot_boards` + board_hot 标记）

### 修复与硬化

- **港股 f[74] 负债率误映射修复**：实为杠杆率（映美 5965%/腾讯 -28.41/东亚 51.52 均失真）→ 移除映射 + fail-closed 标「数据缺失」+ 渲染 0-100% 护栏
- 上车/离场条件固化：状态必须带触发价，禁止只输出"谨慎布局/观望"
- 新增快照回测 `backtest_snapshot.py`（全量 80 只/天，无幸存者偏差）
- 腾讯 78 字段负债率移除（f[74] 映射删除）

---

## V1.6.0 (2026-08-28) — 波段推荐 + 缠论评分体系

- A股+港股**纯技术波段推荐模式**（`--mode swing`）首版
- **腾讯 K 线域名 501 修复**：`web.ifzq.gtimg.cn` 失效 → `ifzq.gtimg.cn` 多域名降级（HTTPS 硬要求）
- 三维评分 5:3:2 + 缠论周线定势日线定点
- A股数据链路修复 + 近5日资金流热点评分
- 结论先行输出模板（规则八）
- 六维评分 Mermaid 图 + 产业链 YAML → `chain_renderer.py` 纯渲染
- `analyze.py` 复用 `portfolio_report.py` 统一模板（六维+产业链+漏斗+镜子测试）

---

## V1.5.0 (2026-07-17)

- 跨市场推荐引擎（A股+港股+美股统一架构）
- TickFlow 初始化 banner 抑制
- 表格数据来源标注 + LLM 补充分析来源标注铁律（规则四）

---

## V1.4.0 (2026-07-16)

- 代码迁移至 `scripts/` 统一目录（analyze.py 等）
- 输出格式铁律强化：脚本原样展示、禁止追加手写内容（规则一）

---

## V1.3.0 (2026-07-16)

- 港股推荐候选池 114 → 300+ 动态扩充（`fetch_dynamic_pool`）
- 港股资金流 API 限流修复 + 基本面评分逻辑
- 资金流热点评分 + 港股 K 线优先级调整 + Layer 7 公告层

---

## V1.2.0 (2026-07-08)

### 缠论层 (Chan Theory) — 新增 （V1.2.0-1）

完整的缠中说禅（Chan Theory）技术分析实现，纯 Python 计算，基于现有 K 线数据，无需额外 API：

- **K 线包含处理** — `kline_contain()`: 向上取高高 / 向下取低低，消除K线包含关系
- **分型识别** — `find_fractals()`: 识别顶分型（3K中高最高）和底分型（3K中低最低）
- **笔的构建** — `build_strokes()`: 相邻顶底分型交替连接，去重同向分型取极端值，标准笔≥5根K线
- **线段构建** — `build_segments()`: 至少3笔重叠构成线段，特征序列包含处理
- **中枢识别** — `find_pivots()`: 滑动窗口识别≥3段重叠区间，返回 zg/zd/zz_width
- **趋势分类** — `classify_trend()`: 0中枢=单边，1中枢=盘整，≥2中枢=趋势
- **背驰检测** — `detect_divergence()`: MACD 面积对比 + 力度衰减，区分顶背驰/底背驰及强弱
- **买卖点定位** — `find_buy_sell_points()`: 一买/一卖（背驰终结点）、二买/二卖（回调确认）、三买/三卖（中枢突破回踩）
- **全功能计算** — `chan_theory_full()`: 一键完成包含处理 → 分型 → 笔 → 线段 → 中枢 → 背驰 → 买卖点
- **风控集成** — `chan_risk_assessment()`: 输出缠论评分 / 偏多偏空判断 / 买卖点信号 / 相对中枢位置

### 代码提取为 Python 模块（V1.2.0-2）

将 SKILL.md 中全部数据函数（行情/K线/基本面/资金面/信号/公告/期权/SEC/工具/技术指标）正式提取为可导入的 Python 模块，消除临时脚本 copy-paste：

- **data.py** (615行) — 四合一数据层：HTTP会话 + 行情8函数 + K线6函数 + 基本面/资金面/信号等30函数
- **indicators.py** (316行) — 技术指标：MA/MACD/RSI/KDJ/BOLL/支撑压力/止损止盈 + 缠论re-export
- **screener.py** (113行) — 标的池三层筛选 + `batch_hk_quotes()` / `batch_hk_full()` 批量查询
- **report.py** (236行) — `StockAnalyzer` 类，提供 `analyze_hk()` / `analyze_cn()` / `analyze_us()` / `analyze_hk_batch()` 一键全量分析
- **scripts/analyze_hk.py** — 可直接运行的入口脚本：`uv run scripts/analyze_hk.py 03690`

#### 文件整理

- 删除旧模块：`client.py` / `quotes.py` / `kline.py` / `fundamental.py` → 合并为 `data.py`
- 删除 `pyproject.toml` / `egg-info`，无需 pip install，`uv run` 直接使用
- `chan.py` 保持不变（已在 V1.2.0-1 中建立）

### 分析框架优化

- 确立三维评分体系：**基本面(权重5) > 热点(权重3) > 缠论(权重2)**，满分50
- 分析思路：基本面为估值锚 → 技术面辅助择时 → 热点是关键催化剂
- 文档同步更新：CLAUDE.md / README.md / CHANGELOG.md

---

## V1.1.0 (2026-07-03)

### A 股数据源支持（重大更新）

基于 [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) 的接口设计，在现有美股+港股架构上扩充 A 股支持，新增 **6 层 20+ 个数据端点**，架构从 8 层扩展为 11 层。

#### 新增 Layer

- **Layer 1 行情层** — `cn_stock_quote_tencent_async()` / `cn_stock_quote_eastmoney_async()` / `cn_stock_basic_info_async()`，腾讯（不封IP）为主力 A 股行情源，47 字段含 PE/PB/市值/换手率/涨跌停价
- **Layer 2 K 线层** — `cn_stock_kline_tencent_async()`（腾讯前复权）/ `cn_stock_kline_baidu_async()`（百度带MA5/10/20）/ `cn_stock_kline_tdx_sync()`（mootdx 多周期分钟/日/周/月）
- **Layer 4 基本面层** — `cn_key_indicators_async()`（东财 datacenter）/ `cn_financial_statements_sina_async()`（新浪三表）/ `cn_eps_forecast_sync()`（同花顺一致预期 EPS）/ `cn_financial_snapshot_sync()`（mootdx 财务快照 37 字段）
- **Layer 5 资金面层** — `cn_fund_flow_minute_async()`（资金流）/ `cn_margin_trading_async()`（融资融券）/ `cn_block_trade_async()`（大宗交易）/ `cn_holder_num_change_async()`（股东户数）/ `cn_dividend_history_async()`（分红送转）
- **Layer 6 信号层（A 股独有）** — `ths_hot_stocks_async()`（强势股+题材归因）/ `northbound_flow_async()`（北向资金）/ `cn_concept_blocks_async()`（板块归属）/ `cn_dragon_tiger_board_async()`（龙虎榜）/ `cn_lockup_expiry_async()`（解禁预警）/ `cn_industry_ranking_async()`（行业排名）
- **Layer 8 公告层（A 股独有）** — `cninfo_announcements_async()`（巨潮 cninfo 沪深北全量公告检索）

#### 基础设施变更

- 新增 `cn_market_prefix()` / `cn_secid()` 市场前缀辅助函数
- 新增 `_tdx_client()` mootdx TCP 客户端（含服务器探测和 fallback）
- 可选依赖 `mootdx`（A 股 K 线/财务快照）

#### 文档更新

- README.md：更新架构图（11 层）、端点列表（40+）、数据源汇总表、使用示例
- SKILL.md：更新触发关键词（A 股/沪深/龙虎榜/北向/融资融券等）
- 数据源优先级表增加 A 股场景

#### 兼容性

- 完全向后兼容，现有美股/港股代码未做任何修改
- A 股函数全部以 `cn_` 前缀命名，与现有函数区分清晰
- mootdx 为可选依赖，不安装不影响现有功能

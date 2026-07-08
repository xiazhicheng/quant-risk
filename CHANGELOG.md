# Changelog

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

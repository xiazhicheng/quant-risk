# Changelog

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

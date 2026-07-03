# Quant-Risk

全生命周期量化风控工具 — **投前审查 / 持仓监控 / 预警触发 / 处置决策** 四阶段全覆盖。支持 **美股 + A 股 + 港股** 三大市场。

基于十一层数据源架构（行情、K线、基本面、资金面、信号层、公告层、期权、SEC Filing），结合 ATR 技术指标与全生命周期风控框架，输出风险评估、仓位建议、止损止盈触发条件。

> 本项目基于 [global-stock-data](https://github.com/simonlin1212/global-stock-data) 改进，在原项目「美股港股全栈数据工具包」基础上，扩展了全生命周期风控框架。V1.1.0 新增 A 股支持（基于[a-stock-data](https://github.com/simonlin1212/a-stock-data))。
>
> 兼容 Claude Code · Codex · OpenClaw


## 架构

```
全生命周期风控 · 十一层数据 · 四阶段架构 · V1.1.0
│
├── 投前审查（Pre-trade）  审查能否入场，预设止损止盈
├── 持仓监控（Holding）    持续监控风险，检查离场条件
├── 预警触发（Alert）      警报触发，紧急基本面检查
├── 处置决策（Disposal）   多方案对比，制定退出计划
│
├── 行情层      腾讯(sh/sz/r_hk/us) + 新浪(gb_/rt_hk) + 东财push2 + mootdx(A股)
├── K线层       腾讯(A股前复权) + 新浪(美股) + 百度(带MA) + Yahoo + mootdx
├── 技术指标    MA/EMA + MACD + RSI + KDJ + 布林带 + ATR + 支撑/压力
├── 基本面      东财datacenter + mootdx快照 + 新浪三表 + 同花顺一致预期 + Yahoo + SEC XBRL
├── 资金面      东财push2his + 东财datacenter(两融/大宗/股东/分红)
├── 信号层(A股)  同花顺强势股+题材+北向+东财板块归属+龙虎榜+解禁+行业排名
├── 公告层(A股)  巨潮 cninfo
├── 期权层      Yahoo crumb（仅美股）
├── SEC Filing  EDGAR submissions + XBRL（仅美股）
└── 工具层      东财search+push2列表 + Yahoo search + SEC CIK映射
```

## 快速开始

**3 步，2 分钟。**

```bash
mkdir -p ~/.claude/skills/quant-risk
curl -o ~/.claude/skills/quant-risk/SKILL.md \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/SKILL.md
pip install aiohttp
```

启动 Claude Code，说一句「帮我做腾讯的风控审查」，自动激活。

> **Codex / OpenClaw 用户：** 把 SKILL.md 的内容贴入你的系统 prompt 或项目上下文文件即可。

## 四阶段能力清单

### 阶段一：投前审查（Pre-trade）

审查标的能否入场，输出完整的风控参数预设。

| 输出 | 说明 |
|------|------|
| 风险等级 | 低/中/较高/高，五维评分（估值/盈利/财务/成长/流动性）|
| 建议仓位上限 | 基于风险等级的仓位比例上限 |
| 预设止损位 | ATR(14) × 2，跌破则离场 |
| 预设止盈位 | ATR(14) × 3，分档止盈 |
| 行业基本面 | 景气度 / 政策环境 / 竞争格局 / 产业链地位 |
| 审查结论 | 买入 / 观望 / 拒绝 |

### 阶段二：持仓监控（Holding）

持有期间的持续风险追踪。

| 输出 | 说明 |
|------|------|
| 浮动盈亏 | 持仓成本 vs 当前价格 |
| 距止损距离 | 当前价格距止损线的百分比 |
| 风险变化趋势 | PE/成交额/行业景气度的环比变化 |
| 离场条件检查 | 止损/止盈/盈利保护/基本面预警逐项检查 |
| 操作建议 | 继续持有 / 减仓至 X% / 增持 / 清仓 |

### 阶段三：预警触发（Alert）

价格触及预设线或基本面突变时的紧急响应。

| 输出 | 说明 |
|------|------|
| 触发详情 | 当前价格 / 预设线 / 偏离幅度 |
| 紧急基本面检查 | 财报日期 / 近期利空 / 行业系统性风险 / 成交量异常 |
| 处置建议 | 执行止损 / 部分减仓 / 持有观察 / 反向加仓 |
| 执行优先级 | 高/中/低 + 时限（立即/本日/本周）|

### 阶段四：处置决策（Disposal）

决定退出后的具体执行方案。

| 输出 | 说明 |
|------|------|
| 方案对比 | 一次性清仓 / 分批退出 / 减仓留底仓 / 转仓 |
| 执行计划 | 市价/限价/条件单 + 分批明细 |
| 再配置建议 | 资金释放后的配置方向 |
| 经验记录 | 本轮交易经验教训 |

## 40+ 个数据端点

### 行情层（实时/延时）

| 端点 | 数据 |
|------|------|
| 腾讯财经 | A股 sh/sz 47字段 / 港股 78字段 / 美股 71字段 |
| 新浪财经 | 美股 36 字段（含中文名/EPS/PE）|
| 东财 push2 | A股 secid:0-1 / 美股 secid:105-107 / 港股 secid:116 |
| mootdx | A 股五档盘口 + 逐笔成交（TCP 直连）|

### K线层

| 端点 | 数据 |
|------|------|
| 腾讯 | A股日K前复权，带MA5/10/20 |
| 新浪 | 美股日K线，回溯至 1984 年 |
| Yahoo chart | 美股 + 港股，v8 API 零 crumb |
| 百度 | A 股日K线，直接返回 MA5/10/20 均价 |
| mootdx | A 股多周期 K 线（分钟/日/周/月）|

### 技术指标层（纯计算）

MA/EMA + MACD(DIF/DEA/柱状图) + RSI(6/12/24) + KDJ(K/D/J) + 布林带 + ATR(14) + 支撑/压力位

### 基本面

| 端点 | 数据 |
|------|------|
| 东财 datacenter 三表 | 美股/港股/A股三表，中文科目名 |
| 东财 GMAININDICATOR | 关键财务指标（美股49字段/港股75字段/A股同等）|
| mootdx finance | A 股季报 37 字段（EPS/ROE/净利润/营收）|
| 新浪 | A 股三表（资产负债表/利润表/现金流量表）|
| 同花顺 basic | A 股机构一致预期 EPS |
| Yahoo quoteSummary | 23 个模块（财务数据 + 关键指标 + 分析师 + 机构持仓）|
| SEC EDGAR XBRL | 503 个 GAAP 指标（仅美股）|

### 资金面

| 端点 | 数据 |
|------|------|
| 东财 push2his | 日级主力/大单/中单/小单净流入，覆盖 A 股+美股+港股 |
| 东财 datacenter | A 股融资融券 / 大宗交易 / 股东户数 / 分红送转 |

### 信号层（A 股独有）

| 端点 | 数据 |
|------|------|
| 同花顺 | 当日强势股 + 题材归因 |
| 东财 push2 ulist | 北向资金分钟级流向 |
| 东财 slist | 个股所属板块（行业/概念/地域）|
| 东财 datacenter | 龙虎榜席位 + 限售解禁 |
| 东财 push2 clist | 行业板块涨跌排名 |

### 公告层（A 股独有）

巨潮 cninfo：沪深北全量公告检索

### 期权层（仅美股）

Yahoo options：期权链 calls + puts，所有到期日，含 Greeks

### SEC Filing 层（仅美股）

EDGAR submissions（10-K/10-Q/8-K 列表）+ EDGAR XBRL（结构化财务指标）

### 工具层

东财 search / 东财 push2 列表（美股5925+ / 港股18000+）/ Yahoo search（新闻）/ SEC CIK mapping

### 鉴权要求

全部数据源完全免费无 Key（iwencai 除外）。Yahoo crumb 由代码自动获取，SEC EDGAR 仅需标准 User-Agent。mootdx 走 TCP 直连通达信服务器。

## 使用示例

| 场景 | 提示词 |
|------|--------|
| 投前审查(A股) | 帮我做贵州茅台的投前风控审查 |
| 投前审查(美股) | 帮我做腾讯的投前风控审查 |
| 持仓检查 | 检查一下我持仓的阿里的风险状况 |
| 预警响应 | 腾讯跌到止损线了，帮我看看要不要执行 |
| 处置决策 | 我要清仓泡泡玛特，给个处置方案 |
| 批量审查 | 帮我审查阿里百度腾讯 3 只股票的风控 |
| 止损计算 | 美团现价 70.8，帮我算止损止盈位 |
| 基本面评分 | 给巨子生物做五维风险评分 |
| 龙虎榜 | 看看 300750 最近龙虎榜情况 |
| 北向资金 | 今天北向资金流入情况怎么样 |
| 板块归属 | 688017 属于哪些概念板块 |
| 行业排名 | 今天哪些行业涨得最好 |
| 一致预期 | 600519 的机构一致预期 EPS 是多少 |
| 公告检索 | 查一下比亚迪最近的公告 |

## V1.1 亮点（新增）

- **A 股全覆盖**：新增 A 股行情/K线/基本面/资金面/信号层/公告层 6 层 20+ 新端点
- **腾讯优先**：A 股行情走腾讯（不封 IP），47 字段含 PE/PB/市值/换手率/涨跌停价
- **A 股 K 线三源**：腾讯前复权 + 百度带 MA + mootdx 多周期
- **A 股专属信号**：强势股/题材归因/北向资金/龙虎榜/解禁/行业排名
- **公告检索**：巨潮 cninfo 沪深北全量公告
- **板块归属**：东财 slist 一次请求拿全个股所属概念板块

## V1.0 亮点

- **全生命周期**：投前 / 持仓 / 预警 / 处置 四阶段一体的风控框架
- **全异步**：aiohttp 异步并行，批量 15 只股票行情+基本面 1-2 秒完成
- **全零鉴权**：全部数据源免费无 Key，Yahoo crumb 自动获取
- **内置 ATR**：止损止盈触发条件自动计算，无需外部依赖
- **支撑/压力位**：EMA 平滑算法，基于实时 K 线计算
- **五维评分**：估值 / 盈利 / 财务 / 成长 / 流动性
- **行业景气度判断**：行业环境 / 竞争格局 / 产业链地位

## 数据源优先级

| 场景 | 第一优先 | 备选 |
|------|---------|------|
| 港股行情 | 腾讯 r_hkXXXXX（78字段）| 新浪 / 东财 push2 |
| 美股行情 | 新浪 gb_XXXX（36字段）| 腾讯 / 东财 push2 |
| 美股K线 | 新浪 | Yahoo chart |
| 港股K线 | Yahoo chart | — |
| 关键指标（中文） | 东财 GMAININDICATOR | — |
| 关键指标（英文） | Yahoo quoteSummary | — |
| 财报三表（中文） | 东财 datacenter | — |
| 分析师/机构 | Yahoo quoteSummary | — |
| 资金流 | 东财 push2his | — |
| 期权链 | Yahoo options（仅美股）| — |
| SEC Filing | EDGAR（仅美股）| — |
| 搜索 | 东财 search | Yahoo search |
| 全市场列表 | 东财 push2 clist | — |

## 数据源汇总

| 数据源 | 协议 | 鉴权 | 覆盖 |
|--------|------|------|------|
| 东财 push2/push2his | HTTPS | 零 | A股+美股+港股 行情/资金流/行业排名 |
| 东财 datacenter | HTTPS | 零 | A股+美股+港股 财报/龙虎榜/两融/大宗/股东/分红/解禁 |
| 东财 search API/slist | HTTPS | 零 | 全球股票搜索+secid映射+板块归属 |
| 腾讯财经 | HTTPS | 零 | A股+美股+港股 实时行情（不封IP）|
| 新浪财经 | HTTP | 零 | A股三表+美股行情/港股行情+美股K线 |
| 百度股市通 | HTTP | 零 | A股日K线（带MA均价）|
| 同花顺 | HTTP | 零（需UA）| A股强势股/涨停原因/一致预期EPS |
| 巨潮 cninfo | HTTP | 零（需UA）| A股全量公告 |
| Yahoo Finance | HTTPS | cookie+crumb（自动）| 美股+港股 全品类 |
| SEC EDGAR | HTTPS | 零（需UA）| 美股 Filing+XBRL |
| mootdx | TCP | 零 | A股 K线/盘口/财务快照/F10（不封IP）|

## 依赖

```bash
pip install aiohttp
# A 股数据（可选，需要 A 股 K 线/财务快照时安装）
pip install mootdx
```

## 快速开始

**3 步，2 分钟。**

```bash
mkdir -p ~/.claude/skills/quant-risk
curl -o ~/.claude/skills/quant-risk/SKILL.md \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/SKILL.md
pip install aiohttp
```

## FAQ

**Q: 需要安装什么依赖？**
基础依赖仅 `aiohttp`。如果要使用 A 股 K 线和财务快照，还需要安装 `mootdx`（`pip install mootdx`）。

**Q: 和 a-stock-data 有什么关系？**
[simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) 是独立的 A 股数据工具包。本项目 V1.1.0 将其 10 层 A 股 API 封装融入风控框架。

**Q: A 股数据在国内能正常跑吗？**
能。A 股数据源（腾讯/东财/同花顺/巨潮/mootdx）在国内直连速度很快。mootdx 走 TCP 直连通达信服务器。

**Q: 和 global-stock-data 有什么关系？**
本项目 fork 自 [global-stock-data](https://github.com/simonlin1212/global-stock-data)，在原项目的数据层基础上，扩展了全生命周期风控框架、ATR 止损止盈计算、支撑/压力位分析、四阶段输出模板等风控专属功能。

**Q: Yahoo Finance 需要 API Key 吗？**
不需要。代码自动获取 cookie + crumb。

**Q: 在国内服务器能跑吗？**
Yahoo Finance 和 SEC EDGAR 是境外服务，国内直连可能不稳定。建议走代理。

**Q: 不用 Claude Code，能用吗？**
能。SKILL.md 本质是 Markdown + 内嵌 Python。Codex、OpenClaw 或任何 AI 编程助手都能读取。

**Q: 支持实盘交易吗？**
本项目仅提供风控分析工具，不构成投资建议，不连接任何交易接口。

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

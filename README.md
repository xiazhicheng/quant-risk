# Quant-Risk

全生命周期量化风控工具 — **投前审查 / 持仓监控 / 预警触发 / 处置决策** 四阶段全覆盖。

支持 **美股 + A 股 + 港股** 三大市场，基于 **基本面为主(60%) + 技术面为辅(40%，含热点+缠论)** 的二维评分体系。

## 投资理念

> **基本面为主（60%）→ 技术面为辅（40%，含热点+缠论各一半）**
>
> **强制结论制**：每项分析必须给出可操作的结论（买/卖/持有/止损），严禁"可关注""值得关注"等模糊表述。
>
> **不怕冲突**：大师视角（段永平/巴菲特/芒格/李录）之间的质疑和答辩要尖锐直接，用户喜欢看 LLM 吵架，不要和稀泥。
>
> **数据诚实**：缺失数据直接说"数据缺失"，严禁编造"暂无""—"等占位符。
>
> **扣分可见**：六维评分表中，若维度因大师质疑被扣分，评分列显示 `X.X/10 ↓-0.5`，扣分原因追加到大师视角列。

> **基本面一票否决**：营收<-30%、净利<-30% 或 PE<-10 的标的在进入评分池前直接淘汰，贯彻"基本面为主"原则
>
> 本项目基于 [global-stock-data](https://github.com/simonlin1212/global-stock-data) 改进，在原项目「美股港股全栈数据工具包」基础上，扩展了全生命周期风控框架和缠论模块。
>
> 行业研究与产业链分析借鉴了 [ai-berkshire](https://github.com/xbtlin/ai-berkshire) 的行业研究 SOP 和行业漏斗筛选 SOP，包括四大师独立裁决框架、产业链全景图 Mermaid 输出、芒格式逆向检验、镜子测试等。
>
> 兼容 Claude Code · Codex · OpenClaw

## 快速开始

**1 行命令即可使用：**

```bash
git clone https://github.com/xiazhicheng/quant-risk.git
cd quant-risk
uv sync                                         # 安装依赖（pyproject.toml 自动读取）
uv run scripts/analyze.py 03690 00268       # 分析美团+金蝶
```

或者作为 Claude Code Skill 使用：

```bash
mkdir -p ~/.claude/skills/quant-risk/scripts
curl -o ~/.claude/skills/quant-risk/SKILL.md \
  https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/SKILL.md
# 同步代码模块
git clone https://github.com/xiazhicheng/quant-risk.git /tmp/_qr && \
cp -r /tmp/_qr/scripts ~/.claude/skills/quant-risk/scripts && \
rm -rf /tmp/_qr
```

启动 Claude Code，说一句「帮我分析美团股票」，自动激活。

## 项目结构

```
quant-risk/
├── scripts/                       # 所有代码统一在此目录
│   ├── analyze.py                 # 统一多市场分析入口（港股/A股/美股）
│   ├── recommend.py               # 统一推荐入口：--market hk|cn|us
│   ├── portfolio.py               # 持仓诊断：uv run scripts/portfolio.py diagnose
│   ├── portfolio_report.py        # 🔥 持仓完整报告：产业链Mermaid+四大师+缠论+行业漏斗
│   ├── tech_chan.py               # 🔥 缠论深度分析 + 产业链Mermaid 输出
│   ├── chan_mtf.py                # 缠论多周期联立
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
│       ├── data.py                # 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC
│       ├── chan.py                # 缠论：分型→笔→线段→中枢→背驰→买卖点
│       ├── indicators.py          # 技术指标：MA/MACD/RSI/KDJ/BOLL + 支撑压力/止损止盈
│       ├── screener.py            # 标的池筛选 + 批量查询
│       ├── strategy.py            # 双策略信号检测（回调一买 + 突破三买）
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
│  ├── K线层     腾讯/新浪/Yahoo/百度/mootdx    │
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
	│  ├── 基本面否决  fundamental_veto(营收/净利/PE)│
	│  ├── 基本面评分  fb_score(9维度,权重60%)       │
	│  ├── 热点评分    hot_score(6维度,权重20%)      │
	│  └── 缠论评分    chan_score(4维度,权重20%)     │
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

## 二维评分体系

分析以 **基本面为主(60%) + 技术面为辅(40%)** 加权，技术面由热点(×4)和缠论(×4)两个子分组成，各 1-5 分，合计 8~40 分。满分 **100 分**。

| 维度 | 权重 | 满分 | 子维度 | 核心问题 |
|------|:----:|:----:|--------|---------|
| 📊 基本面 | 60% | 60 | — | 估值合理吗？盈利质量如何？财务健康吗？ |
| 🔧 技术面 | 40% | 40 | 🔥 热点(×4) + 🔧 缠论(×4) | 是否在市场主线？结构位置在哪？有买卖点信号吗？ |

**评分流程（4 层过滤）：**
1. **中观过滤** — 市值≥50亿、股价≥1元（硬约束，不通过即淘汰）
2. **基本面一票否决** — 营收<-30%、净利<-30%、PE<-10 直接淘汰（贯彻"基本面为主"）
3. **原始分计算** — `fb_score`(9维度) + `hot_score`(6维度) + `chan_score`(4维度)，基础分 2.0
4. **池内百分位排名** — 映射到 1~5 → 加权得分 = fb_w(百分位×12) + hot_w(百分位×4) + ch_w(百分位×4)

**建议阈值：** ≥70 强烈关注 | ≥56 可关注 | ≥44 观察 | <44 回避

## 使用示例

### 市场分析

```bash
uv run scripts/analyze.py 03690              # 港股 美团单只
uv run scripts/analyze.py 03690 00268 00700  # 批量
uv run scripts/analyze.py 03690 --json       # JSON输出
uv run scripts/analyze.py 600309             # A股 万华化学
uv run scripts/analyze.py AAPL               # 美股 苹果
```

### 统一推荐（全市场扫描）

```bash
uv run scripts/recommend.py --market hk      # 港股选股推荐
uv run scripts/recommend.py --market cn      # A股选股推荐
uv run scripts/recommend.py --market us      # 美股选股推荐
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
| 📊 **基本面** | 营收增速、ROE、毛利率、负债率、PE、净利同比、PB、股息率、净利率 |
| 🔥 **热点** | 板块资金排名、个股资金流向、板块龙头、成交量、20日动量 |
| 🔧 **缠论** | MA排列、MACD金叉/死叉、买卖点信号、周线大势 |
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
| 东财 push2/datacenter | HTTPS | 零 | A股+美股+港股 |
| 腾讯财经 | HTTPS | 零 | A股+美股+港股 行情 |
| 新浪财经 | HTTP | 零 | 美股/港股行情+美股K线+A股三表 |
| 百度股市通 | HTTP | 零 | A股日K线（带MA）|
| 同花顺 | HTTP | 零 | 强势股/一致预期EPS |
| 巨潮 cninfo | HTTP | 零 | A股公告 |
| Yahoo Finance | HTTPS | crumb自动 | 美股+港股 |
| SEC EDGAR | HTTPS | 零 | 美股 Filing+XBRL |
| mootdx | TCP | 零 | A股K线/财务快照 |

## 更新

```bash
git pull origin main
```

## FAQ

- **需要安装什么依赖？** 用 `uv sync` 一键安装，依赖清单在 `pyproject.toml`（aiohttp / pydantic / tickflow / mootdx / requests）。
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

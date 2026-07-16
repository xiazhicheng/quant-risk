# Quant-Risk

全生命周期量化风控工具 — **投前审查 / 持仓监控 / 预警触发 / 处置决策** 四阶段全覆盖。

支持 **美股 + A 股 + 港股** 三大市场，基于 **基本面为主 + 热点驱动 + 缠论择时** 的三维评分体系。

> 本项目基于 [global-stock-data](https://github.com/simonlin1212/global-stock-data) 改进，在原项目「美股港股全栈数据工具包」基础上，扩展了全生命周期风控框架和缠论模块。
>
> 兼容 Claude Code · Codex · OpenClaw

## 快速开始

**1 行命令即可使用：**

```bash
git clone https://github.com/xiazhicheng/quant-risk.git
cd quant-risk
uv sync                                         # 安装依赖（pyproject.toml 自动读取）
uv run scripts/analyze_hk.py 03690 00268       # 分析美团+金蝶
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
│   ├── analyze_hk.py              # 港股分析：uv run scripts/analyze_hk.py 03690
│   ├── recommend_hk.py            # 港股选股推荐：uv run scripts/recommend_hk.py
│   ├── portfolio.py               # 持仓诊断：uv run scripts/portfolio.py diagnose
│   ├── chan_mtf.py                # 缠论多周期联立
│   ├── formatter.py               # 选股推荐格式化器 (Pydantic + 渲染)
│   ├── formatters/                # 四阶段风控格式化器
│   │   ├── __init__.py
│   │   ├── _base.py               # 共享基础
│   │   ├── _pretrade.py           # 投前审查
│   │   ├── _holding.py            # 持仓监控
│   │   ├── _alert.py              # 预警触发
│   │   └── _disposal.py           # 处置决策
│   └── quantrisk/                 # Python 模块（scripts/quantrisk 子包）
│       ├── data.py                # 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC/工具
│       ├── chan.py                # 缠论：分型→笔→线段→中枢→背驰→买卖点
│       ├── indicators.py          # 技术指标：MA/MACD/RSI/KDJ/BOLL + 支撑压力/止损止盈
│       ├── screener.py            # 标的池三层筛选 + 批量查询
│       ├── report.py              # StockAnalyzer 一键全量分析入口
│       └── __init__.py            # 包入口
├── portfolio.json                 # 持仓配置文件
├── SKILL.md                       # Skill 主定义（数据函数 + 风控模板）
├── AGENTS.md                      # 项目约定和设计决策
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
│  分析层                                        │
│  ├── 技术指标  indicators.py (MA/MACD/RSI/KDJ)│
│  ├── 缠论     chan.py (分型→笔→中枢→买卖点)   │
│  └── 报告     report.py (StockAnalyzer)        │
└──────────────────────────────────────────────┘
```

## 三维评分体系

分析以 **基本面为主(权重5) > 热点(权重3) > 缠论(权重2)** 排序，每维 1-5 分，满分 50。

## 使用示例

### 港股分析

```bash
uv run scripts/analyze_hk.py 03690              # 美团单只
uv run scripts/analyze_hk.py 03690 00268 00700  # 批量
uv run scripts/analyze_hk.py 03690 --json       # JSON输出
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
| 三维评分 | 给美团做三维评分（基本面+热点+缠论）|

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
- **不用 Claude Code 能用吗？** 能，`uv run scripts/analyze_hk.py 03690` 直接运行。
- **和 a-stock-data 有什么关系？** 本项目 V1.1.0 将 a-stock-data 的 A 股接口封装融入风控框架。
- **和 global-stock-data 有什么关系？** 本项目 fork 自 global-stock-data，在其数据层基础上扩展了风控框架和缠论模块。
- **Yahoo Finance 需要 API Key 吗？** 不需要，代码自动获取 crumb。
- **支持实盘交易吗？** 不，本项目仅提供风控分析工具，不连接任何交易接口。

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

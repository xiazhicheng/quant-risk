# quant-risk — 全生命周期风控 Skill

## 项目定位

Claude Code Skill，覆盖 **美股 + A 股 + 港股** 全生命周期风控：投前审查 → 持仓监控 → 预警触发 → 处置决策。

## 核心约定

- **Python 包管理**: 用 `uv add` 不用 pip
- **执行 Python**: 用 `uv run`
- **写代码**: 严格遵守 superpowers skill 规范
- **思考过程**: 用中文
- **数据分析方法**: 基本面为主(权重5) > 热点(权重3) > 缠论(权重2) 三维评分

## 架构速览 (V1.2.0)

```
quantrisk/
├── data.py         (615行) 数据层 — 行情/K线/基本面/资金面/信号/公告/期权/SEC/工具
├── chan.py         (553行) 缠论 — 分型→笔→线段→中枢→背驰→买卖点
├── indicators.py   (316行) 技术指标 — MA/MACD/RSI/KDJ/BOLL + 缠论 re-export
├── screener.py     (113行) 标的池筛选 + 批量查询
├── report.py       (236行) StockAnalyzer 一键全量分析入口
└── scripts/                可直接运行的入口脚本 (uv run scripts/analyze_hk.py 03690)
```

## 关键设计决策

- **代码从 SKILL.md 提取为 Python 模块**: V1.2.0 将之前散落在 SKILL.md 文本中的~100个函数正式提取为可导入的 Python 包。用户不再需要 copy-paste 代码，直接 `from quantrisk.data import hk_stock_quote_tencent_async`
- **data.py 四合一**: HTTP 会话管理 + 行情层(8函数) + K线层(6函数) + 基本面/资金面/信号等(30函数)合并为一个文件，GitHub 浏览一目了然
- **scripts/ 入口**: 可直接 `uv run scripts/analyze_hk.py 03690` 运行，无需 pip install
- **A股行情主力**: 腾讯 (不封IP) > 东财 push2
- **A股日K**: 腾讯 (前复权) > 百度 (带MA) / mootdx (多周期)
- **缠论背驰**: MACD面积对比, 阈值15%, 强背驰50%
- **缠论中枢**: 至少3段重叠 (min_overlap=3)
- **标准化笔**: 分型间距≥4根K线, 同向取极端值
- **数据获取**: 全部 aiohttp 异步, batch_*() 并行查询
- **标的池筛选**: 三层流程：①宏观扫描(板块排名→候选池) → ②中观过滤(市值/成交额/股价) → ③微观评分(热点×3+基本面×5+缠论×2)
- **风控输出**: 每个阶段必须有明确结论 (买入/观望/拒绝 等)

## 文件清单

| 文件/目录 | 用途 |
|-----------|------|
| SKILL.md | Skill 主定义 (数据函数 + 风控模板) |
| README.md | 项目说明 |
| CHANGELOG.md | 版本记录 |
| CLAUDE.md | 本文件（项目约定和设计决策）|
| quantrisk/data.py | 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC/工具 (615行) |
| quantrisk/chan.py | 缠论：分型→笔→线段→中枢→背驰→买卖点 (553行) |
| quantrisk/indicators.py | 技术指标：MA/MACD/RSI/KDJ/BOLL/支撑压力/止损止盈 (316行) |
| quantrisk/screener.py | 标的池三层筛选 + 批量查询 (113行) |
| quantrisk/report.py | StockAnalyzer 全量分析入口：analyze_hk/analyze_cn/analyze_us (236行) |
| scripts/analyze_hk.py | 可直接运行的港股分析脚本 |

## 分析框架

三维分析体系（按权重排序）：

| 维度 | 权重 | 评分(1-5) | 核心问题 |
|------|------|----------|---------|
| 📊 基本面 | ×5 | 1-5 | 估值合理吗？盈利质量如何？财务健康吗？ |
| 🔥 热点 | ×3 | 1-5 | 是否在市场主线？有催化剂吗？ |
| 🔧 缠论 | ×2 | 1-5 | 结构位置在哪？有买卖点信号吗？ |

总分 = 基本面×5 + 热点×3 + 缠论×2，满分50。

**风控四阶段**: 投前审查 → 持仓监控 → 预警触发 → 处置决策

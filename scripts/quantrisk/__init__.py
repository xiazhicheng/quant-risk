# quantrisk — 全生命周期风控数据工具包
# 目录结构:
#   data.py        — 数据层：行情/K线/基本面/资金面/信号/公告/期权/SEC/工具（~600行）
#   chan.py        — 缠论：分型→笔→线段→中枢→背驰→买卖点（~550行）
#   indicators.py  — 技术指标：MA/MACD/RSI/KDJ/BOLL + 辅助分析（~300行）
#   screener.py    — 标的池三层筛选 + 批量查询（~110行）
#   report.py      — StockAnalyzer 一键全量分析入口（~230行）
# 用法:
#   from scripts.quantrisk.report import analyze_hk
#   import asyncio; result = asyncio.run(analyze_hk("03690"))

# 数据源优先级（data-sources）

> 本文件是 AGENTS.md「数据源优先级」章节归档，2026-09-18 拆分。
> **何时读取**：任务涉及行情/K线/基本面/资金面数据获取、数据源限流排查、K线 fallback 链调整时，先读本文件。

## 数据源优先级

| 数据类型 | 主源 | 备选 | 备注 |
|---------|------|------|------|
| A股行情 | 腾讯(不封IP) | 东财 push2 | — |
| A股日K | 腾讯(前复权) | 新浪(免鉴权) / 百度(带MA) / TickFlow(兜底) | 2026-08-31 新浪日K上线，TickFlow 降级为最终兜底 |
| 港股行情 | 腾讯(78字段) | 新浪(25字段) | — |
| 港股日K | 腾讯(ifzq.gtimg.cn) | Yahoo / TickFlow(兜底) | 2026-09-18 收敛为统一入口 `hk_kline_async`（腾讯→Yahoo 两级，fail-closed）；原 web.ifzq.gtimg.cn 已501（2026-08-12 修复）；新浪港股日K接口已失效不可用 |

**港股日K统一入口（2026-09-18 新增）**：`data.hk_kline_async(code, period="day", count)`——腾讯 ≥20 根即停；不足则 Yahoo（`stock_kline_yahoo_async`）兜底；两源全挂返回 `[]` 并打 WARN，绝不静默伪造。周K保持腾讯单点（Yahoo 兜底仅对日K开放）。原散落在 analyze_swing / backtest_swing / recommend_hk / portfolio 的手写"腾讯→Yahoo"兜底已全部收敛到该入口；report.py 与 chan_mtf / tech_chan（缠论 Yahoo 优先）保持原样。portfolio_report.py 已于 2026-09-21 收敛（日K走 `hk_kline_async`，周K腾讯单点优先 + Yahoo try/except 兜底）——旧链 Yahoo 优先且超时抛异常不返回空，会直接崩掉整个报告脚本。
**实测记录（2026-09-18）**：Yahoo chart API（query2.finance.yahoo.com）对本机出口 IP 返回 429，`fc.yahoo.com` crumb 初始化同样被限——当前网络下 Yahoo 兜底不会生效（fail-closed 空返回），属"保险"性质，网络恢复即自动生效。30m 链的 Yahoo 源同样受影响（由东财兜住）。
**实测记录（2026-09-21）**：Yahoo 在 portfolio_report.py 旧链（Yahoo 优先）上直接 **TimeoutError 抛异常**（非空返回），导致脚本崩溃；已收敛到 `hk_kline_async` 统一入口修复。
**HTTP 状态码（2026-09-18）**：`_get`/`_get_json` 现在检查非 2xx 状态码（≥400 返回空）并捕获 JSON 解析失败——上游返回 HTML/限流页不再抛 JSONDecodeError 炸调用方。
| 美股行情 | 腾讯(71字段) | 新浪(36字段) | — |
| 美股日K | 新浪 / Yahoo | TickFlow(兜底) | — |
| 基本面(港股A股) | 东财 datacenter | Yahoo(key stats) | — |
| 基本面(美股) | Yahoo | — | — |
| 缠论K线 | 腾讯(ifzq.gtimg.cn) / Yahoo / 新浪 | TickFlow(兜底) | TickFlow支持前复权 |

**腾讯 K 线域名（2026-08-12 修复）**：`http://web.ifzq.gtimg.cn`（HTTP+web 前缀）已失效返回 501，全部落到 TickFlow 导致道氏摆动点评分失真。修复为 `data.py` 的 `_tencent_kline_get()` 多域名降级：`https://ifzq.gtimg.cn` → `https://proxy.finance.qq.com/ifzqgtimg/`（均验证可用，0.1s，无 501）。**HTTPS + 非 web 前缀是硬要求**，改回 `web.ifzq.gtimg.cn` 会让道氏全挂（波段评分只拿最低基准分 = K 线源全挂的信号）。

**TickFlow** (免费免注册): 官方 SDK `pip install tickflow`，`TickFlow.free()` 模式
- 免费提供历史日K/周K/月K/季K/年K，无需 API Key
- 支持 A股(`.SH`/`.SZ`/`.BJ`) + 港股(`.HK`) + 美股(`.US`)
- 支持前复权 (`adjust=True`)
- 不支持实时行情和分钟级K线（free模式）
- 文档: https://docs.tickflow.org
- **2026-08-31 降级为最终兜底源**：`free-api.tickflow.org` 连接不稳定（频繁连接失败），所有 K 线 fallback 链中 TickFlow 移到最后，前端有腾讯/新浪/Yahoo 兜底，TickFlow 极少触发。`_get_tickflow()` 初始化加 8s 超时、`kline_tickflow_async` 数据请求加 10s 超时，失败快速返回不拖慢整体。

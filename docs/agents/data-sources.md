# 数据源优先级（data-sources）

> 本文件是 AGENTS.md「数据源优先级」章节归档，2026-09-18 拆分。
> **何时读取**：任务涉及行情/K线/基本面/资金面数据获取、数据源限流排查、K线 fallback 链调整时，先读本文件。

## 数据源优先级

| 数据类型 | 主源 | 备选 | 备注 |
|---------|------|------|------|
| A股行情 | 腾讯(不封IP) | 东财 push2 | — |
| A股日K | 腾讯(前复权) | 新浪(免鉴权) / 百度(带MA) / TickFlow(兜底) | 2026-08-31 新浪日K上线，TickFlow 降级为最终兜底 |
| 港股行情 | 腾讯(78字段) | 新浪(25字段) | — |
| 港股日K | 腾讯(ifzq.gtimg.cn) | Yahoo / TickFlow(兜底) | 2026-08-12 修复：原 web.ifzq.gtimg.cn 已501，改用 ifzq.gtimg.cn；新浪港股日K接口已失效不可用 |
| 美股行情 | 腾讯(71字段) | 新浪(36字段) | — |
| 美股日K | 新浪 / Yahoo | TickFlow(兜底) | — |
| 基本面(港股A股) | 东财 datacenter | Yahoo(key stats) | — |
| 基本面(美股) | Yahoo | — | — |
| 缠论K线 | 腾讯(ifzq.gtimg.cn) / Yahoo / 新浪 | TickFlow(兜底) | TickFlow支持前复权 |

**腾讯 K 线域名（2026-08-12 修复）**：`http://web.ifzq.gtimg.cn`（HTTP+web 前缀）已失效返回 501，全部落到 TickFlow 导致缠论评分失真。修复为 `data.py` 的 `_tencent_kline_get()` 多域名降级：`https://ifzq.gtimg.cn` → `https://proxy.finance.qq.com/ifzqgtimg/`（均验证可用，0.1s，无 501）。**HTTPS + 非 web 前缀是硬要求**，改回 `web.ifzq.gtimg.cn` 会让缠论全挂（缠论评分 6/20 最低基准 = K 线源全挂的信号）。

**TickFlow** (免费免注册): 官方 SDK `pip install tickflow`，`TickFlow.free()` 模式
- 免费提供历史日K/周K/月K/季K/年K，无需 API Key
- 支持 A股(`.SH`/`.SZ`/`.BJ`) + 港股(`.HK`) + 美股(`.US`)
- 支持前复权 (`adjust=True`)
- 不支持实时行情和分钟级K线（free模式）
- 文档: https://docs.tickflow.org
- **2026-08-31 降级为最终兜底源**：`free-api.tickflow.org` 连接不稳定（频繁连接失败），所有 K 线 fallback 链中 TickFlow 移到最后，前端有腾讯/新浪/Yahoo 兜底，TickFlow 极少触发。`_get_tickflow()` 初始化加 8s 超时、`kline_tickflow_async` 数据请求加 10s 超时，失败快速返回不拖慢整体。

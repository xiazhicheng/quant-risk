# Quant-Risk

**零成本 · A股+港股 量化选股 AI Skill**（Claude Code · Codex · ZCode 通用）

给 AI 装上"会看盘的助手"——对话就能**推荐 A股/港股标的、分析单只股票、生成每日信号、诊断持仓**。数据全部来自**免费公开接口**，零注册、零 API Key、零订阅，GitHub 下载即用。

---

## ✨ 特性

| | 说明 |
|:--|:----|
| 💰 **零成本** | 行情/K线/资金流/公告/财务全部来自腾讯、东财、新浪、Yahoo 等**免费公开接口**，无需注册、无需 API Key、无任何付费墙 |
| ⚡ **下载即用** | 一行命令安装为 AI Skill，重启客户端即可对话使用；脚本依赖由 AI 首次运行时自动安装（几十 MB） |
| 🇨🇳 **聚焦 A股+港股** | 波段推荐、单股分析、每日收盘工作流、回测闭环（美股已移出维护，旧价值评分为 legacy 兼容） |
| 📊 **道氏波段评分** | 四维 100 分（日线趋势30 / 日线量价资金25 / 日线道氏20 / 30分钟道氏25），三档状态（🟢可布局 / 🟡谨慎 / 🟡观望），每只带**触发价 + 止损 + 移动止盈**（不预测目标价） |
| 📅 **每日信号** | `daily_run.py` 一条命令跑完 A股+港股「扫池 → 规则裁决 → 决策凭证 → 冻结快照 → 报告」，无 LLM 依赖 |
| 🔌 **MCP 工具** | 5 个确定性工具（analyze_stock / run_daily / run_recommend / backtest_stats / get_daily_report）供 AI 客户端直接调用 |
| 🔒 **免费源容错** | 免费接口高频访问会限流——数据缺失时系统**宁可 BLOCK 不给假信号**（fail-closed），限流恢复自动生效 |

---

## 快速开始

**方式一：安装为 AI Skill（推荐，下载即用）**

```bash
# macOS / Linux：一键安装到 ~/.claude/skills/quant-risk
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)"

# Windows（PowerShell）
irm https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.ps1 | iex
```

其他客户端指定目标目录：

```bash
# Codex
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)" -- --dest ~/.codex/skills/quant-risk
# ZCode
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)" -- --dest ~/.agents/skills/quant-risk
```

装完后**重启 AI 客户端**，对话中直接说：

> 「推荐今日 A股+港股」 或 「帮我分析 600388」

首次执行时 AI 会自动 `uv sync` 安装依赖（几十 MB，约 1-3 分钟），之后即用。

> 手动同步：`git clone https://github.com/xiazhicheng/quant-risk.git && cp -r SKILL.md scripts ~/.claude/skills/quant-risk/`

**方式二：Docker 一键运行（零环境要求，脚本直跑）**

```bash
docker pull ghcr.io/xiazhicheng/quant-risk:latest
docker run --rm -v $(pwd)/report:/app/report quant-risk daily --markets cn,hk   # 每日信号
docker run --rm -v $(pwd)/report:/app/report quant-risk analyze 600388          # 单股分析
```

**方式三：本机直接运行 CLI（macOS / Linux / Windows）**

```bash
git clone https://github.com/xiazhicheng/quant-risk.git
cd quant-risk
bash install.sh                      # macOS/Linux：自动装 uv + Python 3.12 + 依赖
# Windows: powershell -ExecutionPolicy Bypass -File install.ps1
uv run scripts/analyze_swing.py 600388   # 单股波段分析
```

> 💡 **依赖说明**：默认安装**轻量依赖**（约几十 MB），要求 Python 3.12+（安装脚本自动托管），无需任何 API Key。**Semantica（可选）**：需要完整 RETE 影子裁决（审计溯源）时 `uv sync --extra semantica`（约 2.5GB）；未安装时自动降级纯 Python 参考引擎，功能完整。

---

## 它能做什么（对话示例）

| 你想做的事 | 对 AI 说 | 得到什么 |
|:----|:----|:----|
| 推荐今日标的 | 「推荐今日 A股+港股」 | TOP10 推荐表（四维评分+三档状态+评分要点）+ 逐只触发价/止损/移动止盈 |
| 分析单只股票 | 「帮我分析 600388」 | 单股波段信号：四维评分/道氏结论/上车离场条件/三tab简介（简况/财务/看点/动态） |
| 看每日信号 | 「跑一下每日信号」 | A股+港股每日报告 + 冻结快照 + 决策凭证 + 回测记录 |
| 检查持仓 | 「结合我的持仓给投资建议」 | 持仓诊断 + 调仓建议（持有/止损/减仓/加仓） |
| 查回测 | 「回测统计怎么样」 | T+5/10/20 胜率、按总分分段/状态分组统计 |

---

## 数据与成本（纯免费）

| 数据类型 | 免费数据源（零鉴权） |
|:----|:----|
| A股/港股行情 | 腾讯财经（主源，不封 IP）、东财 push2 |
| A股日K | 腾讯（前复权）→ 新浪 → 百度 → TickFlow（兜底） |
| 港股日K | 腾讯 → Yahoo |
| 30分钟K线 | A股：Yahoo→东财→新浪→腾讯→mootdx；港股：Yahoo→东财 |
| 资金流 | 东财 push2his（分钟级，并发限流自动退避） |
| 基本面/财务 | 东财 datacenter / F10 |
| 公告 | 东财公告接口（A股）/ 腾讯公告（港股） |
| 板块/题材 | 东财 F10 + 腾讯自选股 |

> ✅ **零成本承诺**：不接任何付费数据源，不要求注册或 API Key。免费源高频访问有限流属正常现象——系统已内置并发控制与退避重试，限流期宁可输出「数据缺失」也不造假（fail-closed）。

---

## 波段评分体系（当前默认）

A股与港股默认运行**纯技术波段模式**（策略 `swing_band`），持有时间不预设（高抛低吸，由离场信号自然决定；60 天仅作风控上界）。**评分只用行情/成交量/资金/道氏摆动点，不看基本面**（PE/ROE/负债率不参与评分、不否决）。

| 维度 | 满分 | 依据 |
|:----|:---:|:----|
| 日线趋势 | 30 | MA5/10/20/60 排列、价格位置、MACD 动能 |
| 日线量价/资金 | 25 | 近5日涨跌、量比、主力资金流 |
| 日线道氏 | 20 | 收盘价摆动点判趋势（高点/低点连续抬高=上升，只做多） |
| 30分钟道氏 | 25 | 30m 摆动点确认短线入场（缺失不阻断、与日线冲突则观望） |

**输出三档状态 + 可执行价格**：🟢可布局（现价分批介入+回踩加仓）／🟡谨慎布局（回踩 MA5/MA10 企稳或放量突破前高，勿追高）／🟡观望（放量突破确认后再介入）；每只带 ATR 动态止损（-5%~-11%）与移动止盈（跌破前低或自高点回撤离场，**不预测目标价**）。

**道氏三步框架**：①定方向=收盘价摆动点只做多；②验健康=涨放量/回调缩量 + A股三大指数同向（背离即禁新仓）；③找信号=收盘价未跌破前低则持有，跌破离场。辅以三阶段定位（吸筹/公众参与/派发，缩量新高降级）。

**风控自动拦截**：ST/*ST/退市硬拦截，次新股警示，停牌/退市残留代码剔除，数据缺失 BLOCK。

---

## 常见问题（FAQ）

**Q1：安装后跑出来全是 BLOCK / 数据缺失，是不是装坏了？**
不是。`BLOCK：数据缺失` 是**免费数据源限流**时的 fail-closed 正常行为（东财资金流/港股 30m 等高并发即限流），系统宁可拒绝也不给假信号。稍后重跑或分市场跑（`--markets cn` / `--markets hk`）即恢复。

**Q2：要花钱吗？要 API Key 吗？**
都不要。数据全部来自腾讯/东财/新浪/Yahoo 等免费公开接口，零注册、零 API Key、零订阅。

**Q3：为什么默认不装 Semantica（2.5GB）？**
官方全量包含 torch/faiss 等 AI 推理库，而本项目只用它的纯标准库 RETE。默认轻量安装（几十 MB）功能完整（Python 主裁决+自动降级）；需要完整影子比对时 `uv sync --extra semantica`。

**Q4：首次运行很慢 / 卡住？**
首轮要拉全市场候选池（A股约 300 只 × 日K/30m/资金流），A股+港股串行约 1-5 分钟属正常；某数据源限流会有 WARN 日志，不影响其余标的。

**Q5：Windows 兼容吗？**
兼容。`install.ps1` 自动装 uv + Python 3.12 + 依赖，数据层均为 HTTP 免费接口，无平台特定依赖。

**Q6：如何卸载？**
删除 skill 目录即可（如 `rm -rf ~/.claude/skills/quant-risk`）；依赖装在项目内 `.venv/`，不污染系统。

**Q7：支持实盘交易吗？**
不支持。本项目仅提供数据获取与风控分析，不连接任何交易接口。

**Q8：持仓信息每次都要重新说吗？**
不需要。提供过一次后自动保存到记忆系统，下次会话直接分析。

**Q9：Yahoo 需要 API Key 吗？**
不需要，代码自动获取 crumb。

---

## 高级用法（CLI）

```bash
uv run scripts/daily_run.py                                  # 每日收盘工作流（A股+港股）
uv run scripts/analyze_swing.py 600388                       # 单股波段分析（A股6位/港股5位）
uv run scripts/analyze_swing.py 03968                        # 港股示例
uv run scripts/recommend.py --market cn --rule-engine shadow # 全市场波段推荐（TOP10）
uv run scripts/backtest_swing.py --report --days 5,10,20     # 回测统计（胜率/分数段/状态分组）
uv run scripts/portfolio.py diagnose                         # 持仓诊断
uv run scripts/mcp_server.py                                 # MCP server（stdio，供 AI 客户端）
```

> MCP 接入细节（stdio / Streamable HTTP / Docker 远程）与项目结构见仓库内 `AGENTS.md`。

---

## Legacy（旧体系，仅兼容，非默认）

- **价值评分 `--mode value`**：六维基本面(50) + 缠论(30) + 热点(20) = 100 分（5:3:2），四大师对抗/产业链 Mermaid/芒格式逆向检验/镜子测试——保留供旧报告复现
- **持仓完整报告**：`portfolio_report.py`（组合总览/产业链全景图/缠论深度/投委会辩论）
- **美股**：已移出维护范围（2026-08-31），`--market us` 为 legacy 兼容路径

---

## 更新

```bash
# Skill 方式：重跑 install_skill.sh 即可覆盖更新
bash -c "$(curl -fsSL https://raw.githubusercontent.com/xiazhicheng/quant-risk/main/scripts/install_skill.sh)"
# 仓库方式：git pull origin main
```

---

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

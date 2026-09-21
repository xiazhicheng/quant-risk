# jev_advice.py — TypeSafe jev 模型持仓买卖裁决

> **何时读取**：任务涉及外部 AI 裁决（TypeSafe jev）、持仓买卖双引擎交叉验证、`scripts/jev_advice.py` 时读取。

## 定位

用 TypeSafe 的 System One 旗舰模型 **jev** 对持仓组合做结构化买卖裁决（buy/hold/reduce/sell），与本地道氏波段系统交叉验证。**设计哲学（官方 System One 范式）**：代码负责取数/算信号，模型只负责在你定义好的、风险可控的问题里做窄决策——不把自由文本生成交给模型。

**jev 非必需（2026-09-21 用户明确）**：typesafe-sdk 未安装 / 无 `TYPESAFE_API_KEY` / jev 调用失败时自动降级 `local_dow_action` 纯规则裁决（输出同构：action+confidence+reason），**永不崩溃，离线照常可用**。降级映射：离场/道氏 down → sell；双 up+可布局 → buy；谨慎布局/双周期冲突/派发 → reduce；其余（观望/数据质量不足）→ hold。测试 `tests/test_jev_advice.py` 覆盖两条路径与降级分支。

## 依赖与安装

- `typesafe-sdk`（pyproject 已加，2026-09-21；注意它要求 `tenacity>=9`，与 mootdx 的 `<9` 冲突——**mootdx 已移除**，勿重装）
- **API key 存放**：写项目根 `.env` 文件 `TYPESAFE_API_KEY=xxx`（已进 `.gitignore`，不会推 GitHub）。脚本启动自动加载 `.env`（`_load_dotenv` 零依赖实现，环境变量优先），**无需手动 export**；也可用 `TYPESAFE_API_KEY=xxx uv run ...` 临时覆盖
- 可用模型：`jev-latest`（默认）｜`jev-preview`（预览）

## 用法

```bash
echo '[{"code":"002640","market":"cn","shares":3000,"avg_cost":3.702},
       {"code":"02460","market":"hk","shares":6800,"avg_cost":9.492}]' \
  | uv run scripts/jev_advice.py --stdin            # key 从项目根 .env 自动读取

uv run scripts/jev_advice.py --stdin --model jev-preview   # 指定模型
uv run scripts/jev_advice.py --stdin --json                # 原始 JSON
uv run scripts/jev_advice.py portfolio.json                # 本地文件
```

输入与 `portfolio_report.py --stdin` 同格式（`code/market/shares/avg_cost`，5位=港股、6位=A股）。

## state / questions 写法（本工具固化规范）

### state — 被评估的结构化数据（代码算，模型看）

`build_state()`（`scripts/jev_advice.py`）自动打包，两层：

| 层 | 内容 | 说明 |
|:----|:----|:----|
| 账户层 | 总市值/总成本/总盈亏%/持仓数/集中度TOP1 | 让模型感知全局约束（如单票>20%红线）|
| 持仓层（每只）| 仓位占比/成本/现价/盈亏% + 波段总分/状态 + 日线&30m道氏结论 + 趋势健康/量比/主力5日 + 三阶段 + 止损/离场规则 + 基本面财务（东财有则带）+ 主营业务构成 + 所属板块 | 复用 `analyze_swing.py` 信号管线，**数据缺失如实缺，不编造** |

**关键**：把量化系统算好的信号拼进 state，而不是让模型自己看图——代码负责事实，模型只做裁决。

### questions — 三类结构化问题

本工具为每只持仓发 `Choice`（买卖裁决）+ `Score`（信心），组合级发 `Score`（风险）：

```python
# Choice：多选一，criteria 是 dict（选项→触发条件），返回 choice+confidence+各选项概率
Choice(instructions="华润饮料（02460）应如何操作？综合技术面（波段23分、道氏下降趋势、跌破前低、缩量）与基本面及仓位风险给出裁决",
       criteria={"buy": "立即买入/加仓，认为是错杀机会",
                 "hold": "继续持有，等反弹回本",
                 "reduce": "部分减仓降低风险，允许保留部分仓位博反弹",
                 "sell": "止损离场，趋势已破不应再扛"})

# Score：按有序等级打分，criteria 是 list（低→高），返回 score(0..N-1)+各档概率
Score(instructions="对华润饮料裁决的信心度", criteria=["非常不确定","有点不确定","比较确定","非常确定"])

# Noul：是/否（本工具未用，官方三种之一）
Noul(instructions="该消息是否表达紧急/时效性")
```

**写法要点**：
1. 一个 `system_one` 调用可塞多个 question，共享同一 state（本工具 3 只持仓 = 7 个 question 一次调用）
2. `instructions` 里把关键证据写全（评分/道氏结论/仓位权重），模型按 instruction+criteria 回答，不是去 state 里翻
3. criteria 选项互斥、语义边界清晰，概率才有意义
4. score 高但 confidence 低 = 模型只是碰巧选档，信号弱，读结果要两个一起看
5. 必须 `model="jev-latest"`（或 preview），key 走 `TYPESAFE_API_KEY`

### 结果读取

```python
resp.choices["02460_action"].choice          # "reduce"
resp.choices["02460_action"].confidence      # 0.69
resp.choices["02460_action"].probabilities   # {"sell":0.17,"reduce":0.77,"hold":0.06,"buy":0.0}
resp.scores["portfolio_risk"].score          # 0..3
```

## 踩坑记录

- **2026-09-21 依赖冲突**：`typesafe-sdk` 需 `tenacity>=9`，mootdx 锁 `<9` → 用户决定删 mootdx（它同时是 A股30m/基本面的 TCP 兜底源，删除同步清了 `data.py`/`recommend_cn.py`/`tests/test_30m_data.py`/README/docs 引用，30m 源链收敛为 Yahoo→东财→新浪→腾讯）
- **2026-09-21 asyncio 双 run**：`_collect` 早期写成同步函数内部又 `asyncio.run(_main())`，外层 run() 再包一层报 `ValueError: coroutine expected` → 改为纯 async + `asyncio.gather`
- **state 信息密度影响裁决**：只传技术面信号时华润被判 `reduce 54%`（信心 0.39）；补上账户层集中度 + 基本面财务后升至 `reduce 77% / sell 17%`（信心 0.69）——**state 越接近用户手工构造的完整语境，裁决越准**
- **jev 有概率波动**：同 state 多跑有 ±10% 概率抖动，正常；看稳定方向 + confidence，不抠单次数值
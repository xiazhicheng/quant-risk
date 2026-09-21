"""jev_advice.py — 持仓组合买卖裁决（TypeSafe jev 模型 + 本地道氏降级）。

复用 analyze_swing.py 的波段信号管线（行情/资金/道氏/止损），把量化信号打包成
state + questions 发给 TypeSafe jev 模型，让模型按 Choice/Score 结构化裁决
每只持仓 buy/hold/reduce/sell，并给出信心度与组合风险。

**jev 非必需（2026-09-21 用户明确）**：typesafe-sdk 未安装 / 无 TYPESAFE_API_KEY /
jev 调用失败时，自动降级为本地道氏裁决（local_dow_action 纯规则映射，输出同构），
脚本永不崩溃——离线环境照常可用。

用法:
    echo '[{"code":"002640","market":"cn","shares":3000,"avg_cost":3.702},\
           {"code":"02460","market":"hk","shares":6800,"avg_cost":9.492}]' \
      | uv run scripts/jev_advice.py --stdin
    uv run scripts/jev_advice.py --stdin --model jev-preview   # 指定模型
    uv run scripts/jev_advice.py --stdin --json                # 输出原始 JSON
    uv run scripts/jev_advice.py portfolio.json                # 本地文件

依赖:
    - typesafe-sdk（uv add typesafe-sdk；注意其 tenacity>=9 与 mootdx 冲突，
      mootdx 已于 2026-09-21 移除）
    - 环境变量 TYPESAFE_API_KEY（必填，控制台 https://console.typesafe.ai 创建）

输出:
    - 每只持仓: choice（buy/hold/reduce/sell）+ confidence + 各选项概率
    - 信心度 score（0..3 档）
    - 组合整体风险 score（0..3 档）
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.analyze_swing import analyze_one, detect_market
from scripts.quantrisk.data import close_async_session

DEFAULT_MODEL = "jev-latest"
ACTION_KEYS = ("buy", "hold", "reduce", "sell")
CONF_LEVELS = ["非常不确定", "有点不确定", "比较确定", "非常确定"]
RISK_LEVELS = ["低风险", "中等风险", "高风险", "极高风险"]

ACTION_CRITERIA = {
    "buy": "立即买入/加仓，技术面与价值面足够强",
    "hold": "继续持有，不加仓也不卖出",
    "reduce": "部分减仓，降低仓位控制风险",
    "sell": "全部卖出，风险大过收益",
}


def _fmt_pct(v: float) -> str:
    return f"{v:+.2f}%"


def _direction_label(r: dict, key: str) -> str:
    d = (r.get(key) or {}).get("direction") or "无"
    return {"up": "上升", "down": "下降", "neutral": "震荡"}.get(d, d or "无")


def build_state(holdings: list[dict], results: list[dict], account: dict | None = None) -> dict:
    """把波段信号打包成 state（账户层汇总 + 持仓层结构化 JSON）。"""
    pairs = []
    for h, r in zip(holdings, results):
        shares = float(h.get("shares", 0))
        cost = float(h.get("avg_cost", 0))
        price = float(r.get("price") or 0)
        pairs.append({"h": h, "r": r, "mv": shares * price, "cv": shares * cost})
    total_cost = sum(p["cv"] for p in pairs)
    total_value = sum(p["mv"] for p in pairs) or 1.0
    total_pnl = (total_value / total_cost - 1) * 100 if total_cost else 0.0
    top = max(pairs, key=lambda p: p["mv"], default=None)
    account_layer = account or {
        "总市值": round(total_value, 2),
        "总成本": round(total_cost, 2),
        "总盈亏%": round(total_pnl, 2),
        "持仓数": len(pairs),
        "集中度TOP1": f"{top['r'].get('name')} {top['mv'] / total_value * 100:.1f}%（单票20%红线参考）" if top else "无",
    }
    state_holdings = []
    for p in pairs:
        h, r = p["h"], p["r"]
        code = h["code"]
        shares = float(h.get("shares", 0))
        cost = float(h.get("avg_cost", 0))
        price = float(r.get("price") or 0)
        mv = p["mv"]
        pnl = (price / cost - 1) * 100 if cost else 0.0
        stroke = r.get("stroke") or {}
        seg = r.get("segment") or {}
        health = r.get("health") or {}
        stage, stage_note = r.get("stage") or "未知", r.get("stage_note") or ""
        exit_rule = str(r.get("exit_rule") or "移动止盈离场")
        extra = r.get("profile_extra") or {}
        fin = extra.get("finance") or {}
        mix = extra.get("business_mix") or []
        conc = extra.get("conception") or {}
        item = {
            "代码": code, "名称": r.get("name") or code, "市场": "A股" if h.get("market") == "cn" else "港股",
            "仓位占比%": round(mv / total_value * 100, 2),
            "成本": cost, "现价": price, "盈亏%": round(pnl, 2),
            "波段总分": r.get("total"), "状态": r.get("status"),
            "日线道氏方向": _direction_label(r, "stroke"),
            "日线道氏结论": stroke.get("conclusion", "数据缺失"),
            "30分钟道氏方向": _direction_label(r, "segment"),
            "30分钟道氏结论": seg.get("conclusion", "数据缺失"),
            "趋势健康": health.get("note", "数据缺失"),
            "量比": r.get("flow", {}).get("vol_ratio"),
            "主力5日": r.get("flow", {}).get("flow_5d"),
            "三阶段": stage, "三阶段说明": stage_note,
            "止损": r.get("stop_loss"), "离场规则": exit_rule,
        }
        if fin:
            item["基本面财务"] = {k: fin.get(k) for k in
                                  ("report_date", "revenue", "revenue_yoy", "profit",
                                   "profit_yoy", "roe", "gross_margin", "net_margin", "debt_ratio")
                                  if fin.get(k) is not None}
        if mix:
            item["主营业务构成"] = [{"业务": m.get("item"), "占比%": m.get("ratio"),
                                      "毛利率%": m.get("gross_margin")} for m in mix[:3]]
        boards = conc.get("boards") or []
        if boards:
            item["所属板块"] = "、".join([b for b in boards if "概念" in b or "题材" in b][:6]
                                        or boards[:6])
        state_holdings.append(item)
    return {"账户": account_layer, "持仓": state_holdings}


def build_questions(holdings: list[dict], results: list[dict]) -> dict:
    """为每只持仓构建 Choice(buy/hold/reduce/sell) + Score(信心) 及组合级 Score(风险)。"""
    from typesafe_sdk import Choice, Score
    questions = {}
    for h, r in zip(holdings, results):
        code = h["code"]
        name = r.get("name") or code
        stroke = (r.get("stroke") or {}).get("conclusion", "数据缺失")
        seg = (r.get("segment") or {}).get("conclusion", "数据缺失")
        status = r.get("status")
        pnl = (float(r.get("price") or 0) / float(h.get("avg_cost") or 1) - 1) * 100
        questions[f"{code}_action"] = Choice(
            instructions=(
                f"{name}（{code}）应如何操作？综合技术面（波段总分{r.get('total')}、状态『{status}』、"
                f"日线道氏『{stroke}』、30分钟『{seg}』）与盈亏（{pnl:+.1f}%）及仓位权重（{h['shares']}股）给出裁决"
            ),
            criteria={k: v for k, v in ACTION_CRITERIA.items()},
        )
        questions[f"{code}_confidence"] = Score(
            instructions=f"对 {name}（{code}）裁决的信心度",
            criteria=CONF_LEVELS,
        )
    questions["portfolio_risk"] = Score(
        instructions="整个持仓组合的整体风险水平（集中度、深套比例、趋势分化）",
        criteria=RISK_LEVELS,
    )
    return questions


def _load_dotenv() -> None:
    """零依赖 .env 加载：项目根 .env 的 KEY=VALUE 注入 os.environ（已存在的环境变量优先）。
    .env 已被 .gitignore 忽略，防止 API key 推送到 GitHub。"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass


def local_dow_action(r: dict, pnl_pct: float = 0.0, position_pct: float = 0.0) -> tuple[str, float, str]:
    """无 jev 时的本地降级裁决：纯道氏信号映射 buy/hold/reduce/sell。

    映射规则（与 swing.py status 语义对齐）：
      - 离场 / 日线道氏下降且跌破前低 → sell
      - 当前可布局 / 日线+30m 双 up → buy
      - 谨慎布局 / 双周期冲突 / 三阶段派发 → reduce
      - 其余（观望/震荡/数据缺失）→ hold
    返回 (action, confidence, reason)。confidence 为规则确定性加权，非模型概率。"""
    status = str(r.get("status") or "")
    stroke = r.get("stroke") or {}
    seg = r.get("segment") or {}
    d_dir, s_dir = stroke.get("direction"), seg.get("direction")
    stage = r.get("stage") or ""
    dow_step3 = str(r.get("dow_step3") or "")
    total = float(r.get("total") or 0)
    stop = r.get("stop_loss") or 0
    price = float(r.get("price") or 0)

    def _conf(base: float, penalty: int = 0) -> float:
        return round(min(0.95, max(0.3, base - penalty * 0.08)), 2)

    # 1. 离场信号最硬：跌破前低/趋势结束
    if ("离场" in status or "跌破前低" in dow_step3 or d_dir == "down"):
        return "sell", _conf(0.9), f"道氏{d_dir}方向向下或已破前低（{dow_step3 or status}）"
    # 2. 双 up + 可布局 → buy（前提：有足够 K 线）
    if d_dir == "up" and s_dir == "up" and "当前可布局" in status:
        return "buy", _conf(0.85), f"日线+30m 双 up（{status}），总分{total:.0f}"
    # 3. 谨慎布局/冲突/派发 → reduce
    if "谨慎布局" in status or (d_dir and s_dir and d_dir != s_dir) or stage == "派发":
        why = f"{stage}·派发" if stage == "派发" else ("双周期冲突" if d_dir != s_dir else status)
        return "reduce", _conf(0.7), f"{why}，降风险（总分{total:.0f}）"
    # 4. 其他 → hold（含禁止开仓=数据质量不足，不动）
    return "hold", _conf(0.6), f"{status or '观望'}，等待共振（总分{total:.0f}）"


def run(holdings: list[dict], model: str = DEFAULT_MODEL) -> dict:
    """执行裁决：优先 jev 模型，缺失 SDK/API key 时降级为本地道氏裁决（不崩溃）。"""
    results = asyncio.run(_collect(holdings))
    engine, error = "jev", ""
    try:
        from typesafe_sdk import TypeSafeClient
        _load_dotenv()
        api_key = os.environ.get("TYPESAFE_API_KEY")
    except ImportError:
        api_key = None
        engine, error = "local-dow", "typesafe-sdk 未安装，降级本地道氏裁决"
    if engine == "jev" and not api_key:
        engine, error = "local-dow", "缺少 TYPESAFE_API_KEY，降级本地道氏裁决"
    if engine == "jev":
        state = build_state(holdings, results)
        questions = build_questions(holdings, results)
        try:
            with TypeSafeClient(model=model, api_key=api_key) as client:
                resp = client.system_one(state=state, questions=questions)
            return {"engine": "jev", "model": resp.model, "state": state, "results": results,
                    "response": resp, "error": ""}
        except Exception as exc:
            engine, error = "local-dow", f"jev 调用失败（{exc}），降级本地道氏裁决"
    # 本地降级：输出与 jev 同构的裁决结构
    state = build_state(holdings, results, account=None)
    pairs = []
    for h, r in zip(holdings, results):
        code = h["code"]
        price = float(r.get("price") or 0)
        cost = float(h.get("avg_cost") or 0)
        pnl = (price / cost - 1) * 100 if cost else 0.0
        position_pct = 0.0
        for st in state["持仓"]:
            if st["代码"] == code:
                position_pct = float(st.get("仓位占比%") or 0)
        action, conf, reason = local_dow_action(r, pnl, position_pct)
        pairs.append({"code": code, "action": action, "confidence": conf, "reason": reason,
                      "pnl_pct": round(pnl, 2), "position_pct": round(position_pct, 2)})
    return {"engine": "local-dow", "model": "local-dow", "state": state, "results": results,
            "response": None, "error": error, "local": pairs}


async def _collect(holdings: list[dict]) -> list[dict]:
    async def _one(h):
        market, clean = detect_market(h["code"])
        h = dict(h, market=market)
        return await analyze_one(clean, market, name_hint=h.get("name", ""))

    try:
        return await asyncio.gather(*(_one(h) for h in holdings))
    finally:
        await close_async_session()


def render(out: dict) -> str:
    """渲染裁决结果（jev 引擎输出 choice/score；local-dow 降级输出本地映射）。"""
    engine = out.get("engine", "jev")
    if engine == "local-dow":
        lines = ["=== 本地道氏裁决（jev 不可用，降级） ==="]
        if out.get("error"):
            lines.append(f"> ⚠️ {out['error']}")
        for item in out.get("local", []):
            icon = {"buy": "🟢", "hold": "🟡", "reduce": "🟠", "sell": "🔴"}.get(item["action"], "⚪")
            lines.append(f"\n[{item['code']}] action={icon}{item['action']} | confidence={item['confidence']}")
            lines.append(f"  reason={item['reason']} | 盈亏 {item['pnl_pct']:+.1f}% | 仓位 {item['position_pct']:.1f}%")
        return "\n".join(lines)
    lines = ["=== jev 裁决 ==="]
    response = out.get("response")
    choices = getattr(response, "choices", {})
    scores = getattr(response, "scores", {})
    for name, ch in choices.items():
        lines.append(f"\n[{name}] choice={ch.choice} | confidence={ch.confidence}")
        lines.append(f"  probabilities={json.dumps({k: round(float(v), 3) for k, v in ch.probabilities.items()}, ensure_ascii=False)}")
    for name, sc in scores.items():
        lines.append(f"\n[{name}] score={sc.score} | confidence={sc.confidence}")
        lines.append(f"  probabilities={json.dumps({k: round(float(v), 3) for k, v in sc.probabilities.items()}, ensure_ascii=False)}")
    return "\n".join(lines)


def _json_output(out: dict) -> dict:
    engine = out.get("engine", "jev")
    if engine == "local-dow":
        return {"engine": "local-dow", "model": "local-dow", "error": out.get("error", ""),
                "decisions": out.get("local", [])}
    resp = out["response"]
    return {"engine": "jev", "model": out.get("model", "jev-latest"),
            "choices": {k: {"choice": v.choice, "confidence": v.confidence,
                            "probabilities": v.probabilities} for k, v in resp.choices.items()},
            "scores": {k: {"score": v.score, "confidence": v.confidence,
                           "probabilities": v.probabilities} for k, v in resp.scores.items()},
            "error": out.get("error", "")}


def main() -> None:
    args = sys.argv[1:]
    stdin_mode = "--stdin" in args
    json_mode = "--json" in args
    model = DEFAULT_MODEL
    if "--model" in args:
        model = args[args.index("--model") + 1]
    raw = None
    if stdin_mode:
        raw = sys.stdin.read().strip()
    elif args and not args[0].startswith("--"):
        with open(args[0]) as f:
            raw = f.read()
    if not raw:
        print(__doc__)
        sys.exit(1)
    data = json.loads(raw)
    holdings = data if isinstance(data, list) else data.get("holdings", [])
    out = run(holdings, model=model)
    if json_mode:
        print(json.dumps(_json_output(out), ensure_ascii=False, indent=2))
    else:
        print(render(out))


if __name__ == "__main__":
    main()
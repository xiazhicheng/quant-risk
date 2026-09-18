"""单股波段分析脚本：A股 / 港股 个股纯技术波段评分。

用法:
    uv run scripts/analyze_swing.py 600388           # A股
    uv run scripts/analyze_swing.py 03968            # 港股（5位代码）
    uv run scripts/analyze_swing.py 03968.HK         # 港股（带后缀）
    uv run scripts/analyze_swing.py 600018 01258     # 批量

输出:
    - 波段四维评分（日线趋势30 + 量价资金25 + 日线道氏20 + 30分钟道氏25 = 100）
    - 日线/30分钟道氏一句话结论（规则八格式）
    - 布局状态判定（当前可布局 / 谨慎布局 / 观望）+ 止损/目标价
    - 三刀筛辅助数据（量比 / 道氏双周期方向 / 板块）

与 recommend.py --mode swing 同源：复用 swing.py 评分核心 + data.py 数据层，
仅将"全市场扫描"改为"指定个股"，方便单票跟踪。
"""
import asyncio
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.quantrisk.data import (
    close_async_session,
    cn_stock_quote_tencent_async,
    cn_stock_kline_fallback,
    cn_fund_flow_minute_async,
    hk_stock_quote_tencent_async,
    hk_kline_async,
    fund_flow_daily_async,
    stock_kline_30m_async,
)
from scripts.quantrisk.swing import swing_score_one


def detect_market(code: str) -> tuple[str, str]:
    """根据代码格式识别市场，返回 (market, clean_code)。"""
    code = code.strip()
    upper = code.upper()
    if upper.endswith(".HK"):
        return "hk", upper[:-3]
    if upper.endswith(".SH") or upper.endswith(".SZ"):
        return "cn", upper[:-3]
    if code.isdigit():
        if len(code) == 5:
            return "hk", code
        if len(code) == 6:
            return "cn", code
        raise ValueError(f"无法识别的市场（5位=港股，6位=A股）: {code}")
    raise ValueError(f"无法识别的代码格式: {code}")


async def _fetch_quote(code: str, market: str) -> dict:
    if market == "hk":
        return await hk_stock_quote_tencent_async(code)
    return await cn_stock_quote_tencent_async(code)


async def _fetch_daily(code: str, market: str) -> list:
    if market == "hk":
        return await hk_kline_async(code, "day", 365)
    return await cn_stock_kline_fallback(code, days=365)


async def _fetch_flow(code: str, market: str) -> dict:
    if market == "hk":
        rows = await fund_flow_daily_async(code, secid_prefix=116, limit=5)
        if not rows:
            return {}
        mains = [r.get("main_net", 0) or 0 for r in rows]
        return {"flow_5d": sum(mains), "flow_1d": mains[-1] if mains else 0, "days": len(mains)}
    rows = await cn_fund_flow_minute_async(code)
    if not rows:
        return {}
    mains = [r.get("main_net", 0) or 0 for r in rows[-5:]]
    return {"flow_5d": sum(mains), "flow_1d": mains[-1] if mains else 0, "days": len(mains)}


async def _fetch_intraday(code: str, market: str) -> list:
    r = await stock_kline_30m_async(code, market, range_="60d")
    return r.get("bars", []) if r.get("available") else []


def _fmt_flow(v: float) -> str:
    return f"{v / 1e8:+.2f}亿" if abs(v) >= 1e6 else f"{v / 1e4:+.2f}万" if abs(v) >= 1e2 else f"{v:+.0f}"


def parse_args() -> tuple[list[str], str, str, str]:
    codes: list[str] = []
    strategy = "tactical"
    run_mode = "research"
    rule_engine = "shadow"
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--strategy" and i + 1 < len(args):
            strategy = args[i + 1].lower()
            i += 2
        elif arg == "--run-mode" and i + 1 < len(args):
            run_mode = args[i + 1].lower()
            i += 2
        elif arg == "--rule-engine" and i + 1 < len(args):
            rule_engine = args[i + 1].lower()
            i += 2
        elif arg.startswith("--"):
            raise ValueError(f"未知参数: {arg}（支持 --strategy/--run-mode/--rule-engine）")
        else:
            codes.append(arg)
            i += 1
    if strategy not in ("band", "tactical", "trend"):
        raise ValueError("--strategy 支持 band（历史别名 tactical|trend）")
    from scripts.quantrisk.strategy_config import normalize_strategy_id
    strategy = normalize_strategy_id(strategy)
    if run_mode not in ("research", "paper", "live"):
        raise ValueError("--run-mode 仅支持 research|paper|live")
    if rule_engine not in ("python", "shadow", "semantica"):
        raise ValueError("--rule-engine 仅支持 python|shadow|semantica")
    return codes, strategy, run_mode, rule_engine


async def analyze_one(code: str, market: str, name_hint: str = "", strategy: str = "tactical", run_mode: str = "research", rule_engine: str = "shadow") -> dict:
    from scripts.quantrisk.data import (company_survey_async, recent_announcements_async,
                                        business_mix_async, finance_brief_async, core_conception_async,
                                        cn_index_quotes_async)
    from scripts.quantrisk.swing import build_index_sync
    q = await _fetch_quote(code, market)
    price = float(q.get("price") or 0)
    name = name_hint or q.get("name") or code
    stock = {"c": code, "n": name, "s": "个股", "p": price, "q": q,
             "market": market, "strategy_id": strategy, "run_mode": run_mode,
             "rule_engine": rule_engine}
    # 道氏原则3·指数相互验证（单股分析同样注入：A股三指数，港股恒指环境）
    stock["index_sync"] = build_index_sync(await cn_index_quotes_async(), market)

    daily, flow, intraday = await asyncio.gather(
        _fetch_daily(code, market), _fetch_flow(code, market), _fetch_intraday(code, market))
    profile, announcements = await asyncio.gather(
        company_survey_async(code, market), recent_announcements_async(code, market))
    extra = {}
    for key, fn in (("business_mix", business_mix_async), ("finance", finance_brief_async),
                    ("conception", core_conception_async)):
        try:
            extra[key] = await fn(code, market)
        except Exception:
            extra[key] = {}
    result = swing_score_one(stock, daily, intraday, flow)
    result["market"] = market
    result["name"] = name
    result["daily_count"] = len(daily)
    result["intraday_count"] = len(intraday)
    result["quote"] = q
    result["profile"] = profile if isinstance(profile, dict) else {"error": "资料获取失败"}
    result["profile_extra"] = extra
    result["announcements"] = announcements if isinstance(announcements, list) else []
    return result


def _direction_emoji(concl: str) -> str:
    if "🟢上升趋势" in concl:
        return "🟢上升趋势"
    if "🔴下降趋势" in concl:
        return "🔴下降趋势"
    if "🟡震荡" in concl:
        return "🟡震荡"
    return "数据缺失"


def _knife_checks(r: dict) -> list[str]:
    """三刀筛辅助数据：量比 / 道氏双周期 / 板块信号。"""
    checks = []
    ratio = float(r["flow"].get("vol_ratio") or 0)
    checks.append(f"📐 第一刀·量比: **{ratio:.2f}**{'✅放量' if ratio >= 1 else '❌缩量'}")
    d_dir = _direction_emoji(r["stroke"].get("conclusion", ""))
    s_dir = _direction_emoji(r["segment"].get("conclusion", ""))
    both_up = d_dir == "🟢上升趋势" and s_dir == "🟢上升趋势"
    checks.append(f"🔮 第二刀·道氏双周期: 日线{d_dir} / 30m{s_dir} "
                  f"{'✅共振偏多' if both_up else '❌未共振'}")
    checks.append(f"🏷️ 第三刀·板块: {r.get('sector', '个股')}（需人工结合主线判断）")
    return checks


def render_one(r: dict) -> str:
    from scripts.quantrisk.swing import _render_profile_line, _entry_exit_conditions
    market_label = "A股" if r["market"] == "cn" else "港股"
    t, f, st, sg = r["trend"], r["flow"], r["stroke"], r["segment"]
    health = r.get("health") or {}
    idx = r.get("index_sync") or {}
    entry_line, exit_line = _entry_exit_conditions(r)
    lines = [
        f"#### {r['name']}（{r['code']}）— {r['status']}",
        f"**现价**：{r['price']:.2f} | **总分**：{r['total']}/100 | "
        f"**止损**：{r['stop_loss']:.2f}（-{r.get('stop_pct', 8.0):.1f}%）| **{r.get('exit_rule', '移动止盈')}**" +
        (f"，ATR{r.get('atr')}" if r.get('atr') else ""),
        f"- 📌 **上车条件**：{entry_line}",
        f"- 🚪 **离场条件**：{exit_line}",
        _render_profile_line(r, r["market"]),
        f"- 日线趋势（30）：{t['reason']}",
        f"- 日线量价/资金（25）：{f['reason']}",
        f"- 日线道氏（20）：{st['reason']}",
        f"- 30分钟道氏（25）：{sg['reason']}（30m K线 {r['intraday_count']} 根）",
        f"- 道氏①定方向：{st.get('conclusion', '数据缺失')}",
        f"- 道氏②验健康：{health.get('note', '数据缺失')}（量比{f.get('vol_ratio', 0)}x）｜指数：{idx.get('note', '数据缺失')}",
        f"- 道氏③找信号：{r.get('dow_step3', '数据缺失')}",
        f"- 三阶段：{r.get('stage', '未知')}｜{r.get('stage_note', '')}",
    ]
    if r.get("direction_conflict"):
        lines.append("- ⚠️ 日线趋势与30分钟道氏趋势方向冲突，禁止当前布局。")
    if r.get("error"):
        lines.append(f"- 数据状态：{r['error']}")
    if r["intraday_count"] < 40:
        lines.append("- ⚠️ 30分钟K线不足40根，30m线段维度按0分，仅观望。")
    lines.append("")
    lines += ["  三刀筛辅助："] + [f"  - {c}" for c in _knife_checks(r)] + [""]
    return "\n".join(lines)


async def main() -> None:
    try:
        args, strategy, run_mode, rule_engine = parse_args()
    except ValueError as exc:
        print(f"❌ {exc}")
        sys.exit(1)
    if not args:
        print(__doc__)
        sys.exit(1)

    ds = datetime.now().strftime("%Y-%m-%d")
    print(f"## 个股波段分析 | {ds}")
    print(f"> 策略：{strategy} | 运行模式：{run_mode} | 规则引擎：{rule_engine}")
    print(f"> 持有周期不预设（高抛低吸，由道氏破前低/移动止盈离场信号自然决定）；纯技术筛选（日线趋势30+量价资金25+日线道氏20+30分钟道氏25），不使用基本面评分。")
    print(f"> 评分说明（满分100）：日线趋势30分=均线多头排列+MACD；日线量价资金25分=量比放量+主力净流入；日线道氏20分=日线摆动点趋势方向（道氏三句话）；30分钟道氏25分=30m摆动点趋势确认短线入场（缺失或与日线趋势冲突则观望）。")
    print(f"> 美股已移出维护范围，本脚本仅支持 A 股（6位）与港股（5位）。")

    results = []
    for code in args:
        try:
            market, clean = detect_market(code)
        except ValueError as e:
            print(f"\n## ❌ {code} — {e}")
            continue
        print(f"\n🔍 分析 {code}（{market_label(market)}）...")
        r = await analyze_one(clean, market, strategy=strategy, run_mode=run_mode, rule_engine=rule_engine)
        results.append(r)
        print(f"✅ {r['name']} {r['code']} — {r['total']}/100 | {r['status']}")

    print("\n### 逐只波段信号\n")
    for r in results:
        print(render_one(r))

    print("### 波段纪律\n")
    print("- 30分钟道氏缺失或与日线趋势冲突：只观望，不补默认分。")
    print("- 三刀筛（量比>1 + 道氏双周期偏多 + 板块有主线）是人工过滤，脚本仅输出辅助数据。")
    print("- 放量突破或回踩确认后再入场；单只仓位建议不超过20%。")
    print("- ⚠️ 道氏滞后性：趋势反转确认天然滞后，标 ⚠️动能走弱预警（价新高但 MACD 柱收缩）的上升趋势严格等回踩支撑、不追当日涨幅、仓位减半；高位放量滞涨视为衰竭信号。")
    print("- 跌破技术止损无条件离场，持仓3-5个交易日缩量滞涨则减仓。")
    print("\n> ⚠️ 声明：基于公开市场行情与技术指标自动生成，不构成投资建议。")

    await close_async_session()


def market_label(market: str) -> str:
    return "A股" if market == "cn" else "港股"


if __name__ == "__main__":
    asyncio.run(main())

"""每日收盘工作流（Phase 1，无 LLM 依赖）。

一条命令完成 A股+港股：扫池 → swing_band 裁决 → outbox 落库 → 冻结快照 →
报告落盘 → 回测记录。skill 只负责解读本模块产出的报告/快照/outbox。

设计要点（2026-09-09 用户确认 Phase 1）：
- 串行跑各市场，避免双市场并行再触发东财资金流限流（eastmoney-fflow 已知坑）
- 固定 run_mode=research；live 下单需独立流程（fail-closed 精神）
- engine 级持有天数回放（run_swing_replay）依赖 walk-forward 基建，属 Phase 2
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .swing import render_swing_report, swing_validate

REPORT_DIR = Path(__file__).resolve().parents[2] / "report"
DEFAULT_SNAPSHOT_DIR = REPORT_DIR / "snapshots"
BACKTEST_FILE = REPORT_DIR / "swing_backtest.jsonl"

_MARKET_LABEL = {"cn": "A股", "hk": "港股"}


def _today() -> str:
    return date.today().isoformat()


def _record_top10(report_path: Path, backtest_file: Path = BACKTEST_FILE) -> list[dict]:
    """复用 backtest_swing 的解析逻辑，把报告 TOP10 追加到回测 jsonl。"""
    from scripts.backtest_swing import _record_from_report
    records = _record_from_report(str(report_path))
    if records:
        backtest_file.parent.mkdir(parents=True, exist_ok=True)
        with open(backtest_file, "a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return records


async def _run_one_market(
    market: str,
    min_stocks: int = 300,
    rule_engine: str = "shadow",
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    record_backtest: bool = True,
    report_dir: Path = REPORT_DIR,
    backtest_file: Path = BACKTEST_FILE,
) -> dict[str, Any]:
    """跑单个市场的完整确定性流程，返回报告/文件/回测记录。"""
    today = _today()
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir = Path(snapshot_dir)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.replace("-", "")
    report_file = report_dir / f"recommend-{market}-{stamp}-daily.md"
    snapshot_file = snapshot_dir / f"{market}-{stamp}.json"

    if market == "cn":
        from .recommend_cn import (cn_recommend_pipeline, fetch_cn_candidate_pool,
                                   fetch_hot_boards, merge_pools)
        candidates = await fetch_cn_candidate_pool(min_stocks=min_stocks)
        if not candidates:
            raise RuntimeError("A股候选池获取失败")
        # 2026-09-17 板块池：热门板块（主力净流入前10×top3）补充合并，失败不阻断主池
        try:
            board = await fetch_hot_boards()
            if board:
                candidates = merge_pools(candidates, board)
        except Exception as exc:
            print(f"[WARN] 热门板块池获取失败（跳过）: {exc}")
        data = await cn_recommend_pipeline(
            candidates, mode="swing", strategy="band", run_mode="research",
            rule_engine=rule_engine, snapshot=str(snapshot_file))
    elif market == "hk":
        from .recommend_hk import hk_recommend_pipeline
        data = await hk_recommend_pipeline(
            min_stocks=min_stocks, mode="swing", strategy="band", run_mode="research",
            rule_engine=rule_engine, snapshot=str(snapshot_file))
    else:
        raise ValueError(f"未知市场: {market}（可选: cn, hk）")

    # 2026-09-17：快照补 pool_mode（A1 按池版本分组统计；历史快照无此字段归 mcap-only）
    if snapshot_file.exists():
        try:
            snap = json.loads(snapshot_file.read_text(encoding="utf-8"))
            snap["pool_mode"] = "amount+board" if market == "cn" else "amount"
            snapshot_file.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            print(f"[WARN] 快照 pool_mode 补写失败: {exc}")

    swing_validate(data)
    markdown = render_swing_report(data, market)
    report_file.write_text(markdown, encoding="utf-8")
    records = _record_top10(report_file, backtest_file) if record_backtest else []
    return {
        "market": market,
        "report": data,
        "file": str(report_file),
        "snapshot": str(snapshot_file) if snapshot_file.exists() else "",
        "records": records,
        "top10": list(data.get("top10") or []),
    }


async def run_daily(
    markets=("cn", "hk"),
    min_stocks: int = 300,
    rule_engine: str = "shadow",
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    record_backtest: bool = True,
    report_dir: Path = REPORT_DIR,
    backtest_file: Path = BACKTEST_FILE,
) -> dict[str, Any]:
    """串行跑各市场；单市场失败不中断其余市场，结果含 error 字段。"""
    if isinstance(markets, str):
        markets = tuple(m.strip() for m in markets.split(",") if m.strip())
    if not markets:
        raise ValueError("至少指定一个市场: cn/hk")
    report_dir = Path(report_dir)
    result: dict[str, Any] = {
        "date": _today(), "strategy": "swing_band", "rule_engine": rule_engine,
        "markets": {}, "outbox": str(report_dir / "decision_outbox.sqlite3"),
    }
    for market in markets:
        try:
            result["markets"][market] = await _run_one_market(
                market, min_stocks=min_stocks, rule_engine=rule_engine,
                snapshot_dir=snapshot_dir, record_backtest=record_backtest,
                report_dir=report_dir, backtest_file=backtest_file)
        except Exception as exc:  # 单市场失败不拖垮整轮
            result["markets"][market] = {
                "market": market, "error": f"{type(exc).__name__}: {exc}",
                "report": {}, "file": "", "snapshot": "", "records": [], "top10": [],
            }
    for m in result["markets"].values():
        report = m.get("report") or {}
        if report.get("run_id"):
            result["outbox_run_id"] = report["run_id"]
            break
    return result


def render_daily_summary(result: dict[str, Any]) -> str:
    """生成控制台/日志摘要：每市场产物路径 + TOP3 + 回测记录数 + outbox。"""
    lines = [
        f"# 📅 每日波段信号 {result.get('date', '')}",
        f"策略 swing_band（research）｜规则引擎 {result.get('rule_engine', '')}",
        "",
    ]
    markets = result.get("markets") or {}
    if not markets:
        lines.append("⚠️ 本轮未运行任何市场。")
    for market, m in markets.items():
        label = _MARKET_LABEL.get(market, market)
        if m.get("error"):
            lines.append(f"## {label}（{market}）❌ 失败：{m['error']}")
            lines.append("")
            continue
        lines.append(f"## {label}（{market}）")
        lines.append(f"- 报告：{m.get('file') or '—'}")
        lines.append(f"- 快照：{m.get('snapshot') or '—'}")
        gate = (m.get("report") or {}).get("gate_stats") or {}
        if gate:
            lines.append(f"- ⛔ 基本面门禁：评估 {gate.get('evaluated', 0)} 只，否决 {gate.get('vetoed', 0)} 只")
        top10 = m.get("top10") or []
        if top10:
            lines.append("- TOP10：")
            for row in top10[:3]:
                lines.append(f"  - {row.get('name', '?')}（{row.get('code', '?')}）{row.get('verdict', '')}")
        else:
            lines.append("- TOP10：无（数据缺失或全部拦截）")
        lines.append(f"- 回测记录：{len(m.get('records') or [])} 只 → report/swing_backtest.jsonl")
        lines.append("")
    lines.append(f"📦 outbox：{result.get('outbox', '')}（run_id={result.get('outbox_run_id', '—')}）")
    lines.append("")
    lines.append("> ⚠️ 声明：基于公开市场数据自动生成，不构成投资建议。")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 策略层信号（TrendGate 当日闸门 + 双动量 TOP10，2026-10-13 新增）
# ─────────────────────────────────────────────────────────────
async def _trendgate_index_kline(days: int, symbol: str):
    """闸门指数日K（沪深300 / 恒指），复用腾讯 K 线多域名降级。"""
    import pandas as pd
    from . import data
    d = await data._tencent_kline_get(f"{symbol},day,,,{days},qfq")
    kdata = (((d or {}).get("data") or {}).get(symbol) or {})
    rows = kdata.get("day") or kdata.get("qfqday") or kdata.get("qfq") or []
    if not rows:
        return None
    s = pd.Series({r[0]: float(r[2]) for r in rows if len(r) >= 3})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


async def trendgate_signal(market: str, gate_ma: int = 30, days: int = 800) -> dict[str, Any]:
    """TrendGate 策略当日信号（A股中证500+沪深300闸门 / 港股恒指成分池+恒指闸门）。

    不跑回测，秒级出信号：池与行情矩阵直接复用 rotation 缓存（需先跑过对应
    backtest_trendgate 生成 universe_{cn,hk_hsi}.json 与 {cn,hk_hsi}_d{days} 矩阵），
    闸门指数实时拉取日K；输出截至矩阵最后交易日的闸门开关 + 连续确认天数 + 双动量 TOP10。
    """
    import pandas as pd
    from . import rotation as rot
    from .trendgate import HS300_SYMBOL, HSI_SYMBOL

    hsi_pool = market == "hk"
    uni_key = "hk_hsi" if hsi_pool else "cn"
    universe = rot.load_universe_cache(uni_key)
    if not universe:
        return {"market": market, "error": f"无池缓存 universe_{uni_key}.json（先跑 backtest_trendgate --pool {('hsi ' if hsi_pool else '')}--market {market} 生成）"}
    hit = rot.cache_matrix(f"{uni_key}_d{days}")
    if hit is None:
        return {"market": market, "error": f"无行情缓存 {uni_key}_d{days}（先跑 backtest_trendgate 生成）"}
    close = hit[0].sort_index()
    if close.empty:
        return {"market": market, "error": "行情矩阵为空"}

    gate_sym = HSI_SYMBOL if hsi_pool else HS300_SYMBOL
    gi = await _trendgate_index_kline(days, gate_sym)
    if gi is None:
        return {"market": market, "error": f"闸门指数 {gate_sym} 获取失败（fail-closed）"}

    last_day = close.index[-1]
    gi = gi.loc[gi.index <= last_day]
    if len(gi) < gate_ma + 1:
        return {"market": market, "error": f"闸门指数数据不足（{len(gi)} 日 < MA{gate_ma}）"}

    ma = gi.rolling(gate_ma).mean()
    above = gi > ma
    confirm_days = 0
    for v in above.iloc[::-1]:
        if bool(v):
            confirm_days += 1
        else:
            break
    gate_on = bool(above.iloc[-1])
    if gate_on:
        stance = "🟢 在场（闸门开，可持仓）"
    elif confirm_days > 0:
        stance = f"🟡 闸门确认中（已站上 {confirm_days} 日，需连续 {3 if gate_ma >= 20 else 1} 日再入场）"
    else:
        stance = "🔴 空仓等待（闸门关闭）"

    score = rot.cross_section_scores(close)
    try:
        sel = rot.select_on_date(score, last_day, min_score=0.65, top_n=10)
    except Exception:
        sel = pd.Series(dtype=float)
    name_map = {u["code"]: u.get("name", "") for u in universe}
    top10 = [{"code": c, "name": name_map.get(c, ""), "score": round(float(s), 3)}
             for c, s in sel.items()]

    return {
        "market": market, "label": _MARKET_LABEL.get(market, market),
        "as_of": last_day.strftime("%Y-%m-%d"), "gate_ma": gate_ma,
        "gate": {"symbol": gate_sym, "close": round(float(gi.iloc[-1]), 2),
                 "ma": round(float(ma.iloc[-1]), 2), "on": gate_on,
                 "confirm_days": confirm_days},
        "top10": top10, "stance": stance,
        "universe_count": len(universe) if close.shape[1] else 0,
    }


def render_strategy_signals(signals: list[dict]) -> str:
    """渲染 TrendGate 策略信号报告（闸门状态 + 双动量 TOP10）。"""
    lines = []
    for sig in signals:
        if sig.get("error"):
            lines.append(f"## {sig.get('label', sig.get('market', ''))}（{sig.get('market', '')}）❌ {sig['error']}")
            lines.append("")
            continue
        g = sig["gate"]
        lines.append(f"## {sig['label']}（{sig.get('market', '')}）· 信号截至 {sig.get('as_of', '')} · 池 {sig.get('universe_count', '')} 只")
        lines.append(f"- **闸门 {g['symbol']} MA{sig.get('gate_ma')}**：收盘 {g['close']} vs MA {g['ma']} → {sig.get('stance', '')}（连续确认 {g['confirm_days']} 日）")
        top = sig.get("top10") or []
        if top:
            lines.append("- **双动量 TOP10（得分≥0.65，调仓日买入候选）**：")
            for i, row in enumerate(top, 1):
                lines.append(f"  {i}. {row['name']}（{row['code']}）得分 {row['score']}")
        else:
            lines.append("- **双动量 TOP10**：当前无合格标的（全部低于阈值或数据缺失）")
        lines.append("")
    lines.append("> ⚠️ 声明：基于公开市场数据自动生成，不构成投资建议（策略层信号，非个股买卖建议）。")
    return "\n".join(lines)


__all__ = ["run_daily", "render_daily_summary", "_run_one_market", "_record_top10",
           "trendgate_signal", "render_strategy_signals",
           "REPORT_DIR", "DEFAULT_SNAPSHOT_DIR", "BACKTEST_FILE"]

"""A1 — 快照截面 T+N 统计（2026-09-17 grill 落地）。

读 report/snapshots/*.json 的**全量 results**（每快照 80 只，非 TOP10），按
status 三档 / total 分数段 / verdict / 板块池来源 / pool_mode 分组，计算 T+5/10/20
胜率与平均收益。T+N 价格用**快照日之后的真实收盘价**回填（复用 backtest_swing 的
_fetch_close/_returns），快照是当日实时冻结 → 天然无幸存者偏差。

用法：
  uv run scripts/backtest_snapshot.py --market cn [--days 5,10,20]
  uv run scripts/backtest_snapshot.py --market all
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# 项目根目录加入 sys.path（与其他 scripts/*.py 一致，保证 scripts.quantrisk 可导入）
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPORT_DIR = Path(__file__).resolve().parents[1] / "report"
SNAPSHOT_DIR = REPORT_DIR / "snapshots"

STATUS_GROUPS = ("当前可布局", "谨慎布局", "观望")
BAND_GROUPS = (("≥85", 85, 1000), ("80-84", 80, 85), ("<80", 0, 80))
VERDICT_GROUPS = ("ALLOW", "WATCH", "EXIT", "BLOCK")


def load_snapshots(market: str) -> list[dict[str, Any]]:
    snaps = []
    for p in sorted(SNAPSHOT_DIR.glob(f"{market}-*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        results = d.get("results") or []
        if not results:
            continue
        as_of = d.get("date") or (results[0].get("as_of") or "")[:10]
        # board_hot 标记在 stocks 里（results 不复制该字段），建 code → board_hot 映射
        board_of = {s.get("c"): s.get("board_hot") or ""
                    for s in (d.get("stocks") or [])}
        snaps.append({
            "file": p.name,
            "as_of": as_of,
            "pool_mode": d.get("pool_mode", "mcap-only"),
            "results": results,
            "board_of": board_of,
        })
    return snaps


def _rows_from_snapshot(snap: dict[str, Any], market: str) -> list[dict[str, Any]]:
    rows = []
    for r in snap["results"]:
        code = r.get("code")
        if not code:
            continue
        # 门禁状态（2026-09-24 Q4-B）：gate.state 优先，兼容顶层 veto 字段；历史快照两者皆无 → 未评估
        gate_state = (r.get("gate") or {}).get("state") or ""
        if not gate_state and "veto" in r:
            gate_state = "veto" if r.get("veto") else "pass"
        rows.append({
            "as_of": snap["as_of"], "market": market, "code": code,
            "name": r.get("name") or "", "status": r.get("status") or "观望",
            "total": r.get("total") or 0, "verdict": r.get("verdict") or "WATCH",
            "board": snap["board_of"].get(code, ""),
            "gate": gate_state,
        })
    return rows


async def build_returns_map(rows: list[dict[str, Any]], market: str, days: list[int],
                            concurrency: int = 12) -> dict[tuple[str, str], dict[int, float | None]]:
    """对去重后的 code 并发拉日K，缓存 pairs；再对每个 (as_of, code) 算 T+N 收益。"""
    from scripts.backtest_swing import _fetch_close, _returns

    codes = sorted({r["code"] for r in rows})
    pairs_map: dict[str, list] = {}
    sem = asyncio.Semaphore(concurrency)

    async def fetch(code: str) -> None:
        async with sem:
            try:
                pairs_map[code] = await _fetch_close(code, market)
            except Exception:
                pairs_map[code] = []

    await asyncio.gather(*[fetch(c) for c in codes])

    out: dict[tuple[str, str], dict[int, float | None]] = {}
    for r in rows:
        pairs = pairs_map.get(r["code"], [])
        out[(r["as_of"], r["code"])] = {d: _returns(pairs, r["as_of"], d) for d in days}
    return out


def _fmt(v: float | None) -> str:
    return f"{v:+.1f}%" if v is not None else "—"


def render_report(snaps: list[dict[str, Any]], market: str, days: list[int],
                  ret_map: dict[tuple[str, str], dict[int, float | None]]) -> str:
    lines = [
        f"# 📊 快照截面 T+N 统计（A1）｜市场 {market}",
        f"快照数: {len(snaps)} ｜ 窗口: T+{days} ｜ 收益=快照日后真实收盘价",
        f"池版本(pool_mode): {sorted({s['pool_mode'] for s in snaps})}",
        "",
    ]

    def section(title: str, groups: list[tuple[str, Any]]) -> None:
        lines.append(f"## {title}")
        header = "| 分组 | 样本 | " + " | ".join(f"T+{d} 胜率(均收益)" for d in days) + " |"
        lines.append(header)
        lines.append("|:---|:---:|" + "|".join([":---:"] * len(days)) + "|")
        for label, key in groups:
            cells = []
            total_n = 0
            for d in days:
                vals = [ret_map[(r["as_of"], r["code"])][d] for r in key]
                vals = [v for v in vals if v is not None]
                if vals:
                    total_n = max(total_n, len(vals))
                    win = sum(1 for v in vals if v > 0)
                    cells.append(f"{win}/{len(vals)}={win/len(vals)*100:.0f}%({sum(vals)/len(vals):+.1f}%)")
                else:
                    cells.append("—")
            lines.append(f"| {label} | {len(key)} | " + " | ".join(cells) + " |")
        lines.append("")

    all_rows = [r for s in snaps for r in _rows_from_snapshot(s, market)]
    # status 三档
    section("按状态（三档）", [(g, [r for r in all_rows if r["status"] == g]) for g in STATUS_GROUPS])
    # 分数段
    section("按总分（分数段）",
            [(label, [r for r in all_rows if lo <= r["total"] < hi]) for label, lo, hi in BAND_GROUPS])
    # verdict
    section("按裁决（verdict）", [(g, [r for r in all_rows if r["verdict"] == g]) for g in VERDICT_GROUPS])
    # 板块池 vs 主池
    section("按来源（板块池 vs 主池）", [
        ("板块池(热门板块top3)", [r for r in all_rows if r["board"]]),
        ("主池", [r for r in all_rows if not r["board"]]),
    ])
    # 基本面门禁（2026-09-24 Q4-B：通过组 vs 否决组条件收益差）
    section("按基本面门禁", [
        ("门禁通过", [r for r in all_rows if r["gate"] == "pass"]),
        ("门禁否决", [r for r in all_rows if r["gate"] == "veto"]),
        ("未评估（财务缺失/历史快照）", [r for r in all_rows if r["gate"] not in ("pass", "veto")]),
    ])
    # pool_mode
    section("按池版本(pool_mode)", [
        (mode, [r for s in snaps if s["pool_mode"] == mode for r in _rows_from_snapshot(s, market)])
        for mode in sorted({s["pool_mode"] for s in snaps})
    ])
    lines.append(f"> 口径：样本=该分组入选信号数；胜率=T+N 收盘价高于快照日收盘价的占比；均收益=平均涨跌幅。"
                 f"数据不足时显示 —。A1 验证的是「入选信号的条件胜率」，不是策略绝对收益。")
    return "\n".join(lines)


async def main(market: str, days: list[int]) -> int:
    from scripts.quantrisk.data import close_async_session

    markets = ("cn", "hk") if market == "all" else (market,)
    for mkt in markets:
        snaps = load_snapshots(mkt)
        if not snaps:
            print(f"[{mkt}] 无快照（report/snapshots/{mkt}-*.json）")
            continue
        rows = [r for s in snaps for r in _rows_from_snapshot(s, mkt)]
        print(f"[{mkt}] 快照 {len(snaps)} 个, 样本 {len(rows)} 条（去重 code {len({r['code'] for r in rows})}）…")
        ret_map = await build_returns_map(rows, mkt, days)
        md = render_report(snaps, mkt, days, ret_map)
        out = REPORT_DIR / f"swing_snapshot_stats_{mkt}.md"
        out.write_text(md, encoding="utf-8")
        print(md)
        print(f"→ {out}")
    await close_async_session()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="A1 快照截面 T+N 统计")
    ap.add_argument("--market", default="all", choices=("cn", "hk", "all"))
    ap.add_argument("--days", default="5,10,20")
    args = ap.parse_args()
    dl = [int(x) for x in args.days.split(",") if x.strip().isdigit()] or [5, 10, 20]
    sys.exit(asyncio.run(main(args.market, dl)))

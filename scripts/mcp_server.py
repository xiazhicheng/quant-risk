"""quant-risk MCP server — 供 AI 工具（Codex / Claude Code / ZCode）调用的确定性工具层。

Transport（2026-09-09 用户确认 streamable http + ZCode 适配）：
  stdio            本地：uv run scripts/mcp_server.py
  streamable-http  远程/容器：uv run scripts/mcp_server.py --transport http --host 0.0.0.0 --port 8765

工具（全部复用 scripts/quantrisk 现有模块，不重写；固定 research 模式不接 live）：
  analyze_stock(code)    单股波段分析 → JSON（四维评分/规则裁决/状态/止损/三tab）
  run_daily(market)      每日收盘工作流（单市场，约 2-3 分钟）→ 摘要 + 报告路径
  run_recommend(market)  波段推荐 TOP10 → 结论表 JSON（约 3-5 分钟）
  backtest_stats(days)   回测累计统计 → 胜率/分数段/状态分组
  get_daily_report(market, date)  读取已生成 daily 报告全文
"""
from __future__ import annotations

import argparse
import builtins
import json
import os
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

# --- MCP stdio 协议护栏（2026-09-17 修复 run_daily Error executing tool）---
# stdio transport 下 stdout 只能承载 JSON-RPC 帧；data.py 满屏 [WARN] print 会污染
# 协议导致客户端解析失败/断连。把进程内所有 print 定向 stderr，并固定 cwd 到项目根
# （daily/data 内部均为相对路径 report/...，cwd 不对时写文件抛错）。
_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_ROOT)

_builtin_print = builtins.print


def _print_to_stderr(*args: Any, **kwargs: Any) -> None:
    kwargs.setdefault("file", sys.stderr)
    _builtin_print(*args, **kwargs)


mcp = MCPServer(
    "quant-risk",
    instructions=(
        "A股+港股量化波段系统：单股波段分析/每日收盘信号/波段推荐/回测统计。"
        "数据源为免费公开接口；纯技术筛选（道氏+ATR 移动止盈），固定 research 模式不接实盘。"
    ),
)


@mcp.tool()
async def analyze_stock(code: str) -> dict[str, Any]:
    """单股波段分析（A股 6 位 / 港股 5 位）。返回四维评分、规则裁决、三档状态、止损/移动止盈、三tab简介。

    耗时约 30s-2min（拉日K/30m/资金流/F10）。状态三档：当前可布局/谨慎布局/观望；裁决含 BLOCK/EXIT/WATCH/ALLOW。
    """
    from scripts.analyze_swing import analyze_one, detect_market

    market, clean = detect_market(code)
    r = await analyze_one(clean, market, strategy="band")
    prof = r.get("profile") or {}
    extra = r.get("profile_extra") or {}
    return {
        "code": r.get("code"), "name": r.get("name"), "market": r.get("market"),
        "price": r.get("price"), "total": r.get("total"),
        "trend_score": (r.get("trend") or {}).get("score"),
        "flow_score": (r.get("flow") or {}).get("score"),
        "stroke_score": (r.get("stroke") or {}).get("score"),
        "segment_score": (r.get("segment") or {}).get("score"),
        "verdict": r.get("verdict"), "entry_eligible": r.get("entry_eligible"),
        "status": r.get("status"), "decision_engine": r.get("decision_engine"),
        "shadow_match": r.get("shadow_match"),
        "stop_loss": r.get("stop_loss"), "trail_stop": r.get("trail_stop"),
        "exit_rule": r.get("exit_rule"), "atr": r.get("atr"),
        "dow_conclusion": (r.get("stroke") or {}).get("conclusion"),
        "profile": {
            "industry": prof.get("industry"), "brief": str(prof.get("brief", ""))[:120],
            "pe_ttm": prof.get("pe_ttm"), "roe": prof.get("roe"),
        },
        "finance": extra.get("finance") or {},
        "boards": ((extra.get("conception") or {}).get("boards") or [])[:6],
        "announcements": [{"date": a.get("date"), "title": a.get("title")}
                          for a in (r.get("announcements") or [])[:3]],
    }


@mcp.tool()
async def run_daily(market: str = "cn") -> dict[str, Any]:
    """每日收盘工作流（单市场，约 2-3 分钟）：扫池→swing_band 裁决→outbox 落库→快照→报告→回测记录。

    返回摘要与报告路径；长耗时请耐心等待，之后可用 get_daily_report 读全文。
    """
    from scripts.quantrisk.daily import run_daily as _run_daily

    result = await _run_daily(markets=(market,), record_backtest=True)
    m = result["markets"].get(market, {})
    return {
        "date": result["date"], "market": market, "strategy": result["strategy"],
        "rule_engine": result["rule_engine"],
        "error": m.get("error"),
        "report_file": m.get("file"), "snapshot": m.get("snapshot"),
        "outbox": result.get("outbox"), "outbox_run_id": result.get("outbox_run_id"),
        "top10": [{"name": row.get("name"), "code": row.get("code"), "verdict": row.get("verdict"),
                   "total": row.get("total")} for row in (m.get("top10") or [])[:10]],
        "backtest_records": len(m.get("records") or []),
    }


@mcp.tool()
async def run_recommend(market: str = "cn") -> dict[str, Any]:
    """波段推荐 TOP10（全市场扫池，约 3-5 分钟）。返回结论表（评分/操作）与报告路径。

    注意：与 run_daily 同源（同一 pipeline），日常信号建议直接用 run_daily。
    """
    from scripts.recommend import run_cn_recommendation, run_hk_recommendation

    if market == "cn":
        data = await run_cn_recommendation(min_stocks=300, mode="swing", strategy="band",
                                           run_mode="research", rule_engine="shadow")
    else:
        data = await run_hk_recommendation(min_stocks=300, mode="swing", strategy="band",
                                           run_mode="research", rule_engine="shadow")
    return {
        "date": data.get("date"), "market": data.get("market"), "run_id": data.get("run_id"),
        "top10": data.get("top10") or [],
        "outbox": data.get("outbox"),
    }


@mcp.tool()
async def backtest_stats(days: str = "5,10,20") -> dict[str, Any]:
    """回测累计统计：读 report/swing_backtest.jsonl，按市场/分数段/状态分组计算 T+N 胜率。

    先要有记录（daily/推荐已自动记录 TOP10）。分数段：≥85 / 80-84 / <80；状态：当前可布局/谨慎布局/观望。
    """
    import os

    from scripts.backtest_swing import _fetch_close, _returns
    from scripts.quantrisk.data import close_async_session

    backtest_file = Path("report") / "swing_backtest.jsonl"
    if not backtest_file.exists():
        return {"error": f"无记录文件：{backtest_file}（先跑 daily 或推荐）"}
    records = [json.loads(line) for line in backtest_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not records:
        return {"error": "记录为空"}
    days_list = [int(x) for x in days.split(",") if x.strip().isdigit()] or [5, 10, 20]
    groups: dict[str, list[dict]] = {"cn": [], "hk": []}
    for r in records:
        groups["cn" if len(r["code"]) == 6 else "hk"].append(r)
    out: dict[str, Any] = {"records": len(records), "days": days_list, "markets": {}}
    for market, items in groups.items():
        if not items:
            continue
        wins = {d: [0, 0] for d in days_list}
        rows = []
        for r in items:
            pairs = await _fetch_close(r["code"], market)
            rets = {d: _returns(pairs, r["date"], d) for d in days_list}
            for d in days_list:
                v = rets[d]
                if v is not None:
                    wins[d][0] += 1
                    wins[d][1] += int(v > 0)
            rows.append({"date": r["date"], "code": r["code"], "name": r["name"],
                         "status": r["status"], "total": r.get("total"), "returns": rets})
        mkt = {"samples": len(items), "rows": rows[:30], "win_rate": {}}
        for d in days_list:
            n, w = wins[d]
            mkt["win_rate"][f"T+{d}"] = {"samples": n, "wins": w,
                                          "rate_pct": round(w / n * 100, 1) if n else None}
        # 分数段 + 状态分组（T+ 最短窗口）
        d0 = days_list[0]
        bands: dict[str, Any] = {}
        for label, (lo, hi) in ({"≥85": (85, 1000), "80-84": (80, 85), "<80": (0, 80)}).items():
            grp = [r for r in items if lo <= r.get("total", 0) < hi]
            n = w = 0
            for r in grp:
                v = _returns(await _fetch_close(r["code"], market), r["date"], d0)
                if v is not None:
                    n += 1
                    w += int(v > 0)
            bands[label] = {"samples": len(grp), "with_data": n,
                            "rate_pct": round(w / n * 100, 1) if n else None}
        mkt["bands"] = bands
        out["markets"][market] = mkt
    await close_async_session()
    return out


@mcp.tool()
def get_daily_report(market: str = "cn", date: str = "") -> str:
    """读取已生成的 daily 报告全文（markdown）。date 格式 YYYY-MM-DD，默认今天。"""
    stamp = (date or _date.today().isoformat()).replace("-", "")
    p = Path("report") / f"recommend-{market}-{stamp}-daily.md"
    if not p.exists():
        return f"报告不存在：{p}（先跑 run_daily）"
    return p.read_text(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="quant-risk MCP server（stdio / streamable-http）")
    ap.add_argument("--transport", choices=("stdio", "http"), default="stdio",
                    help="stdio=本地进程；http=Streamable HTTP（远程/容器/ZCode 桥接）")
    ap.add_argument("--host", default="127.0.0.1", help="http transport 监听地址（容器内用 0.0.0.0）")
    ap.add_argument("--port", type=int, default=8765, help="http transport 端口")
    args = ap.parse_args()
    if args.transport == "http":
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        # stdio 模式下 stdout 只能承载 JSON-RPC 帧；data.py 的 [WARN] print 会污染
        # 协议导致客户端解析失败/断连，故仅在此刻把进程内 print 定向 stderr。
        builtins.print = _print_to_stderr
        mcp.run()


if __name__ == "__main__":
    main()

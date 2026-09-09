"""MCP server 测试（离线：mock 数据层，不真拉网络）。"""
import asyncio

import scripts.mcp_server as ms


def test_mcp_tools_registered():
    """5 个工具全部注册（确定性操作层）。"""
    tools = asyncio.run(ms.mcp.list_tools())
    names = [t.name for t in tools]
    assert {"analyze_stock", "run_daily", "run_recommend", "backtest_stats", "get_daily_report"} <= set(names)


def test_analyze_stock_mocked(monkeypatch):
    """单股分析返回结构化 JSON（评分/裁决/止损/三tab 摘要）。"""
    async def fake_analyze_one(code, market, strategy="band"):
        return {
            "code": code, "name": "测试", "market": market, "price": 10.5, "total": 85.0,
            "trend": {"score": 27}, "flow": {"score": 17}, "stroke": {"score": 20},
            "segment": {"score": 21}, "verdict": "WATCH", "entry_eligible": False,
            "status": "谨慎布局：上升趋势但动能走弱", "decision_engine": "shadow",
            "shadow_match": True, "stop_loss": 9.66, "trail_stop": 9.9, "exit_rule": "跌破前低离场",
            "atr": 0.42, "profile": {"industry": "测试行业", "brief": "测试公司简介", "pe_ttm": 8.0, "roe": 12.0},
            "profile_extra": {"finance": {"report_date": "2026-06-30", "revenue": 100.0},
                              "conception": {"boards": ["算力概念", "测试板块"]}},
            "announcements": [{"date": "2026-09-01", "title": "重大资产重组"}],
        }

    monkeypatch.setattr("scripts.analyze_swing.analyze_one", fake_analyze_one)
    monkeypatch.setattr("scripts.analyze_swing.detect_market", lambda code: ("cn", code))
    out = asyncio.run(ms.analyze_stock("600000"))
    assert out["code"] == "600000" and out["verdict"] == "WATCH"
    assert out["total"] == 85.0 and out["stop_loss"] == 9.66
    assert out["profile"]["industry"] == "测试行业"
    assert out["boards"][0] == "算力概念"
    assert out["announcements"][0]["title"] == "重大资产重组"


def test_get_daily_report_missing():
    """报告不存在返回明确提示（离线）。"""
    text = ms.get_daily_report("cn", "2099-01-01")
    assert "报告不存在" in text


def test_backtest_stats_error_without_file(monkeypatch, tmp_path):
    """无回测记录文件时返回 error（离线，重定向 report 目录）。"""
    import scripts.mcp_server as ms_mod
    monkeypatch.setattr(ms_mod, "Path", lambda *a: tmp_path / "report")
    out = asyncio.run(ms_mod.backtest_stats())
    assert "error" in out

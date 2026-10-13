"""daily 收盘工作流测试（离线 mock，风格对齐 test_strategy_pipeline.py）。"""
import asyncio
import json

import scripts.quantrisk.daily as daily

MARKDOWN_WITH_TOP10 = """# A股波段信号
#### 1. 测试（600000）— 🟢当前可布局
**现价**：10.0 | **总分**：85.0/100 | **趋势**：27 | **量价**：20 | **道氏**：18 | **30m**：20
"""


def cn_report(**over):
    base = {
        "date": daily._today(), "market": "cn", "selection_mode": "swing", "passed_count": 1,
        "run_id": "abc123", "outbox": "report/decision_outbox.sqlite3",
        "top10": [{"rank": 1, "code": "600000", "name": "测试", "sector": "其他",
                   "trend_score": 27.0, "flow_score": 20.0, "stroke_score": 18.0,
                   "segment_score": 20.0, "total": 85.0, "advice": "🟢当前可布局",
                   "verdict": "ALLOW", "entry_eligible": True, "rule_hits": []}],
        "details": [], "summary": [],
    }
    base.update(over)
    return base


def stamp():
    return daily._today().replace("-", "")


def test_run_one_market_cn_writes_report_and_backtest(tmp_path, monkeypatch):
    """A股单市场：报告落盘 + TOP10 追加到回测 jsonl（真实解析 markdown）。"""
    report_dir, snap_dir = tmp_path / "report", tmp_path / "snapshots"
    backtest_file = tmp_path / "swing_backtest.jsonl"

    async def fake_fetch(min_stocks):
        assert min_stocks == 300
        return [{"c": "600000", "n": "测试", "s": "其他", "p": 10.0}]

    async def fake_pipeline(candidates, **kw):
        assert kw["mode"] == "swing" and kw["strategy"] == "band"
        assert kw["run_mode"] == "research"
        assert kw["snapshot"] == str(snap_dir / f"cn-{stamp()}.json")
        return cn_report()

    monkeypatch.setattr("scripts.quantrisk.recommend_cn.fetch_cn_candidate_pool", fake_fetch)
    monkeypatch.setattr("scripts.quantrisk.recommend_cn.cn_recommend_pipeline", fake_pipeline)
    monkeypatch.setattr(daily, "render_swing_report", lambda data, market: MARKDOWN_WITH_TOP10)
    monkeypatch.setattr(daily, "swing_validate", lambda data: None)

    out = asyncio.run(daily._run_one_market("cn", min_stocks=300, snapshot_dir=snap_dir,
                                            report_dir=report_dir, backtest_file=backtest_file))
    report_file = report_dir / f"recommend-cn-{stamp()}-daily.md"
    assert out["file"] == str(report_file)
    assert report_file.read_text(encoding="utf-8") == MARKDOWN_WITH_TOP10
    assert out["top10"][0]["code"] == "600000"
    records = [json.loads(line) for line in backtest_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 1 and records[0]["code"] == "600000" and records[0]["total"] == 85.0
    assert out["records"][0]["code"] == "600000"


def test_run_one_market_hk_and_snapshot_exist(tmp_path, monkeypatch):
    """港股路径 + 快照文件存在时 snapshot 字段返回路径。"""
    report_dir, snap_dir = tmp_path / "report", tmp_path / "snapshots"
    backtest_file = tmp_path / "swing_backtest.jsonl"

    async def fake_pipeline(**kw):
        snap = kw["snapshot"]
        snap_dir.mkdir(parents=True, exist_ok=True)
        with open(snap, "w", encoding="utf-8") as f:
            f.write("{}")
        return cn_report(market="hk")

    monkeypatch.setattr("scripts.quantrisk.recommend_hk.hk_recommend_pipeline", fake_pipeline)
    monkeypatch.setattr(daily, "render_swing_report", lambda data, market: "hk markdown")
    monkeypatch.setattr(daily, "swing_validate", lambda data: None)

    out = asyncio.run(daily._run_one_market("hk", snapshot_dir=snap_dir,
                                            report_dir=report_dir, backtest_file=backtest_file))
    assert out["snapshot"] == str(snap_dir / f"hk-{stamp()}.json")
    assert (report_dir / f"recommend-hk-{stamp()}-daily.md").exists()


def test_no_backtest_skips_jsonl(tmp_path, monkeypatch):
    """record_backtest=False 不写回测 jsonl。"""
    report_dir, snap_dir = tmp_path / "report", tmp_path / "snapshots"
    backtest_file = tmp_path / "swing_backtest.jsonl"

    async def fake_fetch(min_stocks):
        return [{"c": "600000"}]

    async def fake_pipeline(candidates, **kw):
        return cn_report()

    monkeypatch.setattr("scripts.quantrisk.recommend_cn.fetch_cn_candidate_pool", fake_fetch)
    monkeypatch.setattr("scripts.quantrisk.recommend_cn.cn_recommend_pipeline", fake_pipeline)
    monkeypatch.setattr(daily, "render_swing_report", lambda data, market: MARKDOWN_WITH_TOP10)
    monkeypatch.setattr(daily, "swing_validate", lambda data: None)

    out = asyncio.run(daily._run_one_market("cn", snapshot_dir=snap_dir, report_dir=report_dir,
                                            backtest_file=backtest_file, record_backtest=False))
    assert out["records"] == []
    assert not backtest_file.exists()


def test_unknown_market_raises(tmp_path, monkeypatch):
    import pytest
    with pytest.raises(ValueError):
        asyncio.run(daily._run_one_market("us", report_dir=tmp_path / "report"))


def test_run_daily_isolates_market_failure(tmp_path, monkeypatch):
    """单市场失败不中断另一市场；成功市场提供 outbox_run_id。"""
    async def fake_one(market, **kw):
        if market == "cn":
            return {"market": "cn", "report": cn_report(), "file": "f.md",
                    "snapshot": "", "records": [], "top10": [{"name": "测试", "code": "600000", "verdict": "ALLOW"}]}
        raise RuntimeError("数据源限流")

    monkeypatch.setattr(daily, "_run_one_market", fake_one)
    result = asyncio.run(daily.run_daily(markets=("cn", "hk"), report_dir=tmp_path / "report"))
    assert result["markets"]["cn"]["file"] == "f.md"
    assert "error" in result["markets"]["hk"]
    assert result["outbox_run_id"] == "abc123"
    assert str(result["outbox"]).endswith("decision_outbox.sqlite3")


def test_run_daily_runs_markets_serially(monkeypatch):
    """串行执行：cn 在 hk 之前完成。"""
    order = []

    async def fake_one(market, **kw):
        order.append(market)
        return {"market": market, "report": cn_report(), "file": "", "snapshot": "",
                "records": [], "top10": []}

    monkeypatch.setattr(daily, "_run_one_market", fake_one)
    result = asyncio.run(daily.run_daily(markets="cn,hk", report_dir="/tmp/nonexistent-report-dir"))
    assert order == ["cn", "hk"]
    assert set(result["markets"]) == {"cn", "hk"}


def test_run_daily_rejects_empty_markets():
    import pytest
    with pytest.raises(ValueError):
        asyncio.run(daily.run_daily(markets="", report_dir="/tmp/x"))


def test_render_daily_summary_contains_key_fields():
    result = {
        "date": "2026-09-09", "strategy": "swing_band", "rule_engine": "shadow",
        "outbox": "report/decision_outbox.sqlite3", "outbox_run_id": "abc123",
        "markets": {
            "cn": {"market": "cn", "report": {}, "file": "report/recommend-cn-20260909-daily.md",
                   "snapshot": "report/snapshots/cn-20260909.json",
                   "records": [{"code": "600000"}],
                   "top10": [{"name": "测试", "code": "600000", "verdict": "ALLOW"}]},
            "hk": {"market": "hk", "error": "RuntimeError: 数据源限流",
                   "report": {}, "file": "", "snapshot": "", "records": [], "top10": []},
        },
    }
    text = daily.render_daily_summary(result)
    assert "2026-09-09" in text and "swing_band" in text and "shadow" in text
    assert "A股" in text and "600000" in text and "ALLOW" in text
    assert "港股" in text and "数据源限流" in text
    assert "abc123" in text and "swing_backtest.jsonl" in text
    assert "不构成投资建议" in text


def test_trendgate_signal_error_without_cache():
    """trendgate_signal 无缓存时返回 error 字典（不抛异常、不联网）。"""
    import asyncio
    from scripts.quantrisk.daily import trendgate_signal

    async def run():
        # 用一个不存在的 days 强制缓存 miss（cn_d99999）
        sig = await trendgate_signal("cn", gate_ma=30, days=99999)
        assert sig.get("error"), sig
        assert "缓存" in sig["error"] or "cache" in sig["error"].lower(), sig

    asyncio.run(run())


def test_render_strategy_signals_ok():
    """render_strategy_signals 对合法信号渲染出闸门/TOP10 章节。"""
    from scripts.quantrisk.daily import render_strategy_signals
    sig = {
        "market": "hk", "label": "港股", "as_of": "2026-10-13", "gate_ma": 30,
        "universe_count": 93,
        "gate": {"symbol": "hkHSI", "close": 24074.72, "ma": 24723.54,
                 "on": False, "confirm_days": 0},
        "stance": "🔴 空仓等待（闸门关闭）",
        "top10": [{"code": "00316", "name": "東方海外國際", "score": 0.946}],
    }
    md = render_strategy_signals([sig])
    assert "hkHSI" in md and "TOP10" in md and "東方海外國際" in md
    err = render_strategy_signals([{"market": "cn", "label": "A股", "error": "boom"}])
    assert "boom" in err

import asyncio

from scripts.quantrisk import data


def test_hk_fundamentals_eastmoney_fallback_to_tencent(monkeypatch):
    """东财失败时不静默，继续腾讯78字段 fallback。"""
    async def fake_em(secucode, page_size=4):
        raise RuntimeError("rate limited")

    async def fake_tencent(symbol):
        return {"pe": 12.3, "pe_ttm": 11.0, "pb": 1.5, "roe": 15.0,
                "gross_margin": 40.0, "profit_margin": 20.0, "revenue_growth": 5.0,
                "debt_ratio": 30.0, "dividend_yield": 2.0, "market_cap_100m": 1000.0}

    monkeypatch.setattr(data, "key_indicators_eastmoney_async", fake_em)
    monkeypatch.setattr(data, "hk_stock_quote_tencent_async", fake_tencent)
    r = asyncio.run(data.hk_fundamentals_async("00700"))
    assert r["source"] == "tencent"
    assert r["latest"]["PE"] == 12.3


def test_hk_fundamentals_all_fail_explicit_error(capsys, monkeypatch):
    """全部数据源失败时显式报错 + WARN 日志，不静默。"""
    async def fake_em(secucode, page_size=4):
        raise RuntimeError("rate limited")

    async def fake_tencent(symbol):
        return {}

    async def fake_stats(secucode):
        raise RuntimeError("401")

    async def fake_fin(secucode):
        raise RuntimeError("403")

    monkeypatch.setattr(data, "key_indicators_eastmoney_async", fake_em)
    monkeypatch.setattr(data, "hk_stock_quote_tencent_async", fake_tencent)
    monkeypatch.setattr(data, "key_statistics_async", fake_stats)
    monkeypatch.setattr(data, "financial_statements_yahoo_async", fake_fin)
    r = asyncio.run(data.hk_fundamentals_async("00700"))
    assert r["source"] is None
    assert r["error"] == "所有数据源均失败"
    out = capsys.readouterr().out
    assert "港股基本面 东财失败" in out
    assert "港股基本面 Yahoo三表失败" in out


def test_cn_key_indicators_f10_failure_not_fatal(capsys, monkeypatch):
    """A股 F10 主要指标补充失败不阻断主结果，且打 WARN。"""
    async def fake_em(report_name, filter_str="", page_size=4, sort_columns="", sort_types="-1"):
        if report_name == "RPT_LICO_FN_CPD":
            return [{"SECUCODE": "600519.SH", "REPORTDATE": "2026-06-30",
                     "EPSJB": 20.0, "BPS": 100.0}]
        raise RuntimeError("F10 mainfinadata 限流")

    monkeypatch.setattr(data, "eastmoney_datacenter", fake_em)
    r = asyncio.run(data.cn_key_indicators_async("600519"))
    assert len(r) == 1
    out = capsys.readouterr().out
    assert "F10主要指标补充失败" in out

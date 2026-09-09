import asyncio

from scripts.quantrisk import swing


def bars(count=90):
    return [
        {"date": f"2026-01-{(i % 28) + 1:02d}", "open": 10 + i * 0.1,
         "high": 10.2 + i * 0.1, "low": 9.8 + i * 0.1,
         "close": 10 + i * 0.1, "volume": 1000 + i * 10}
        for i in range(count)
    ]


def test_pipeline_requests_intraday_for_band(monkeypatch):
    """单策略 swing_band：统一尝试拉取30m（入场优化），30m缺失由规则层不阻断。"""
    stocks = [{"c": "600000", "n": "测试", "s": "其他", "p": 19.0,
               "market": "cn", "strategy_id": "band", "index_sync": {"sync": True, "quality": "VALUE"}}]
    called = {"intraday": 0}

    async def daily_fetch(code):
        return bars()

    async def flow_fetch(code):
        return {"flow_5d": 1e8, "days": 5}

    async def intraday_fetch(code):
        called["intraday"] += 1
        return {"available": True, "bars": bars(45)}

    async def skip_profiles(report, market):
        return report

    async def skip_receipts(report, stocks):
        return report

    monkeypatch.setattr(swing, "attach_company_profiles", skip_profiles)
    monkeypatch.setattr(swing, "_attach_decision_receipts", skip_receipts)
    report = asyncio.run(swing.run_swing_pipeline_with_intraday(stocks, "cn", daily_fetch, flow_fetch, intraday_fetch))
    assert called["intraday"] == 1
    assert report["details"][0]["strategy_id"] == "swing_band"


def test_pipeline_tolerates_missing_intraday(monkeypatch):
    """30m 缺失不阻断：band 策略仍可输出结果，规则层按非硬门槛处理。"""
    stocks = [{"c": "600000", "n": "测试", "s": "其他", "p": 19.0,
               "market": "cn", "strategy_id": "band", "index_sync": {"sync": True, "quality": "VALUE"}}]

    async def daily_fetch(code):
        return bars()

    async def flow_fetch(code):
        return {"flow_5d": 1e8, "days": 5}

    async def intraday_fetch(code):
        return {"available": False, "bars": []}

    async def skip_profiles(report, market):
        return report

    async def skip_receipts(report, stocks):
        return report

    monkeypatch.setattr(swing, "attach_company_profiles", skip_profiles)
    monkeypatch.setattr(swing, "_attach_decision_receipts", skip_receipts)
    report = asyncio.run(swing.run_swing_pipeline_with_intraday(stocks, "cn", daily_fetch, flow_fetch, intraday_fetch))
    assert report["details"][0]["segment"]["available"] is False
    assert report["details"][0]["verdict"] == "ALLOW" or report["details"][0]["verdict"] == "WATCH"

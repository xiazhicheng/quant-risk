import asyncio

from scripts.quantrisk import data, swing


def test_company_survey_cn(monkeypatch):
    async def fake_get_json(url, **kw):
        return {"jbzl": {"sshy": "旅游酒店", "gsjj": "黄山旅游股份公司主营景区、索道与酒店运营。",
                         "frdb": "章德辉", "zjl": "孙峻", "gswz": "www.hstd.com", "zczb": "7.3亿元"}}

    monkeypatch.setattr(data, "_get_json", fake_get_json)
    p = asyncio.run(data.company_survey_async("600054", "cn"))
    assert p["industry"] == "旅游酒店"
    assert "索道" in p["brief"]
    assert p["chairman"] == "章德辉"
    assert p["gm"] == "孙峻"
    assert p["website"] == "www.hstd.com"


def test_company_survey_cn_empty(monkeypatch):
    async def fake_get_json(url, **kw):
        return {}

    monkeypatch.setattr(data, "_get_json", fake_get_json)
    p = asyncio.run(data.company_survey_async("600054", "cn"))
    assert "error" in p


def test_company_survey_hk(monkeypatch):
    async def fake_quote(code):
        return {"name": "金山软件", "pe_ttm": 10.5, "roe": 10.3,
                "debt_ratio": -11.88, "dividend_yield": -0.14, "market_cap_100m": 120}

    monkeypatch.setattr(data, "hk_stock_quote_tencent_async", fake_quote)

    async def fake_industry(code):
        return "软件服务"

    monkeypatch.setattr(data, "hk_industry_async", fake_industry)
    p = asyncio.run(data.company_survey_async("03888", "hk"))
    assert p["pe_ttm"] == 10.5
    assert p["roe"] == 10.3
    assert p["industry"] == "软件服务"


def test_attach_company_profiles(monkeypatch):
    async def fake_survey(code, market):
        return {"industry": "测试行业", "brief": "主营测试", "chairman": "张三", "gm": "李四"}

    async def fake_empty(*args, **kwargs):
        return {}

    async def fake_ann(*args, **kwargs):
        return []

    for fn in ("business_mix_async", "finance_brief_async", "core_conception_async"):
        monkeypatch.setattr(data, fn, fake_empty)
    monkeypatch.setattr(data, "recent_announcements_async", fake_ann)
    monkeypatch.setattr(data, "company_survey_async", fake_survey)
    report = {"details": [{"code": f"6000{i}", "name": f"标的{i}"} for i in range(3)]}
    out = asyncio.run(swing.attach_company_profiles(report, "cn"))
    assert all(d.get("profile", {}).get("industry") == "测试行业" for d in out["details"])
    assert all("profile_extra" in d for d in out["details"])


def test_attach_company_profiles_error_safe(monkeypatch):
    async def fake_survey(code, market):
        raise RuntimeError("F10挂了")

    async def fake_empty(*args, **kwargs):
        return {}

    async def fake_ann(*args, **kwargs):
        return []

    for fn in ("business_mix_async", "finance_brief_async", "core_conception_async"):
        monkeypatch.setattr(data, fn, fake_empty)
    monkeypatch.setattr(data, "recent_announcements_async", fake_ann)
    monkeypatch.setattr(data, "company_survey_async", fake_survey)
    report = {"details": [{"code": "600054", "name": "黄山旅游"}]}
    out = asyncio.run(swing.attach_company_profiles(report, "cn"))
    assert "error" in out["details"][0]["profile"]


def test_business_mix_cn(monkeypatch):
    async def fake(url, **kw):
        return {"zygcfx": [{"REPORT_DATE": "2026-06-30 00:00:00", "ITEM_NAME": "纺织贸易", "MBI_RATIO": 0.821,
                            "GROSS_RPOFIT_RATIO": 0.0186, "RANK": 1},
                           {"REPORT_DATE": "2026-06-30 00:00:00", "ITEM_NAME": "服装", "MBI_RATIO": 0.12,
                            "GROSS_RPOFIT_RATIO": 0.2, "RANK": 2}]}

    monkeypatch.setattr(data, "_get_json", fake)
    mix = asyncio.run(data.business_mix_async("600156", "cn"))
    assert mix[0]["item"] == "纺织贸易"
    assert mix[0]["ratio"] == 82.1


def test_finance_brief_cn(monkeypatch):
    async def fake(url, **kw):
        return {"result": {"data": [{"REPORT_DATE": "2026-06-30 00:00:00", "TOTALOPERATEREVE": 321701160.97,
                                     "TOTALOPERATEREVETZ": -25.7, "PARENTNETPROFIT": -24000185.25,
                                     "PARENTNETPROFITTZ": -77.1, "EPSJB": -0.06, "ROEJQ": -6.65,
                                     "XSMLL": 3.76, "XSJLL": -8.32, "ZCFZL": 57.12}]}}

    monkeypatch.setattr(data, "_get_json", fake)
    f = asyncio.run(data.finance_brief_async("600156", "cn"))
    assert f["revenue"] == 3.22
    assert f["profit_yoy"] == -77.1


def test_core_conception_cn(monkeypatch):
    async def fake(url, **kw):
        return {"ssbk": [{"BOARD_NAME": "并购重组概念"}, {"BOARD_NAME": "液冷服务器"}],
                "hxtc": [{"KEYWORD": "并购重组", "MAINPOINT_CONTENT": "拟收购易信科技100%股权，转型算力"}]}

    monkeypatch.setattr(data, "_get_json", fake)
    c = asyncio.run(data.core_conception_async("600156", "cn"))
    assert "并购重组概念" in c["boards"]
    assert c["themes"][0]["keyword"] == "并购重组"


def test_render_profile_tabs_cn():
    r = {"profile": {"industry": "化工行业", "brief": "万华化学是全球化工新材料龙头。" * 5, "chairman": "廖增太", "gm": "寇光武"},
         "profile_extra": {"business_mix": [{"item": "聚氨酯", "ratio": 55.0, "gross_margin": 22.0}],
                           "finance": {"report_date": "2026-06-30", "revenue": 500.0, "revenue_yoy": 10.0, "profit": 80.0,
                                       "profit_yoy": 5.0, "roe": 15.0, "gross_margin": 20.0, "net_margin": 12.0,
                                       "debt_ratio": 50.0},
                           "conception": {"boards": ["化工龙头", "新材料"], "themes": [{"keyword": "MDI", "content": "全球MDI龙头"}]}},
         "announcements": []}
    line = swing._render_profile_line(r, "cn")
    assert "📋" in line and "主营构成" in line and "聚氨酯" in line
    assert "📊" in line and "营收500.0亿" in line and "ROE 15.0%" in line
    assert "🎯" in line and "MDI" in line


def test_render_profile_tabs_hk():
    r = {"profile": {"pe_ttm": 14.51, "roe": 4.18, "dividend_yield": 0.15, "debt_ratio": 17.16},
         "profile_extra": {}, "announcements": []}
    line = swing._render_profile_line(r, "hk")
    assert "📊" in line and "PE(TTM) 14.51" in line
    assert "近期动态：数据缺失" in line


def test_render_profile_line_cn():
    r = {"profile": {"industry": "化工行业", "brief": "万华化学是全球化工新材料龙头，依托不断创新的核心技术。" * 6,
                     "chairman": "廖增太", "gm": "寇光武"},
         "profile_extra": {}, "announcements": []}
    line = swing._render_profile_line(r, "cn")
    assert "📋" in line and "化工行业" in line and "法人：廖增太" in line and "…" in line


def test_render_profile_line_hk_financial():
    r = {"profile": {"pe_ttm": 10.5, "roe": 10.3, "dividend_yield": 5.2, "debt_ratio": 45.0}}
    line = swing._render_profile_line(r, "hk")
    assert "PE(TTM) 10.5" in line and "ROE 10.3%" in line and "股息率 5.2%" in line


def test_render_profile_line_hk_missing_negatives():
    """腾讯字段负值/缺失视为无数据，标注数据缺失而非显示负数。"""
    r = {"profile": {"pe_ttm": 0, "roe": None, "dividend_yield": -0.14, "debt_ratio": -11.88}}
    line = swing._render_profile_line(r, "hk")
    assert "数据缺失" in line


def test_render_profile_line_error():
    r = {"profile": {"error": "F10资料为空"}}
    assert "数据缺失" in swing._render_profile_line(r, "cn")


def test_cn_announcements_filter(monkeypatch):
    """重组/收购类公告优先于常规公告。"""
    async def fake_get_json(url, **kw):
        return {"data": {"list": [
            {"notice_date": "2026-09-01 00:00:00", "title": "华升股份:关于召开业绩说明会的公告"},
            {"notice_date": "2026-07-21 00:00:00", "title": "华升股份:关于收购易信科技100%股权的进展公告"},
            {"notice_date": "2026-08-28 00:00:00", "title": "华升股份:2026年半年度报告"},
        ]}}

    monkeypatch.setattr(data, "_get_json", fake_get_json)
    ann = asyncio.run(data.cn_announcements_async("600156"))
    assert len(ann) >= 1
    assert "收购易信科技" in ann[0]["title"]


def test_hk_announcements_filter(monkeypatch):
    """港股公告：腾讯 noticeList 接口，重大事项（回购/重组等）优先。"""
    async def fake_get_json(url, **kw):
        return {"code": 0, "data": {"data": [
            {"title": "翌日披露报表 - 回购股份", "time": "2026-09-07 18:00:45"},
            {"title": "委任执行董事", "time": "2026-09-01 09:00:00"},
            {"title": "年度业绩公告", "time": "2026-08-30 12:00:00"},
        ]}}

    monkeypatch.setattr(data, "_get_json", fake_get_json)
    ann = asyncio.run(data.hk_announcements_async("00386"))
    assert ann and "回购" in ann[0]["title"]
    assert ann[0]["date"] == "2026-09-07"


def test_hk_industry_async(monkeypatch):
    """港股行业：东财 push2 secid=116 f127 字段。"""
    async def fake(url, **kw):
        return {"data": {"f127": "软件服务"}}

    monkeypatch.setattr(data, "_get_json", fake)
    assert asyncio.run(data.hk_industry_async("00700")) == "软件服务"


def test_hk_plate_async(monkeypatch):
    """港股所属板块：腾讯自选股 plate 接口。"""
    async def fake(url, **kw):
        return {"data": {"name": "数码解决方案服务"}}

    monkeypatch.setattr(data, "_get_json", fake)
    assert asyncio.run(data.hk_plate_async("00700")) == "数码解决方案服务"


def test_hk_plate_async_error_safe(monkeypatch):
    async def fake(url, **kw):
        raise RuntimeError("接口失败")

    monkeypatch.setattr(data, "_get_json", fake)
    assert asyncio.run(data.hk_plate_async("00700")) == ""


def test_render_announcements_line():
    r = {"profile": {"industry": "化工行业", "brief": "主营测试", "chairman": "张三", "gm": "李四"},
         "announcements": [{"date": "2026-07-21", "title": "关于收购易信科技100%股权的进展公告"}]}
    line = swing._render_profile_line(r, "cn")
    assert "📌 近期动态" in line and "收购易信科技" in line


def test_render_announcements_hk_missing():
    r = {"profile": {"pe_ttm": 10.5}, "announcements": []}
    line = swing._render_profile_line(r, "hk")
    assert "近期动态：数据缺失" in line


def test_render_swing_report_score_legend():
    """报告头部必须带评分维度说明，否则用户看不懂分数来源。"""
    report = {"date": "2026-09-08", "market": "cn", "selection_mode": "swing",
              "top10": [], "details": [], "summary": [], "sectors": []}
    text = swing.render_swing_report(report, "cn")
    assert "评分说明" in text and "日线趋势30分" in text and "30分钟道氏25分" in text


def test_render_profile_line_hk_plate_announcement():
    """港股看点（腾讯板块）与近期动态（腾讯公告）免费源接入后的渲染。"""
    r = {"profile": {"pe_ttm": 14.51, "roe": 4.18, "industry": "软件服务"},
         "profile_extra": {"conception": {"boards": ["数码解决方案服务"], "themes": []}},
         "announcements": [{"date": "2026-09-07", "title": "翌日披露报表 - 回购股份"}]}
    line = swing._render_profile_line(r, "hk")
    assert "行业：软件服务" in line
    assert "数码解决方案服务" in line
    assert "回购股份" in line and "近期动态" in line

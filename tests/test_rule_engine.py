import importlib.util

from scripts.quantrisk.rule_engine import (
    PythonReferenceRuleEngine,
    SemanticaReteRuleEngine,
    ShadowRuleEngine,
)
from scripts.quantrisk.strategy_models import DataQuality, FeatureSnapshot, Verdict
import pytest


def features(**overrides):
    values = {
        "market": "cn",
        "code": "600000",
        "strategy_id": "swing_tactical_1w2w",
        "as_of": "2026-09-09T15:00:00+08:00",
        "rank_score": 80.0,
        "data_quality": DataQuality.VALUE,
        "suspended_or_delisted": False,
        "daily_direction": "up",
        "intraday_direction": "up",
        "intraday_available": True,
        "intraday_confirmation_required": False,
        "direction_conflict": False,
        "momentum_weak": False,
        "overall_down": False,
        "low_volume": False,
        "overheated": False,
        "stage": "公众参与",
        "health_ok": True,
        "index_sync": True,
        "close_below_previous_low": False,
        "trail_stop_hit": False,
        "previous_low": 10.0,
        "previous_high": 12.0,
        "current_close": 11.5,
    }
    values.update(overrides)
    return FeatureSnapshot(**values)


def test_reference_allows_complete_uptrend():
    result = PythonReferenceRuleEngine().evaluate(features())
    assert result.verdict == Verdict.ALLOW
    assert result.entry_eligible is True
    assert result.rule_hits[0].rule_id == "ALLOW_ALL_HARD_RULES_PASS"


def test_reference_missing_data_blocks():
    result = PythonReferenceRuleEngine().evaluate(features(data_quality=DataQuality.MISSING))
    assert result.verdict == Verdict.BLOCK
    assert result.entry_eligible is False
    assert result.rule_hits[0].rule_id == "DATA_GAP_BLOCK_ENTRY"


def test_reference_exit_beats_watch():
    result = PythonReferenceRuleEngine().evaluate(features(
        close_below_previous_low=True,
        momentum_weak=True,
        index_sync=False,
    ))
    assert result.verdict == Verdict.EXIT
    assert result.rule_hits[0].rule_id == "CLOSE_BELOW_PREVIOUS_LOW_EXIT"


def test_semantica_rete_matches_reference():
    pytest.importorskip("semantica")  # decision extra 未装时跳过，保证默认环境全量测试可过
    semantica = SemanticaReteRuleEngine()
    reference = PythonReferenceRuleEngine()
    cases = [
        features(),
        features(data_quality=DataQuality.MISSING),
        features(momentum_weak=True),
        features(close_below_previous_low=True, low_volume=True),
        features(direction_conflict=True),
    ]
    for case in cases:
        assert semantica.evaluate(case).verdict == reference.evaluate(case).verdict


@pytest.mark.skipif(importlib.util.find_spec("semantica") is None,
                    reason="Semantica 未安装（可选依赖），影子比对降级为纯 Python，降级路径见 test_shadow_degrades_without_semantica")
def test_shadow_reference_remains_authoritative():
    result = ShadowRuleEngine().evaluate(features(index_sync=False))
    assert result.verdict == Verdict.WATCH
    assert result.entry_eligible is False
    assert result.shadow_match is True


def test_shadow_degrades_without_semantica(monkeypatch):
    """未安装 Semantica（可选依赖）时 ShadowRuleEngine 降级为纯 Python 参考引擎，功能完整。"""
    import sys
    # 模拟未安装：先清空 semantica 全部模块缓存（子模块缓存会绕过顶层拦截），再置 None 阻止重新导入
    for name in [n for n in list(sys.modules) if n == "semantica" or n.startswith("semantica.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "semantica", None)
    engine = ShadowRuleEngine()
    assert engine.semantica is None
    result = engine.evaluate(features())
    assert result.engine == "python"
    assert result.shadow_match is None
    assert result.shadow_verdict == "UNAVAILABLE"
    assert result.verdict == Verdict.ALLOW
    assert result.entry_eligible is True


def test_intraday_missing_does_not_block_when_optional():
    """30m 为入场优化：缺失不 BLOCK（单策略 swing_band 语义）。"""
    result = PythonReferenceRuleEngine().evaluate(features(intraday_available=False, intraday_direction=""))
    assert result.verdict == Verdict.ALLOW


def test_intraday_conflict_still_watches():
    """30m 与日线方向冲突仍观望（道氏双周期纪律保留）。"""
    result = PythonReferenceRuleEngine().evaluate(features(direction_conflict=True))
    assert result.verdict == Verdict.WATCH

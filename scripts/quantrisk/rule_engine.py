"""Deterministic rule engines for swing decisions.

The reference engine is the semantic contract.  The optional Semantica RETE
adapter consumes the same facts and is never allowed to weaken a hard block.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol

from .strategy_models import (
    DataQuality,
    DecisionResult,
    FeatureSnapshot,
    RuleHit,
    Verdict,
    VERDICT_PRECEDENCE,
)


RULE_PRIORITY = {
    "DATA_GAP_BLOCK_ENTRY": 1000,
    "STALE_DATA_BLOCK_ENTRY": 990,
    "SUSPENDED_OR_DELISTED_BLOCK": 980,
    "CLOSE_BELOW_PREVIOUS_LOW_EXIT": 900,
    "TRAIL_STOP_EXIT": 890,
    "DAILY_INTRADAY_CONFLICT_WATCH": 800,
    "DIRECTION_NOT_UP_WATCH": 790,
    "OVERALL_TREND_DOWN_WATCH": 780,
    "MOMENTUM_WEAK_WATCH": 700,
    "LOW_VOLUME_WATCH": 690,
    "OVERHEATED_WATCH": 680,
    "DISTRIBUTION_STAGE_WATCH": 670,
    "HEALTH_WARNING_WATCH": 660,
    "INDEX_DIVERGENCE_WATCH": 650,
}


class RuleEngine(Protocol):
    def evaluate(self, features: FeatureSnapshot) -> DecisionResult:
        ...


def _hit(rule_id: str, verdict: Verdict, reason: str, engine: str = "python") -> RuleHit:
    return RuleHit(rule_id, verdict, RULE_PRIORITY.get(rule_id, 0), reason, engine)


def _resolve(hits: list[RuleHit], engine: str, error: str = "") -> DecisionResult:
    ordered = tuple(sorted(hits, key=lambda h: (-VERDICT_PRECEDENCE[h.verdict], -h.priority, h.rule_id)))
    verdict = ordered[0].verdict if ordered else Verdict.WATCH
    return DecisionResult(
        verdict=verdict,
        entry_eligible=verdict == Verdict.ALLOW,
        rule_hits=ordered,
        engine=engine,
        error=error,
    )


class PythonReferenceRuleEngine:
    """Pure Python reference semantics used for replay, rollback, and tests."""

    def evaluate(self, features: FeatureSnapshot) -> DecisionResult:
        hits: list[RuleHit] = []
        if features.data_quality in {DataQuality.MISSING, DataQuality.STALE}:
            rule = "STALE_DATA_BLOCK_ENTRY" if features.data_quality == DataQuality.STALE else "DATA_GAP_BLOCK_ENTRY"
            hits.append(_hit(rule, Verdict.BLOCK, f"关键行情数据质量={features.data_quality.value}，禁止新开仓"))
        if features.suspended_or_delisted:
            hits.append(_hit("SUSPENDED_OR_DELISTED_BLOCK", Verdict.BLOCK, "停牌或退市残留，不允许交易"))
        if features.close_below_previous_low:
            hits.append(_hit("CLOSE_BELOW_PREVIOUS_LOW_EXIT", Verdict.EXIT, "收盘价跌破道氏前低，趋势结束，离场"))
        if features.trail_stop_hit:
            hits.append(_hit("TRAIL_STOP_EXIT", Verdict.EXIT, "收盘价触发自入场峰值移动止盈，离场"))
        if features.direction_conflict:
            hits.append(_hit("DAILY_INTRADAY_CONFLICT_WATCH", Verdict.WATCH, "日线与30分钟方向冲突"))
        if features.intraday_confirmation_required and not features.intraday_available:
            hits.append(_hit("DATA_GAP_BLOCK_ENTRY", Verdict.BLOCK, "策略要求已确认30分钟数据但缺失，禁止新开仓"))
        if features.daily_direction != "up" or (features.intraday_confirmation_required and features.intraday_direction != "up"):
            hits.append(_hit("DIRECTION_NOT_UP_WATCH", Verdict.WATCH, "趋势方向未满足只做多条件"))
        if features.overall_down:
            hits.append(_hit("OVERALL_TREND_DOWN_WATCH", Verdict.WATCH, "整体趋势偏空"))
        if features.momentum_weak:
            hits.append(_hit("MOMENTUM_WEAK_WATCH", Verdict.WATCH, "动能走弱预警，等待回踩确认"))
        if features.low_volume:
            hits.append(_hit("LOW_VOLUME_WATCH", Verdict.WATCH, "量比低于1，缩量上涨"))
        if features.overheated:
            hits.append(_hit("OVERHEATED_WATCH", Verdict.WATCH, "短期涨幅过大，禁止追高"))
        if features.stage == "派发":
            hits.append(_hit("DISTRIBUTION_STAGE_WATCH", Verdict.WATCH, "缩量新高，疑似派发阶段"))
        if not features.health_ok:
            hits.append(_hit("HEALTH_WARNING_WATCH", Verdict.WATCH, "成交量未确认趋势健康"))
        if features.index_sync is False:
            hits.append(_hit("INDEX_DIVERGENCE_WATCH", Verdict.WATCH, "主要指数方向背离"))
        if not hits:
            hits.append(_hit("ALLOW_ALL_HARD_RULES_PASS", Verdict.ALLOW, "硬规则全部通过"))
        return _resolve(hits, "python")


class SemanticaReteRuleEngine:
    """Optional Semantica RETE adapter over the same deterministic facts."""

    def __init__(self) -> None:
        try:
            from semantica.reasoning import Fact, Rule, ReteEngine
        except Exception as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(f"Semantica RETE unavailable: {exc}") from exc
        self._Fact = Fact
        self._Rule = Rule
        self._ReteEngine = ReteEngine

    def evaluate(self, features: FeatureSnapshot) -> DecisionResult:
        try:
            engine = self._ReteEngine()
            rules = self._rules()
            engine.build_network(rules)
            facts = [self._Fact(f"fact_{i}", "flag", [flag]) for i, flag in enumerate(_flags(features))]
            matches = engine.match_patterns(facts)
            hits = []
            for match in matches:
                metadata = match.rule.metadata or {}
                hits.append(_hit(metadata["rule_id"], Verdict(metadata["verdict"]), metadata["reason"], "semantica"))
            if not hits:
                hits.append(_hit("ALLOW_ALL_HARD_RULES_PASS", Verdict.ALLOW, "RETE规则全部通过", "semantica"))
            return _resolve(hits, "semantica")
        except Exception as exc:
            return DecisionResult(
                verdict=Verdict.BLOCK,
                entry_eligible=False,
                rule_hits=(_hit("SEMANTICA_ENGINE_ERROR_BLOCK", Verdict.BLOCK, f"Semantica规则执行失败: {exc}", "semantica"),),
                engine="semantica",
                error=str(exc),
            )

    def _rules(self) -> list[Any]:
        rules = []
        for rule_id, verdict, flag, reason in _RETE_RULES:
            rules.append(self._Rule(
                rule_id=rule_id,
                name=rule_id,
                conditions=[f"flag({flag})"],
                conclusion=f"decision({verdict})",
                priority=RULE_PRIORITY.get(rule_id, 0),
                metadata={"rule_id": rule_id, "verdict": verdict, "reason": reason},
            ))
        return rules


_RETE_RULES = (
    ("DATA_GAP_BLOCK_ENTRY", "BLOCK", "DATA_GAP", "关键行情数据缺失，禁止新开仓"),
    ("STALE_DATA_BLOCK_ENTRY", "BLOCK", "STALE_DATA", "关键行情数据过期，禁止新开仓"),
    ("SUSPENDED_OR_DELISTED_BLOCK", "BLOCK", "SUSPENDED", "停牌或退市残留，不允许交易"),
    ("CLOSE_BELOW_PREVIOUS_LOW_EXIT", "EXIT", "BREAK_PREVIOUS_LOW", "收盘价跌破道氏前低，趋势结束，离场"),
    ("TRAIL_STOP_EXIT", "EXIT", "TRAIL_STOP", "收盘价触发移动止盈，离场"),
    ("DAILY_INTRADAY_CONFLICT_WATCH", "WATCH", "DIRECTION_CONFLICT", "日线与30分钟方向冲突"),
    ("DIRECTION_NOT_UP_WATCH", "WATCH", "DIRECTION_NOT_UP", "趋势方向未满足只做多条件"),
    ("OVERALL_TREND_DOWN_WATCH", "WATCH", "OVERALL_DOWN", "整体趋势偏空"),
    ("MOMENTUM_WEAK_WATCH", "WATCH", "MOMENTUM_WEAK", "动能走弱预警，等待回踩确认"),
    ("LOW_VOLUME_WATCH", "WATCH", "LOW_VOLUME", "量比低于1，缩量上涨"),
    ("OVERHEATED_WATCH", "WATCH", "OVERHEATED", "短期涨幅过大，禁止追高"),
    ("DISTRIBUTION_STAGE_WATCH", "WATCH", "DISTRIBUTION", "缩量新高，疑似派发阶段"),
    ("HEALTH_WARNING_WATCH", "WATCH", "HEALTH_WARNING", "成交量未确认趋势健康"),
    ("INDEX_DIVERGENCE_WATCH", "WATCH", "INDEX_DIVERGENCE", "主要指数方向背离"),
)


def _flags(f: FeatureSnapshot) -> list[str]:
    flags = []
    if f.data_quality == DataQuality.MISSING:
        flags.append("DATA_GAP")
    if f.data_quality == DataQuality.STALE:
        flags.append("STALE_DATA")
    if f.suspended_or_delisted:
        flags.append("SUSPENDED")
    if f.close_below_previous_low:
        flags.append("BREAK_PREVIOUS_LOW")
    if f.trail_stop_hit:
        flags.append("TRAIL_STOP")
    if f.direction_conflict:
        flags.append("DIRECTION_CONFLICT")
    if f.intraday_confirmation_required and not f.intraday_available:
        flags.append("DATA_GAP")
    if f.daily_direction != "up" or (f.intraday_confirmation_required and f.intraday_direction != "up"):
        flags.append("DIRECTION_NOT_UP")
    if f.overall_down:
        flags.append("OVERALL_DOWN")
    if f.momentum_weak:
        flags.append("MOMENTUM_WEAK")
    if f.low_volume:
        flags.append("LOW_VOLUME")
    if f.overheated:
        flags.append("OVERHEATED")
    if f.stage == "派发":
        flags.append("DISTRIBUTION")
    if not f.health_ok:
        flags.append("HEALTH_WARNING")
    if f.index_sync is False:
        flags.append("INDEX_DIVERGENCE")
    return flags


class ShadowRuleEngine:
    """Run reference and Semantica together; reference remains authoritative."""

    def __init__(self, semantica: RuleEngine | None = None):
        self.reference = PythonReferenceRuleEngine()
        self.semantica = semantica
        if self.semantica is None:
            try:
                self.semantica = SemanticaReteRuleEngine()
            except Exception:
                self.semantica = None

    def evaluate(self, features: FeatureSnapshot) -> DecisionResult:
        reference = self.reference.evaluate(features)
        if self.semantica is None:
            return replace(reference, engine="python", shadow_match=None, shadow_verdict="UNAVAILABLE")
        shadow = self.semantica.evaluate(features)
        return replace(
            reference,
            shadow_match=reference.verdict == shadow.verdict,
            shadow_verdict=shadow.verdict.value,
            error=shadow.error,
        )


def features_from_swing_result(result: dict[str, Any], strategy_id: str = "swing_band") -> FeatureSnapshot:
    """Build immutable facts from the legacy swing result without changing scoring."""
    flow = result.get("flow") or {}
    stroke = result.get("stroke") or {}
    segment = result.get("segment") or {}
    error = str(result.get("error") or "")
    liquidity_ok = bool(result.get("liquidity_ok", True))
    quality = DataQuality.MISSING if not liquidity_ok or not flow else DataQuality.VALUE
    if flow.get("available") is False or flow.get("quality") == "MISSING":
        quality = DataQuality.MISSING
    elif flow.get("flow_5d") is not None or flow.get("quality") == "VALUE":
        quality = DataQuality.VALUE
    close = float(result.get("price") or 0)
    previous_low = float(stroke.get("previous_low") or stroke.get("low") or 0)
    return FeatureSnapshot(
        market=str(result.get("market") or ""),
        code=str(result.get("code") or ""),
        strategy_id=str(strategy_id),
        as_of=str(result.get("as_of") or ""),
        rank_score=float(result.get("total") or 0),
        data_quality=quality,
        suspended_or_delisted=bool("停牌" in error or "退市" in error),
        daily_direction=str(stroke.get("direction") or ""),
        intraday_direction=str(segment.get("direction") or ""),
        intraday_available=bool(segment.get("available")),
        intraday_confirmation_required=False,
        direction_conflict=bool(result.get("direction_conflict")),
        momentum_weak="动能走弱预警" in str(stroke.get("conclusion", "")) or "动能走弱预警" in str(segment.get("conclusion", "")),
        overall_down=stroke.get("trend_direction") == "down",
        low_volume=0 < float(flow.get("vol_ratio") or 0) < 1.0,
        overheated=float(flow.get("pct_5d") or 0) > 25.0,
        stage=str(result.get("stage") or ""),
        health_ok=bool((result.get("health") or {}).get("healthy", True)),
        index_sync=(result.get("index_sync") or {}).get("sync"),
        close_below_previous_low=close > 0 and previous_low > 0 and close < previous_low,
        trail_stop_hit=bool(result.get("trail_stop_hit", False)),
        previous_low=previous_low,
        previous_high=float(stroke.get("previous_high") or stroke.get("high") or 0),
        current_close=close,
        flow_quality=quality,
        risk_flags=tuple(result.get("risk_flags") or ()),
    )


__all__ = [
    "RULE_PRIORITY", "PythonReferenceRuleEngine", "SemanticaReteRuleEngine",
    "ShadowRuleEngine", "features_from_swing_result",
]

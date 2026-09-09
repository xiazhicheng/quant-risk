"""Build immutable facts from the legacy swing result."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from .rule_engine import features_from_swing_result
from .strategy_config import load_strategy_config
from .strategy_models import DataQuality, FeatureSnapshot, PositionState


def build_feature_snapshot(
    result: dict[str, Any],
    strategy_id: str = "swing_band",
    position: PositionState | None = None,
) -> FeatureSnapshot:
    """Convert technical output plus optional position state to frozen facts."""
    config = load_strategy_config(strategy_id)
    features = features_from_swing_result(result, config.strategy_id)
    data_quality = features.data_quality
    flow = result.get("flow") or {}
    index = result.get("index_sync") or {}
    if not flow or flow.get("quality") == "MISSING":
        data_quality = DataQuality.MISSING
    if index.get("quality") == "MISSING":
        data_quality = DataQuality.MISSING
    intraday_required = bool(config.get("intraday_confirmation_required", True))
    risk_flags = list(features.risk_flags)
    if data_quality != DataQuality.VALUE:
        risk_flags.append("DATA_QUALITY_" + data_quality.value)
    if not features.health_ok:
        risk_flags.append("HEALTH_WARNING")
    if index.get("sync") is False:
        risk_flags.append("INDEX_DIVERGENCE")
    peak = float((position.max_close_since_entry if position else 0.0) or 0.0)
    trail_pct = float(result.get("trail_pct") or 0.0)
    position_trail_stop = peak * (1 - trail_pct / 100) if peak > 0 and trail_pct > 0 else 0.0
    trail_hit = bool(position and position.is_open and position_trail_stop > 0 and
                     features.current_close <= position_trail_stop)
    return replace(
        features,
        data_quality=data_quality,
        intraday_confirmation_required=intraday_required,
        trail_stop_hit=trail_hit,
        risk_flags=tuple(sorted(set(risk_flags))),
        metadata={**features.metadata, "strategy_version": config.version,
                  "ruleset_hash": config.ruleset_hash,
                  "position_peak": peak, "position_trail_stop": round(position_trail_stop, 4)},
    )


__all__ = ["build_feature_snapshot"]

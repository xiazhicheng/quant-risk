"""Versioned swing strategy configuration loader.

Single band strategy (swing_band); old tactical/trend aliases normalize to it.
Holding time is not preset — it is determined by the Dow prior-low / trailing
stop exit signals (user decision 2026-09-09).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .strategy_models import StrategyId, content_hash


_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "strategies"
_FILE_BY_ID = {StrategyId.BAND.value: "swing_band.yaml"}

# 历史别名统一归一（tactical/trend 不再作为独立策略实体）
_ALIASES = {
    "band": StrategyId.BAND.value,
    "tactical": StrategyId.BAND.value,
    "1w2w": StrategyId.BAND.value,
    "swing_tactical_1w2w": StrategyId.BAND.value,
    "trend": StrategyId.BAND.value,
    "1m2m": StrategyId.BAND.value,
    "swing_trend_1m2m": StrategyId.BAND.value,
    StrategyId.BAND.value: StrategyId.BAND.value,
}


@dataclass(frozen=True)
class StrategyConfig:
    strategy_id: str
    version: str
    values: dict[str, Any]
    ruleset_hash: str

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


def normalize_strategy_id(value: str | StrategyId | None) -> str:
    if isinstance(value, StrategyId):
        return value.value
    raw = str(value or "band").lower()
    if raw not in _ALIASES:
        raise ValueError(f"未知策略: {value}（band，或历史别名 tactical|trend）")
    return _ALIASES[raw]


def load_strategy_config(value: str | StrategyId | None = None) -> StrategyConfig:
    strategy_id = normalize_strategy_id(value)
    path = _CONFIG_DIR / _FILE_BY_ID[strategy_id]
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("strategy_id") != strategy_id:
        raise ValueError(f"策略配置ID不一致: {path}")
    version = str(raw.get("version") or "")
    if not version:
        raise ValueError(f"策略配置缺少version: {path}")
    return StrategyConfig(strategy_id, version, raw, content_hash(raw))


__all__ = ["StrategyConfig", "load_strategy_config", "normalize_strategy_id"]

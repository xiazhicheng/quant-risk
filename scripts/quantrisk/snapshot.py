"""Canonical immutable snapshot storage for replay and audit."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .strategy_models import canonical_json, content_hash


def write_snapshot(payload: dict[str, Any], path: str | Path) -> dict[str, Any]:
    """Write canonical JSON atomically and return path/hash metadata."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = canonical_json(payload)
    digest = content_hash(payload)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(body + "\n", encoding="utf-8")
    tmp.replace(target)
    return {
        "path": str(target),
        "snapshot_hash": digest,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "bytes": len(body.encode("utf-8")),
    }


def read_snapshot(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("snapshot必须是JSON对象")
    return payload


__all__ = ["write_snapshot", "read_snapshot"]

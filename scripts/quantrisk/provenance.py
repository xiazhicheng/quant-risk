"""Decision receipts and a local SQLite outbox for auditable replay."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

from .strategy_models import (
    DecisionReceipt,
    FeatureSnapshot,
    RunMode,
    content_hash,
    utc_now_iso,
)


DEFAULT_OUTBOX = Path("report/decision_outbox.sqlite3")


def current_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


class DecisionOutbox:
    """Durable local queue; network/provenance writes stay off the market path."""

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_OUTBOX):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS decision_receipts (
                    receipt_hash TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    market TEXT NOT NULL,
                    code TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    provenance_id TEXT DEFAULT '',
                    uploaded INTEGER DEFAULT 0
                )
            """)

    def enqueue(self, receipt: DecisionReceipt) -> str:
        payload = receipt.to_dict()
        receipt_hash = receipt.receipt_hash
        with sqlite3.connect(self.path) as db:
            db.execute(
                """INSERT OR IGNORE INTO decision_receipts
                (receipt_hash,run_id,strategy_id,market,code,verdict,payload,created_at,provenance_id,uploaded)
                VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (receipt_hash, receipt.run_id, receipt.strategy_id, receipt.market,
                 receipt.code, receipt.decision.verdict.value,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True),
                 utc_now_iso(), receipt.provenance_id),
            )
        return receipt_hash

    def pending(self, limit: int = 100) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT * FROM decision_receipts WHERE uploaded=0 ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_uploaded(self, receipt_hash: str, provenance_id: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE decision_receipts SET uploaded=1, provenance_id=? WHERE receipt_hash=?",
                (provenance_id, receipt_hash),
            )


def build_receipt(
    run_id: str,
    features: FeatureSnapshot,
    decision,
    strategy_version: str,
    ruleset_hash: str,
    run_mode: RunMode = RunMode.RESEARCH,
    signal_time: str | None = None,
    earliest_execution_time: str | None = None,
    snapshot_hash: str = "",
) -> DecisionReceipt:
    return DecisionReceipt(
        run_id=run_id,
        strategy_id=features.strategy_id,
        strategy_version=strategy_version,
        run_mode=run_mode,
        signal_time=signal_time or features.as_of or utc_now_iso(),
        earliest_execution_time=earliest_execution_time or features.as_of or utc_now_iso(),
        market=features.market,
        code=features.code,
        snapshot_hash=snapshot_hash or features.facts_hash,
        facts_hash=features.facts_hash,
        ruleset_hash=ruleset_hash,
        code_commit=current_git_commit(),
        decision=decision,
        semantica_version="0.6.8" if decision.engine == "semantica" else "",
        audit_complete=bool(decision.engine and decision.error == ""),
    )


__all__ = ["DecisionOutbox", "build_receipt", "current_git_commit"]

"""
Agent decision memory store.

Records every decision (captain, transfer, chip) with the context it was made in
and the actual outcome. Used for:
  - Retrieval-augmented decisions (inject similar past decisions into the prompt)
  - Reflection agent (analyze patterns of wins/losses, update strategy rules)

Storage: SQLite (no external infra needed). For production scale, swap for
Postgres — the interface stays the same.
"""
from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_DB_PATH = "data/agent_memory/decisions.db"


@dataclass
class Decision:
    """A single agent decision with context and (eventually) outcome."""
    entry_id: int
    gw: int
    agent_type: str                          # "captain" | "transfer" | "chip"
    decision: dict                           # what the agent recommended
    context: dict                            # squad / market state at decision time
    actual_outcome: Optional[dict] = None    # filled in after the GW completes
    outcome_delta: Optional[float] = None    # gain/loss vs baseline (positive = good)
    notes: Optional[str] = None              # free-form reflection notes
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class MemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        with self._conn() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id INTEGER NOT NULL,
                    gw INTEGER NOT NULL,
                    agent_type TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    actual_outcome_json TEXT,
                    outcome_delta REAL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_decisions_entry_gw ON decisions(entry_id, gw)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(agent_type)")
            c.execute("""
                CREATE TABLE IF NOT EXISTS strategy_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_text TEXT NOT NULL,
                    evidence_gws TEXT,
                    created_at TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                )
            """)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---- writes ----

    def add_decision(self, d: Decision) -> int:
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO decisions
                   (entry_id, gw, agent_type, decision_json, context_json,
                    actual_outcome_json, outcome_delta, notes, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (d.entry_id, d.gw, d.agent_type,
                 json.dumps(d.decision), json.dumps(d.context),
                 json.dumps(d.actual_outcome) if d.actual_outcome else None,
                 d.outcome_delta, d.notes, d.created_at),
            )
            return int(cur.lastrowid)

    def update_outcome(self, decision_id: int, outcome: dict, delta: float, notes: str = None):
        with self._conn() as c:
            c.execute(
                """UPDATE decisions SET actual_outcome_json = ?, outcome_delta = ?, notes = ?
                   WHERE id = ?""",
                (json.dumps(outcome), float(delta), notes, decision_id),
            )

    def add_strategy_rule(self, rule_text: str, evidence_gws: list[int]):
        with self._conn() as c:
            c.execute(
                """INSERT INTO strategy_rules (rule_text, evidence_gws, created_at)
                   VALUES (?, ?, ?)""",
                (rule_text, json.dumps(evidence_gws),
                 datetime.now(timezone.utc).isoformat()),
            )

    # ---- reads ----

    def get_decisions_for(self, entry_id: int, agent_type: Optional[str] = None,
                           gw_max: Optional[int] = None, limit: int = 200) -> list[Decision]:
        """Return decisions for an entry, optionally filtered by type and capped at gw <= gw_max."""
        sql = "SELECT * FROM decisions WHERE entry_id = ?"
        args: list = [int(entry_id)]
        if agent_type:
            sql += " AND agent_type = ?"
            args.append(agent_type)
        if gw_max is not None:
            sql += " AND gw <= ?"
            args.append(int(gw_max))
        sql += " ORDER BY gw DESC LIMIT ?"
        args.append(int(limit))

        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [self._row_to_decision(r) for r in rows]

    def get_active_rules(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM strategy_rules WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict:
        with self._conn() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
            with_outcome = c.execute(
                "SELECT COUNT(*) AS n FROM decisions WHERE outcome_delta IS NOT NULL"
            ).fetchone()["n"]
            avg_delta = c.execute(
                "SELECT AVG(outcome_delta) AS d FROM decisions WHERE outcome_delta IS NOT NULL"
            ).fetchone()["d"]
            n_rules = c.execute(
                "SELECT COUNT(*) AS n FROM strategy_rules WHERE active = 1"
            ).fetchone()["n"]
        return {
            "total_decisions": total,
            "decisions_with_outcome": with_outcome,
            "avg_delta": float(avg_delta) if avg_delta is not None else None,
            "active_rules": n_rules,
        }

    @staticmethod
    def _row_to_decision(row: sqlite3.Row) -> Decision:
        return Decision(
            id=row["id"],
            entry_id=row["entry_id"],
            gw=row["gw"],
            agent_type=row["agent_type"],
            decision=json.loads(row["decision_json"]),
            context=json.loads(row["context_json"]),
            actual_outcome=json.loads(row["actual_outcome_json"]) if row["actual_outcome_json"] else None,
            outcome_delta=row["outcome_delta"],
            notes=row["notes"],
            created_at=row["created_at"],
        )


# ---------------------------------------------------------------------------
# Retrieval helpers (no embeddings yet — start simple)
# ---------------------------------------------------------------------------

def find_similar_decisions(
    store: MemoryStore,
    entry_id: int,
    agent_type: str,
    current_context: dict,
    gw_max: int,
    top_k: int = 3,
) -> list[Decision]:
    """
    Heuristic similarity (no embedding model needed for Phase 1):
      - Same agent_type
      - Only past decisions (gw < gw_max)
      - Rank by simple feature overlap (same position, similar fixture difficulty,
        similar squad value bracket)
    """
    past = store.get_decisions_for(entry_id, agent_type=agent_type, gw_max=gw_max - 1, limit=200)
    if not past:
        return []

    scored = []
    for d in past:
        score = _similarity_score(d.context, current_context)
        scored.append((score, d))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for _, d in scored[:top_k]]


def _similarity_score(past_ctx: dict, current_ctx: dict) -> float:
    """Very simple overlap score. Refine with embeddings later."""
    if not past_ctx or not current_ctx:
        return 0.0
    score = 0.0
    # Same position bucket?
    if past_ctx.get("position") and past_ctx.get("position") == current_ctx.get("position"):
        score += 1.0
    # Similar difficulty (within 1)?
    pd_diff = past_ctx.get("fixture_difficulty")
    cd_diff = current_ctx.get("fixture_difficulty")
    if pd_diff is not None and cd_diff is not None and abs(pd_diff - cd_diff) <= 1:
        score += 0.7
    # Similar squad value (within £5m)?
    pv = past_ctx.get("squad_value_m")
    cv = current_ctx.get("squad_value_m")
    if pv is not None and cv is not None and abs(pv - cv) <= 5:
        score += 0.3
    # Same chip context
    if past_ctx.get("chip") and past_ctx.get("chip") == current_ctx.get("chip"):
        score += 0.5
    return score


def format_memory_context(decisions: list[Decision]) -> str:
    """Render past decisions as a prompt fragment for injection."""
    if not decisions:
        return ""
    lines = ["Past similar decisions:"]
    for d in decisions:
        outcome = ""
        if d.outcome_delta is not None:
            sign = "+" if d.outcome_delta >= 0 else ""
            outcome = f" → outcome: {sign}{d.outcome_delta:.1f} vs baseline"
        decision_str = json.dumps(d.decision)[:120]
        lines.append(f"  GW{d.gw} ({d.agent_type}): {decision_str}{outcome}")
        if d.notes:
            lines.append(f"    note: {d.notes}")
    return "\n".join(lines)

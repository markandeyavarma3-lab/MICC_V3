"""review.py — the owner's rulings on participants. Plan 1 §6.5.1, Plan 3 step 3.10.

Two kinds of ruling, both keyed on the CLEANED name so they survive every
rebuild of participant_master:

  type    what an UNKNOWN participant is (or a correction to any type)
  merge   ACCEPT or REJECT a suggested duplicate (src/identity/participants.py
          `suggest_merges`). Nothing merges until a ruling says ACCEPT (Q20).

The store is SQLite (review_<env>.sqlite), mutable by design — a ruling can be
changed, and every change keeps its time and note. participants.build() reads
it on every run, so a ruling takes effect on the next nightly rebuild or a
manual `python -m src.identity.participants`.

THE QUEUE ORDER. Plan 1 §6.5.1 orders by deal value x contribution to the
unresolved-symbol rate, so the Phase 3 gate could pass before the queue was
done. The gate passes (unresolved 4.78% < 5%), so the order is rupee deal
value: the participants whose type changes the most money first.

    python -m src.identity.review queue [--n 25]
    python -m src.identity.review merges [--n 25]
    python -m src.identity.review set "CLEANED NAME" TYPE [--note "..."]
    python -m src.identity.review merge "FROM NAME" "TO NAME" [--note "..."]
    python -m src.identity.review keep  "FROM NAME" "TO NAME" [--note "..."]
    python -m src.identity.review types
    python -m src.identity.review progress
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime

from src.common.paths import research_db, review_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS type_decision (
    normalized_name  TEXT PRIMARY KEY,
    participant_type TEXT NOT NULL,
    decided_by       TEXT NOT NULL,
    decided_at       TEXT NOT NULL,
    note             TEXT
);
CREATE TABLE IF NOT EXISTS merge_decision (
    from_name   TEXT NOT NULL,
    to_name     TEXT NOT NULL,
    decision    TEXT NOT NULL CHECK (decision IN ('ACCEPT', 'REJECT')),
    decided_by  TEXT NOT NULL,
    decided_at  TEXT NOT NULL,
    note        TEXT,
    PRIMARY KEY (from_name, to_name)
);
CREATE TABLE IF NOT EXISTS merge_suggestion (
    from_name   TEXT NOT NULL,
    to_name     TEXT NOT NULL,
    why         TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    PRIMARY KEY (from_name, to_name)
);
"""

OWNER = "Markandeya Varma (owner)"


def _con(env: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(review_db(env)))
    con.executescript(_SCHEMA)
    return con


def allowed_types() -> list[str]:
    from src.identity.participants import config
    cfg = config()
    return sorted(set(cfg["name_pattern"]) | {"PROP_HFT", "UNKNOWN"}
                  | set(cfg["review_queue"].get("manual_types", [])))


def decisions(env: str | None = None) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    """({cleaned name: type}, [(from, to, ACCEPT|REJECT)])."""
    con = _con(env)
    try:
        types = dict(con.execute("SELECT normalized_name, participant_type FROM type_decision").fetchall())
        merges = con.execute("SELECT from_name, to_name, decision FROM merge_decision").fetchall()
    finally:
        con.close()
    return types, merges


def store_suggestions(sugg: list[tuple[str, str, str]], env: str | None = None) -> None:
    """Replace the open suggestions with this build's; keep first_seen for any
    that persist. Decided pairs are never re-suggested (the builder filters
    REJECTs; an ACCEPT has already folded the pair into one name)."""
    now = datetime.now(UTC).isoformat()
    con = _con(env)
    try:
        seen = dict(((f, t), s) for f, t, s in
                    con.execute("SELECT from_name, to_name, first_seen FROM merge_suggestion"))
        con.execute("DELETE FROM merge_suggestion")
        con.executemany("INSERT INTO merge_suggestion VALUES (?, ?, ?, ?)",
                        [(f, t, why, seen.get((f, t), now)) for f, t, why in sugg])
        con.commit()
    finally:
        con.close()


def set_type(name: str, ptype: str, note: str | None = None, env: str | None = None) -> None:
    if ptype not in allowed_types():
        raise ValueError(f"{ptype!r} is not a declared type; one of {allowed_types()}")
    con = _con(env)
    try:
        con.execute("INSERT INTO type_decision VALUES (?, ?, ?, ?, ?) ON CONFLICT(normalized_name)"
                    " DO UPDATE SET participant_type = excluded.participant_type,"
                    " decided_by = excluded.decided_by, decided_at = excluded.decided_at,"
                    " note = excluded.note",
                    (name, ptype, OWNER, datetime.now(UTC).isoformat(), note))
        con.commit()
    finally:
        con.close()


def decide_merge(src: str, dst: str, accept: bool, note: str | None = None,
                 env: str | None = None) -> None:
    if src == dst:
        raise ValueError("a participant cannot be merged into itself")
    con = _con(env)
    try:
        con.execute("INSERT INTO merge_decision VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(from_name, to_name)"
                    " DO UPDATE SET decision = excluded.decision, decided_by = excluded.decided_by,"
                    " decided_at = excluded.decided_at, note = excluded.note",
                    (src, dst, "ACCEPT" if accept else "REJECT", OWNER,
                     datetime.now(UTC).isoformat(), note))
        con.commit()
    finally:
        con.close()


def queue(n: int = 25, env: str | None = None) -> list[tuple]:
    """(cleaned name, deals, Rs crore, first, last, sample symbols) — PENDING
    participants by rupee deal value, largest first."""
    import duckdb
    types, _ = decisions(env)
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        rows = con.execute(f"""
            SELECT m.canonical_name, m.deal_count,
                   SUM(TRY_CAST(r.quantity_raw AS DOUBLE) * TRY_CAST(r.deal_price_raw AS DOUBLE)) / 1e7 AS cr,
                   m.first_seen, m.last_seen,
                   string_agg(DISTINCT UPPER(TRIM(r.symbol_raw)), ' ') AS syms
            FROM participant_master m
            JOIN participant_aliases a ON a.participant_id = m.participant_id
            JOIN institutional_deals_raw r ON r.client_name_raw = a.raw_name
            WHERE m.review_status = 'PENDING'
            GROUP BY 1, 2, 4, 5 ORDER BY cr DESC NULLS LAST LIMIT {int(n) + len(types)}""").fetchall()
    finally:
        con.close()
    return [r[:5] + (" ".join(r[5].split()[:6]),) for r in rows if r[0] not in types][:n]


def suggestions(n: int = 25, env: str | None = None) -> list[tuple[str, str, str]]:
    con = _con(env)
    try:
        return con.execute("SELECT from_name, to_name, why FROM merge_suggestion s WHERE NOT EXISTS"
                           " (SELECT 1 FROM merge_decision d WHERE d.from_name = s.from_name"
                           "  AND d.to_name = s.to_name) ORDER BY from_name LIMIT ?", (n,)).fetchall()
    finally:
        con.close()


def progress(env: str | None = None) -> str:
    con = _con(env)
    try:
        t = con.execute("SELECT COUNT(*) FROM type_decision").fetchone()[0]
        acc, rej = (con.execute("SELECT COUNT(*) FROM merge_decision WHERE decision = ?", (d,)).fetchone()[0]
                    for d in ("ACCEPT", "REJECT"))
        open_ = con.execute("SELECT COUNT(*) FROM merge_suggestion s WHERE NOT EXISTS (SELECT 1 FROM"
                            " merge_decision d WHERE d.from_name = s.from_name AND d.to_name = s.to_name)"
                            ).fetchone()[0]
    finally:
        con.close()
    import duckdb
    db = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        pending = db.execute("SELECT COUNT(*) FROM participant_master WHERE review_status = 'PENDING'"
                             ).fetchone()[0]
    finally:
        db.close()
    return (f"  type rulings {t:,}; queue still PENDING {pending:,} (as of the last build)\n"
            f"  merges accepted {acc:,}, kept separate {rej:,}; suggestions open {open_:,}\n"
            f"  rulings take effect on the next build: python -m src.identity.participants")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("queue", "merges"):
        sub.add_parser(c).add_argument("--n", type=int, default=25)
    s = sub.add_parser("set")
    s.add_argument("name")
    s.add_argument("ptype")
    s.add_argument("--note")
    for c in ("merge", "keep"):
        m = sub.add_parser(c)
        m.add_argument("src")
        m.add_argument("dst")
        m.add_argument("--note")
    sub.add_parser("types")
    sub.add_parser("progress")
    a = ap.parse_args(argv)

    if a.cmd == "queue":
        for i, (name, n, cr, f, last, syms) in enumerate(queue(a.n), 1):
            print(f"{i:>3}. {name:<55} {n:>5} deals  Rs {cr or 0:>9,.0f} cr  {f}..{last}  [{syms}]")
    elif a.cmd == "merges":
        for i, (f, t, why) in enumerate(suggestions(a.n), 1):
            print(f"{i:>3}. {f}\n     -> {t}   ({why})")
    elif a.cmd == "set":
        set_type(a.name, a.ptype, a.note)
        print(f"  {a.name} -> {a.ptype}")
    elif a.cmd in ("merge", "keep"):
        decide_merge(a.src, a.dst, a.cmd == "merge", a.note)
        print(f"  {a.src} {'MERGED INTO' if a.cmd == 'merge' else 'KEPT SEPARATE FROM'} {a.dst}")
    elif a.cmd == "types":
        print("  " + ", ".join(allowed_types()))
    else:
        print(progress())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

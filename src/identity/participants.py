"""participants.py — one participant per cleaned name, every spelling an alias.
Plan 1 §6.4–6.5, Plan 3 steps 3.6 (participant_master), 3.9 (merge
suggestions, never applied) and 3.12 (the fund-house mapping).

THE RULES ARE THE OWNER'S, FROM PLAN 1:
  Q19  exact match after cleaning — `entity_names.normalize`, the one cleaning
       rule the counterparty counts already use. No fuzzy matching anywhere.
  Q20  variants stay separate until the owner rules. A likely duplicate is
       written to `participant_aliases.suggested_merge_id` and to the review
       queue; it is NEVER applied by this module.
  Q21  fund houses come from a MANUAL file, configs/fund_houses.yml.
  Q18  PROP_HFT is a category, found by behaviour.

CLASSIFICATION ORDER (participants.yml `classification_order`, plus the owner):
  MANUAL       the owner's ruling in the review db (src/identity/review.py)
  BEHAVIOURAL  PROP_HFT — >= min_client_stock_days and >= roundtrip_ratio same-
               day round trips, measured on the CLEANED name (all spellings)
  NAME_PATTERN participants.yml `name_pattern`, first match in file order
  UNKNOWN      nothing says; queued for review when it has >= min_deals_to_enqueue

DECISIONS ARE KEYED ON THE CLEANED NAME, NOT AN ID. participant_id is
reassigned on every rebuild (row order); a ruling stored against an id would
silently move to another participant the night a new name sorts before it.

WHAT THIS DOES NOT YET DO. Nothing reads participant_id downstream:
`institutional_deals_clean.participant_id` is still NULL, and the mart's
PROP_HFT rule and both round-trip flags key on the raw spelling. Moving them
to this table changes every eligible sample, so it is its own decision.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

import duckdb
import yaml

from src.common.paths import CONFIGS, governance_db, research_db
from src.governance import provenance as prov
from src.research.entity_names import normalize

PRODUCED_BY = "src.identity.participants:build"
FUND_HOUSES = CONFIGS / "fund_houses.yml"


def config() -> dict:
    return yaml.safe_load((CONFIGS / "participants.yml").read_text())


def classify_name(norm: str, patterns: dict[str, str]) -> str | None:
    """The first participants.yml name pattern that matches, in file order."""
    for ptype, pat in patterns.items():
        if re.search(pat, norm):
            return ptype
    return None


def fund_house(norm: str, groups: dict[str, dict]) -> str | None:
    for gid, g in groups.items():
        if re.search(g["pattern"], norm):
            return gid
    return None


def _lev(a: str, b: str, cap: int) -> int:
    """Levenshtein distance, giving up once it exceeds `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


#: Suggestions are surfaced only where at least one side matters for a track
#: record; the queue is read by a person and 19,000 individuals would bury it.
SUGGEST_MIN_LEN = 10
SUGGEST_MAX_EDITS = 2


def suggest_merges(deals: dict[str, int], min_deals: int) -> list[tuple[str, str, str]]:
    """(from, to, why): likely duplicates, FROM the smaller TO the larger.

    Two tests, both conservative and both only suggestions:
      same words    the same tokens in a different order
      near spelling at most SUGGEST_MAX_EDITS character edits, names at least
                    SUGGEST_MIN_LEN long, blocked on the first three characters
    A pair is suggested only if at least one side has >= `min_deals` deals.
    Distinct legal entities that differ by one token — "... MAURITIUS I" and
    "... MAURITIUS II" — WILL be suggested; that is why a person decides.
    """
    names = sorted(deals)
    out: dict[tuple[str, str], str] = {}

    def add(a: str, b: str, why: str) -> None:
        if max(deals[a], deals[b]) < min_deals:
            return
        src, dst = sorted((a, b), key=lambda n: (deals[n], n))
        out.setdefault((src, dst), why)

    by_tokens: dict[str, list[str]] = {}
    for n in names:
        by_tokens.setdefault(" ".join(sorted(n.split())), []).append(n)
    for group in by_tokens.values():
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                add(a, b, "same words, different order")

    blocks: dict[str, list[str]] = {}
    for n in names:
        if len(n) >= SUGGEST_MIN_LEN:
            blocks.setdefault(n[:3], []).append(n)
    for group in blocks.values():
        if len(group) < 2:
            continue
        heavy = [n for n in group if deals[n] >= min_deals]
        for a in heavy:
            for b in group:
                if a != b and _lev(a, b, SUGGEST_MAX_EDITS) <= SUGGEST_MAX_EDITS:
                    add(a, b, f"differs by at most {SUGGEST_MAX_EDITS} characters")
    return [(a, b, why) for (a, b), why in sorted(out.items())]


@dataclass
class Report:
    raw_names: int = 0
    participants: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_method: dict[str, int] = field(default_factory=dict)
    queued: int = 0
    suggestions: int = 0
    merges_applied: int = 0
    fund_house_members: int = 0
    manual_rulings: int = 0

    def render(self) -> str:
        lines = [f"  raw spellings      {self.raw_names:>8,}",
                 f"  participants       {self.participants:>8,}  (one per cleaned name, after "
                 f"{self.merges_applied:,} owner-accepted merge(s))",
                 "  by type:"]
        lines += [f"    {k:<20} {v:>8,}" for k, v in sorted(self.by_type.items(), key=lambda x: -x[1])]
        lines += ["  by method:"] + [f"    {k:<20} {v:>8,}" for k, v in sorted(self.by_method.items())]
        lines += [f"  owner rulings applied        {self.manual_rulings:>6,}",
                  f"  fund-house members           {self.fund_house_members:>6,}",
                  f"  review queue (UNKNOWN, PENDING)  {self.queued:>6,}",
                  f"  merge suggestions pending        {self.suggestions:>6,}  (recorded, never applied)"]
        return "\n".join(lines)


def build(env: str | None = None) -> Report:
    from src.identity import review

    cfg = config()
    patterns = cfg["name_pattern"]
    hft = cfg["behavioural"]["prop_hft"]
    min_deals = int(cfg["review_queue"]["min_deals_to_enqueue"])
    houses = yaml.safe_load(FUND_HOUSES.read_text())["groups"] if FUND_HOUSES.exists() else {}
    types, merges = review.decisions(env)
    accepted = {f: t for f, t, d in merges if d == "ACCEPT"}
    rejected = {(f, t) for f, t, d in merges if d == "REJECT"}

    rep = Report()
    con = duckdb.connect(str(research_db(env)))
    try:
        raw = con.execute("""
            SELECT client_name_raw, COUNT(*) AS n,
                   SUM(TRY_CAST(quantity_raw AS DOUBLE) * TRY_CAST(deal_price_raw AS DOUBLE)) AS v,
                   MIN(trade_date) AS first_d, MAX(trade_date) AS last_d
            FROM institutional_deals_raw WHERE client_name_raw IS NOT NULL GROUP BY 1""").fetchall()
        rep.raw_names = len(raw)

        # Cleaned name, then any owner-accepted merge (followed to its end, so
        # A->B and B->C put A under C; a cycle is refused, not followed).
        def target(n: str) -> str:
            seen = {n}
            while n in accepted:
                n = accepted[n]
                if n in seen:
                    raise ValueError(f"merge cycle through {n!r} in the review db")
                seen.add(n)
            return n

        entity = {r[0]: target(normalize(r[0])) for r in raw}
        rep.merges_applied = sum(1 for n in {normalize(r[0]) for r in raw} if n in accepted)
        con.execute("CREATE OR REPLACE TEMP TABLE _pn (raw VARCHAR, ent VARCHAR)")
        con.executemany("INSERT INTO _pn VALUES (?, ?)", list(entity.items()))

        # BEHAVIOUR, on the cleaned identity: every spelling's client-stock-days together.
        prop = {r[0] for r in con.execute(f"""
            WITH csd AS (
                SELECT p.ent, UPPER(TRIM(r.symbol_raw)) AS sym, r.trade_date,
                       MAX(CASE WHEN UPPER(r.side_raw) LIKE 'B%' THEN 1 ELSE 0 END) AS b,
                       MAX(CASE WHEN UPPER(r.side_raw) LIKE 'S%' THEN 1 ELSE 0 END) AS s
                FROM institutional_deals_raw r JOIN _pn p ON p.raw = r.client_name_raw
                GROUP BY 1, 2, 3)
            SELECT ent FROM csd GROUP BY 1
            HAVING COUNT(*) >= {int(hft['min_client_stock_days'])}
               AND SUM(b * s) * 1.0 / COUNT(*) >= {float(hft['roundtrip_ratio'])}""").fetchall()}

        agg: dict[str, list] = {}
        for name, n, v, f, last in raw:
            e = entity[name]
            a = agg.setdefault(e, [0, 0.0, f, last])
            a[0] += n
            a[1] += v or 0.0
            a[2] = min(a[2], f)
            a[3] = max(a[3], last)

        deals = {e: a[0] for e, a in agg.items()}
        sugg = [s for s in suggest_merges(deals, min_deals) if (s[0], s[1]) not in rejected]
        rep.suggestions = len(sugg)

        names = sorted(agg)
        group_ids = sorted({g for g in (fund_house(n, houses) for n in names) if g})
        pid = {n: i for i, n in enumerate([f"FUND HOUSE {g}" for g in group_ids] + names, start=1)}
        master, aliases = [], []
        for g in group_ids:
            master.append((pid[f"FUND HOUSE {g}"], f"FUND HOUSE {g}", "FUND_HOUSE", "MANUAL", None,
                           None, "HIGH", None, None, 0, "REVIEWED"))
        for n in names:
            count, _value, first_d, last_d = agg[n]
            if n in types:
                ptype, method, conf = types[n], "MANUAL", "HIGH"
                rep.manual_rulings += 1
            elif n in prop:
                ptype, method, conf = "PROP_HFT", "BEHAVIOURAL", "HIGH"
            elif (t := classify_name(n, patterns)) is not None:
                ptype, method = t, "NAME_PATTERN"
                conf = "LOW" if t == "INDIVIDUAL" else "MEDIUM"
            else:
                ptype, method, conf = "UNKNOWN", "NAME_PATTERN", "UNKNOWN"
            status = ("REVIEWED" if method == "MANUAL"
                      else "PENDING" if ptype == "UNKNOWN" and count >= min_deals else "AUTO")
            rep.queued += status == "PENDING"
            house = fund_house(n, houses)
            rep.fund_house_members += house is not None
            parent = pid[f"FUND HOUSE {house}"] if house else None
            master.append((pid[n], n, ptype, method, parent, None, conf, first_d, last_d, count, status))
            rep.by_type[ptype] = rep.by_type.get(ptype, 0) + 1
            rep.by_method[method] = rep.by_method.get(method, 0) + 1
        rep.participants = len(names)

        sugg_to = {a: b for a, b, _ in sugg}
        for i, (name, *_rest) in enumerate(sorted(raw), start=1):
            n0 = normalize(name)
            e = entity[name]
            method = "MANUAL" if e != n0 else ("EXACT" if name.strip().upper() == n0 else "CLEANED")
            aliases.append((i, pid[e], name, n0, method, "HIGH" if method != "CLEANED" else "MEDIUM",
                            pid.get(sugg_to.get(e)) if e in sugg_to else None,
                            "PENDING" if e in sugg_to else "AUTO"))

        # NOT one transaction: DuckDB refuses a parent delete inside the
        # transaction that deleted its children (the same limit master.py
        # records, decision 0049). Every row above was computed BEFORE these
        # deletes, so a failure up to here leaves the old tables intact.
        con.execute("DELETE FROM participant_aliases")
        con.execute("DELETE FROM participant_master")
        con.executemany(
            "INSERT INTO participant_master (participant_id, canonical_name, participant_type,"
            " classification_method, parent_group_id, country, confidence_level, first_seen,"
            " last_seen, deal_count, review_status) VALUES (?,?,?,?,?,?,?,?,?,?,?)", master)
        con.executemany(
            "INSERT INTO participant_aliases (alias_id, participant_id, raw_name, normalized_name,"
            " mapping_method, mapping_confidence, suggested_merge_id, review_status)"
            " VALUES (?,?,?,?,?,?,?,?)", aliases)
    finally:
        con.close()

    review.store_suggestions(sugg, env)
    g = sqlite3.connect(governance_db(env))
    try:
        parents = [(r[0], "input") for r in g.execute(
            "SELECT artefact_hash FROM (SELECT artefact_hash, ROW_NUMBER() OVER ("
            " PARTITION BY logical_name ORDER BY produced_at DESC) AS rn FROM artefact"
            " WHERE logical_name = 'warehouse:institutional_deals_raw') WHERE rn = 1").fetchall()]
    finally:
        g.close()
    prov.register(
        prov.Artefact(
            prov.hash_params({"participants": rep.participants, "aliases": rep.raw_names,
                              "rulings": rep.manual_rulings, "merges": rep.merges_applied}),
            "TABLE", "warehouse:participant_master", PRODUCED_BY, row_count=rep.participants,
            params={"queued": rep.queued, "suggestions": rep.suggestions}),
        parents=parents, env=env)
    return rep


def main() -> int:
    print("PARTICIPANTS (Plan 1 §6.4-6.5) — one per cleaned name; nothing merges without the owner")
    print(build().render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

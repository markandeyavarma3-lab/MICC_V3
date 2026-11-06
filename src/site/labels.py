"""labels.py — corrections to investor labels, for the site only.

WHY (2026-11-06). `participant_master` types most investors by a pattern on the
CLEANED name, and cleaning strips the legal form: TATA SONS LTD became TATA SONS
and read as a person. 14,778 participants are INDIVIDUAL, and 2,431 of them
(Rs 3.85 lakh crore of Rs 7.07 lakh crore) have a company's name in the exchange's
own raw record. HERO MOTOCORP LIMITED, DAIICHI SANKYO COMPANY LIMITED.

THE RESEARCH TABLE IS NOT TOUCHED. Those types feed the studies and 0083 leaves
identity to the owner, who chose this site-only correction on 2026-11-06. A row in
the file changes what a page calls an investor, and nothing else.

NARROW ON PURPOSE. Only an explicit legal form or an unmistakable name. FIDELITY
SHARES AND SECURITIES is an Indian broker, not the US fund house, so a brand alone
does not move a BROKER label except VANGUARD, which has no Indian broker. A MANUAL
classification is never overruled. What the rules cannot read stays as it is.

The file lives under data/ (not in the public repo): it names exchange clients.

    RESEARCH_ENV=prod .venv/bin/python -m src.site.labels
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ROOT, research_db  # noqa: E402

LABELS_FILE = ROOT / "data" / "derived" / "site_participant_labels.csv"
METHOD = "RAW_NAME_RULE"

#: First match wins, against every raw spelling of the participant.
_RULES: tuple[tuple[str, str], ...] = (
    ("BANK", r"\bBANK\b|\bBANQUE\b|CITIBANK|SOCIETE GENERALE|BNP PARIBAS"),
    ("MUTUAL_FUND", r"\bMUTUAL FUND\b"),
    ("INSURANCE", r"\bINSURANCE\b|\bASSURANCE\b"),
    ("FOREIGN_INSTITUTION", r"\bFUNDS?\b|\bETF\b|\bSICAV\b|\bPTE\b|\bPLC\b|\bGMBH\b|\bB\.? ?V\.?$|\bAKTIENGESELLSCHAFT\b"
                            r"|\bL\.?P\.?$|\bLLC\b|\bINC\.?$|KAPITALFORENINGEN"),
    ("CORPORATE", r"\bLIMITED\b|\bLTD\b|\bPVT\b|\bPRIVATE\b|\bLLP\b|\bCORPORATION\b|\bCOMPANY\b|\bTRUSTEESHIP\b"),
)
_VANGUARD = re.compile(r"\bVANGUARD\b")


def proposed(ptype: str | None, method: str | None, raw_names: list[str]) -> str | None:
    """The corrected type, or None to leave the label alone."""
    if method == "MANUAL":
        return None
    text = " | ".join(n.upper().strip() for n in raw_names)
    if ptype == "BROKER_SEC":
        return "FOREIGN_INSTITUTION" if _VANGUARD.search(text) else None
    if ptype != "INDIVIDUAL":
        return None
    for label, pat in _RULES:
        if any(re.search(pat, n.upper().strip()) for n in raw_names):
            return label
    return None


def load(path: Path | None = None) -> dict[str, str]:
    """canonical name -> corrected type (one participant per cleaned name, 0083).
    No file means no corrections."""
    path = path or LABELS_FILE
    if not path.exists():
        return {}
    with path.open(newline="") as fh:
        return {r["name"]: r["corrected_type"] for r in csv.DictReader(fh)}


def build(env: str | None = None, path: Path | None = None) -> list[dict]:
    """Read-only on the database. Writes the file, largest deal value first."""
    import duckdb
    path = path or LABELS_FILE
    con = duckdb.connect(str(research_db(env)), read_only=True)
    try:
        rows = con.execute("""
            SELECT pm.participant_id, pm.canonical_name, pm.participant_type, pm.classification_method,
                   r.client_name_raw, COUNT(*), SUM(c.gross_deal_value) / 1e7
            FROM institutional_deals_clean c
            JOIN institutional_deals_raw r USING (raw_deal_id)
            JOIN participant_aliases pa ON pa.raw_name = r.client_name_raw
            JOIN participant_master pm ON pm.participant_id = pa.participant_id
            GROUP BY ALL""").fetchall()
    finally:
        con.close()
    by: dict[str, dict] = {}
    for pid, name, ptype, method, raw, n, cr in rows:
        e = by.setdefault(str(pid), {"name": name, "type": ptype, "method": method, "raw": [], "n": 0, "cr": 0.0})
        e["raw"].append(raw)
        e["n"] += n
        e["cr"] += cr or 0.0
    out = []
    for pid, e in by.items():
        to = proposed(e["type"], e["method"], e["raw"])
        if to:
            out.append({"participant_id": pid, "name": e["name"], "current_type": e["type"], "corrected_type": to,
                        "deals": e["n"], "cr": round(e["cr"], 1), "raw_name": e["raw"][0]})
    out.sort(key=lambda r: -r["cr"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["participant_id", "name", "current_type", "corrected_type", "deals", "cr", "raw_name"])
        w.writeheader()
        w.writerows(out)
    return out


def main() -> int:
    got = build()
    print(f"  LABELS: {len(got):,} corrected, Rs {sum(r['cr'] for r in got):,.0f} cr of deals -> {LABELS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

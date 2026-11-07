"""lab.py — the data behind the website's Research lab. Decision 0094.

Writes research-website/public/data/lab/events.json: one row per event, with the
abnormal return after it, for the event-study explorer. This is the ONLY place
on the site that may carry an after-event return, so three rules are enforced in
code rather than left to the page:

  EXPLORE ONLY   Events are filtered to EXPLORE stocks (split.assign) BEFORE any
                 return is computed, and `write` refuses a row from any other
                 stratum. SELECT and CONFIRM events never reach the return query.
  ITS OWN FOLDER Everything lands in `lab/`. src/site/export.py never imports this
                 module, so the test banning return fields keeps its full force
                 on every other file. scripts/site_publish.sh refuses to publish
                 while the section exists.
  LABELLED       The file states it is exploratory, not pre-registered. The page
                 shows that with the sample size and a count of slices tried.

SAME METHOD AS THE STUDIES. Returns come from resignation_study.abnormal: entered
at the open after the filing, sessions counted as sessions, against comparable
stocks (CHAR_MATCHED: size x momentum x volatility, self-excluded). The comparison
cells use every stock, as in the registered studies; a cell mean is a benchmark
and reveals no after-event average for a SELECT or CONFIRM stock.

Returns end at measure.REPRODUCIBILITY_HORIZON, so this file changes little from
night to night. It is heavy, and is run by hand outside the collector window:

    RESEARCH_ENV=prod .venv/bin/python -m src.site.lab
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from src.common.paths import warehouse_dir
from src.research import insider_power, measure, pead_power, resignation_study, resignations, split
from src.site.export import SITE_DATA, sym_file

HORIZONS = (5, 21, 63)
LABEL = "Exploratory, not pre-registered"
#: code -> what the page calls it. Each is one per company per 21 sessions.
TYPES = {
    "DEAL_BUY": "Bulk or block deal: buy",
    "DEAL_SELL": "Bulk or block deal: sell",
    "PROMOTER_BUY": "Promoter insider buy",
    "PROMOTER_SELL": "Promoter insider sell",
    "PLEDGE": "Promoter pledge created",
    "RESULT_UP": "Quarterly profit up on a year ago",
    "RESULT_DOWN": "Quarterly profit down on a year ago",
    "RESIGNATION": "Governance resignation",
}


class LabLeak(RuntimeError):
    """A row from outside EXPLORE reached the lab's file (decision 0094)."""


def is_explore(isin: str) -> bool:
    return split.assign("", isin)[0] == "EXPLORE"


def explore_only(evs: list[resignations.Event]) -> list[resignations.Event]:
    return [e for e in evs if is_explore(e.isin)]


def result_direction(res: pd.DataFrame) -> pd.Series:
    """'RESULT_UP' or 'RESULT_DOWN' against the same quarter a year earlier; None
    where either profit is missing or unchanged. Pure; reads profits only."""
    qe = pd.to_datetime(res["qe"])
    key = qe.dt.year * 4 + (qe.dt.month - 1) // 3
    prior = dict(zip(zip(res["symbol"], key, strict=True), res["pat"], strict=True))

    def one(sym: str, k: int, pat: float) -> str | None:
        old = prior.get((sym, k - 4))
        if pat is None or old is None or pd.isna(pat) or pd.isna(old) or pat == old:
            return None
        return "RESULT_UP" if pat > old else "RESULT_DOWN"

    return pd.Series([one(s, k, p) for s, k, p in zip(res["symbol"], key, res["pat"], strict=True)],
                     index=res.index, dtype=object)


#: The mart's reason for a sell that passed every earlier check. eligible_for_research
#: is buys only, so sells are picked by this reason. The mart's size floors are
#: applied after it, so sells are not size-filtered the way buys are.
SELL_REASON = "not a buy (sells not yet studied)"


def _deal_events(con) -> list[resignations.Event]:
    return [resignations.Event(d, i, f"DEAL_{side}") for d, i, side in con.execute("""
        SELECT DISTINCT CAST(c.trade_date AS VARCHAR), m.isin, c.side
        FROM institutional_deals_clean c JOIN security_master m USING (security_id)
        WHERE (c.eligible_for_research OR c.ineligibility_reason = ?) AND m.isin IS NOT NULL""",
        [SELL_REASON]).fetchall()]


def _promoter_events(con) -> list[resignations.Event]:
    out: list[resignations.Event] = []
    for code, txn in (("PROMOTER_BUY", "Buy"), ("PROMOTER_SELL", "Sell"), ("PLEDGE", "Pledge")):
        out += [resignations.Event(d, i, code) for d, i in con.execute(f"""
            SELECT DISTINCT e.tdate, m.isin
            FROM ({insider_power._events_sql(f"transaction_type = '{txn}'")}) e
            JOIN security_master m USING (security_id) WHERE m.isin IS NOT NULL""").fetchall()]
    return out


def _result_events(env: str | None) -> list[resignations.Event]:
    _, res = pead_power.events(env)
    res = res.assign(code=result_direction(res)).dropna(subset=["code", "isin", "tdate"])
    return [resignations.Event(t, i, c) for t, i, c in zip(res["tdate"], res["isin"], res["code"], strict=True)]


def all_events(rows: list[dict], sessions: list[str], env: str | None = None) -> list[resignations.Event]:
    """Every event type, de-clustered per type: a company counts once per 21
    sessions, as in exp_007, so a run of filings is not many observations."""
    con = duckdb.connect(str(measure.research_db(env)), read_only=True)
    try:
        raw = _deal_events(con) + _promoter_events(con)
    finally:
        con.close()
    raw += _result_events(env)
    raw += [resignations.Event(e.date, e.isin, "RESIGNATION")
            for e in resignation_study.governance_events(rows, sessions)]
    out: list[resignations.Event] = []
    for code in TYPES:
        out += resignations.first_in_window([e for e in raw if e.role == code], sessions)
    return out


def _size(df: pd.DataFrame, env: str | None) -> pd.DataFrame:
    """Each event's size quintile (1 smallest) at the last rebalance before it."""
    charp = str(warehouse_dir(env) / "char_panel" / "**" / "*.parquet")
    q = duckdb.connect()
    try:
        q.register("e", df[["symbol", "tdate"]].drop_duplicates())
        return q.execute(f"""
            SELECT e.symbol, e.tdate, c.size_q AS size
            FROM (SELECT symbol, tdate, CAST(tdate AS DATE) AS d FROM e) e
            ASOF JOIN read_parquet('{charp}') c ON c.symbol = e.symbol AND c.rebalance_date <= e.d""").df()
    finally:
        q.close()


def assemble(frames: dict[int, pd.DataFrame], sizes: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per event from one abnormal() frame per horizon: role, tdate, isin,
    symbol, size, then a<h> in percent. A blank means no return at that horizon
    (the window passed the data's end, or a suspension broke it)."""
    keys = ["role", "tdate", "isin", "symbol"]
    out: pd.DataFrame | None = None
    for h, f in frames.items():
        x = f[keys].copy()
        x[f"a{h}"] = (f["ab_CHAR_MATCHED"].astype(float) * 100).round(2)
        out = x if out is None else out.merge(x, on=keys, how="outer")
    if out is None:
        raise ValueError("no horizon was computed")
    if sizes is not None and len(sizes):
        out = out.merge(sizes, on=["symbol", "tdate"], how="left")
    else:
        out["size"] = None
    return out.sort_values(["tdate", "symbol", "role"]).reset_index(drop=True)


def _num(v) -> float | int | None:
    return None if v is None or pd.isna(v) else (int(v) if float(v).is_integer() else float(v))


def write(df: pd.DataFrame, out: Path = SITE_DATA) -> Path:
    """data/lab/events.json. Refuses the whole file if one row is not EXPLORE."""
    leaked = sorted({i for i in df["isin"] if not is_explore(i)})
    if leaked:
        raise LabLeak(f"{len(leaked)} non-EXPLORE ISIN(s) reached the lab, e.g. {leaked[:3]}")
    cols = ["type", "d", "sym", "sid", "size", *(f"a{h}" for h in HORIZONS)]
    rows = [[r["role"], r["tdate"], r["symbol"], sym_file(r["symbol"]), _num(r["size"]), *(_num(r[f"a{h}"]) for h in HORIZONS)]
            for _, r in df.iterrows() if r["role"] in TYPES]
    doc = {"label": LABEL, "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "returns_end": measure.REPRODUCIBILITY_HORIZON, "stratum": "EXPLORE", "benchmark": "CHAR_MATCHED",
           "horizons": list(HORIZONS), "types": TYPES, "cols": cols, "rows": rows}
    path = Path(out) / "lab" / "events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":")))
    return path


def build(env: str | None = None, out: Path = SITE_DATA) -> Path:
    rows, sessions = resignation_study._load()
    evs = explore_only(all_events(rows, sessions, env))
    print(f"  LAB: {len(evs):,} EXPLORE events", flush=True)
    frames = {}
    for h in HORIZONS:
        frames[h] = resignation_study.abnormal(env, evs, h)
        print(f"  LAB: {h} sessions, {frames[h]['ab_CHAR_MATCHED'].notna().sum():,} returns", flush=True)
    df = assemble(frames)
    df = assemble(frames, _size(df, env))
    return write(df, out)


def main() -> int:
    path = build()
    print(f"  LAB: wrote {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

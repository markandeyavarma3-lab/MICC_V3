"""partitioned.py — replace a partitioned parquet dataset whole, never in place.

WHY (2026-10-09). Four tables were written with

    COPY (...) TO '<dir>' (FORMAT PARQUET, PARTITION_BY (k), OVERWRITE_OR_IGNORE 1)

which overwrites `data_0.parquet` in each partition and LEAVES any
`data_1.parquet` an earlier, larger write put there. `char_panel` carried
such files from August: 29,833 (symbol, rebalance_date) keys twice, 241 with
two different quantile cells. Every CHAR_MATCHED benchmark read the
duplicates, and which copy the ASOF join took varied between runs — exp_002's
re-measure gave rank IC -0.217 and -0.238 on identical inputs.

The dataset is written to a sibling `<dir>.partial`, then swapped in: the old
directory moves aside and is deleted only after the new one is in place. A
partition can no longer outlive the write that should have replaced it.
"""

from __future__ import annotations

import shutil
from pathlib import Path


def replace_partitioned(con, select_sql: str, out: Path, partition_by: str) -> None:
    out = Path(out)
    tmp = out.with_name(out.name + ".partial")
    old = out.with_name(out.name + ".old")
    for d in (tmp, old):
        if d.exists():
            shutil.rmtree(d)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({select_sql}) TO '{tmp}' (FORMAT PARQUET, PARTITION_BY ({partition_by}))")
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    if old.exists():
        shutil.rmtree(old)

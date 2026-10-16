"""NSE's MTO delivery file, parsed."""

from __future__ import annotations

import pytest

from src.archive import delivery as D

MTO = """Security Wise Delivery Position - Compulsory Rolling Settlement
10,MTO,03012006,132065782,0000762
Trade Date <03-JAN-2006>,Settlement Type <N>,Settlement No <2006002>,Settlement Date <05-JAN-2006>
Record Type,Sr No,Name of Security,Quantity Traded,Deliverable Quantity(gross across client level),% of Deliverable Quantity to Traded Quantity
20,1,3IINFOTECH,EQ,725638,258161,35.58
20,2,3MINDIA,EQ,1337,864,64.62
20,3,BADROW,EQ,x,1,2
"""


@pytest.mark.unit
def test_only_security_rows_are_read_and_a_bad_number_is_skipped():
    assert D.parse(MTO) == [("3IINFOTECH", "EQ", 725638.0, 258161.0, 35.58), ("3MINDIA", "EQ", 1337.0, 864.0, 64.62)]


@pytest.mark.unit
def test_stored_and_missing_sessions_are_done(tmp_path):
    m = tmp_path / "m.jsonl"
    D.record({"session": "2026-10-15", "status": "STORED"}, m)
    D.record({"session": "2026-10-14", "status": "FAILED"}, m)
    D.record({"session": "2026-10-12", "status": "MISSING"}, m)
    assert D.done(m) == {"2026-10-15", "2026-10-12"}

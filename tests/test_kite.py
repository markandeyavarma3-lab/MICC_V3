"""Kite Connect client and the price audit, offline: a fake server, tmp files,
no account touched. The credential rules are the point: files mode 600, a stale
token refused before 2,000 requests fail one by one, no secret in any error."""

from __future__ import annotations

import gzip
import io
import json
import os
from datetime import date
from urllib.error import HTTPError

import duckdb
import pytest

from src.archive import kite
from src.research import price_audit as pa

pytestmark = pytest.mark.unit


def _cred(tmp_path, mode=0o600):
    p = tmp_path / "cred"
    p.write_text("KITE_API_KEY=key123\nKITE_API_SECRET=sekret456\n")
    os.chmod(p, mode)
    return p


def test_the_session_checksum_is_sha256_of_key_token_secret():
    import hashlib
    assert kite.checksum("k", "t", "s") == hashlib.sha256(b"kts").hexdigest()


def test_a_credential_file_others_can_read_is_refused(tmp_path):
    assert kite.creds(_cred(tmp_path)) == ("key123", "sekret456")
    with pytest.raises(kite.KiteAuthError, match="chmod 600"):
        kite.creds(_cred(tmp_path, 0o644))


def test_the_token_is_written_private_and_yesterdays_is_refused(tmp_path):
    p = tmp_path / "tok"
    kite.write_token("abc", p, today=date(2026, 10, 9))
    assert oct(p.stat().st_mode & 0o777) == "0o600"
    assert kite.access_token(p, today=date(2026, 10, 9)) == "abc"
    with pytest.raises(kite.KiteAuthError, match="expire daily"):
        kite.access_token(p, today=date(2026, 10, 10))


@pytest.mark.parametrize("ts,expected", [
    ("TCS", ("TCS", "EQ")), ("ABC-BE", ("ABC", "BE")), ("XYZ-BZ", ("XYZ", "BZ")),
    ("BAJAJ-AUTO", ("BAJAJ-AUTO", "EQ")), ("MCDOWELL-N", ("MCDOWELL-N", "EQ")),
])
def test_kite_names_a_series_by_suffix(ts, expected):
    assert kite.series_of(ts) == expected


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_a_refused_token_raises_auth_and_no_error_carries_the_secret(monkeypatch):
    monkeypatch.setattr(kite, "MIN_GAP_S", 0)

    def opener(req, timeout):
        assert req.get_header("Authorization") == "token key123:acc789"
        raise HTTPError(req.full_url, 403, "Forbidden", {}, None)
    c = kite.Client("key123", "acc789", opener=opener)
    with pytest.raises(kite.KiteAuthError) as e:
        c.get("/instruments/NSE")
    assert "acc789" not in str(e.value) and "key123" not in str(e.value)


def test_history_is_requested_in_spans_kite_accepts(monkeypatch):
    seen = []

    class C:
        def get(self, path, params):
            seen.append((params["from"][:10], params["to"][:10]))
            return json.dumps({"data": {"candles": [["2020-01-01T00:00:00+0530", 1, 1, 1, 1, 1]]}}).encode()
    out = kite.candles(C(), 1, date(2005, 1, 1), date(2026, 10, 8))
    spans = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in seen]
    assert all((b - a).days <= 2000 for a, b in spans)
    assert spans[0][0] == date(2005, 1, 1) and spans[-1][1] == date(2026, 10, 8)
    assert all((spans[i + 1][0] - spans[i][1]).days == 1 for i in range(len(spans) - 1))
    assert len(out) == len(spans)


def test_a_pull_resumes_and_records_in_its_own_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(kite, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(kite, "MANIFEST", tmp_path / "manifest.jsonl")
    inst = ("instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,"
            "lot_size,instrument_type,segment,exchange\n"
            "11,1,AAA,A,0,,0,0.05,1,EQ,NSE,NSE\n22,2,BBB-BE,B,0,,0,0.05,1,EQ,NSE,NSE\n"
            "33,3,NIFTY 50,N,0,,0,0,0,EQ,INDICES,NSE\n"
            "44,4,775MH35-SG,S,0,,0,0.01,1,EQ,NSE,NSE\n")                # a state loan: not a stock
    calls = []

    class C:
        def get(self, path, params=None):
            calls.append(path)
            if path == "/instruments/NSE":
                return inst.encode()
            return json.dumps({"data": {"candles": [["2026-10-08T00:00:00+0530", 1, 2, 0.5, 1.5, 10]]}}).encode()
    end = date(2026, 10, 8)
    st = kite.pull(C(), end, start=date(2026, 10, 1))
    assert (st["instruments"], st["stored"]) == (2, 2)           # the index row is not a stock
    rows = [json.loads(x) for x in (tmp_path / "manifest.jsonl").read_text().splitlines()]
    assert {r["series"] for r in rows} == {"EQ", "BE"}
    calls.clear()
    st = kite.pull(C(), end, start=date(2026, 10, 1))
    assert st["already"] == 2 and calls == ["/instruments/NSE"]   # resumed: no candle re-fetched


def _parquet(path, rows):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (symbol VARCHAR, date VARCHAR, close DOUBLE)")
    con.executemany("INSERT INTO t VALUES (?, ?, ?)", rows)
    con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
    con.close()


def test_the_audit_finds_an_unadjusted_split_as_a_step(tmp_path):
    days = [f"2024-01-{d:02d}" for d in range(1, 31)]
    kite_rows = [("SPLT", d, 50.0) for d in days] + [("GOOD", d, 100.0) for d in days]
    # Our adjusted series missed a 1:2 split on the 15th: 100 before, 50 after.
    ours = [("SPLT", d, 100.0 if d < "2024-01-15" else 50.0) for d in days] + [("GOOD", d, 100.0) for d in days]
    _parquet(tmp_path / "k.parquet", kite_rows)
    for name in ("raw", "adj"):
        (tmp_path / name).mkdir()
        _parquet(tmp_path / name / "p.parquet", ours)
    con = duckdb.connect()
    rows = con.execute(pa.audit_sql(str(tmp_path / "k.parquet"), str(tmp_path / "raw" / "*.parquet"),
                                    str(tmp_path / "adj" / "*.parquet"))
                       + " ").fetchall()
    steps = [(r[0], r[1]) for r in rows if r[-1]]
    assert steps == [("SPLT", "2024-01-15")]
    assert pa.classify(1.0, 1.0) == "both" and pa.classify(0.5, 0.995) == "adjusted"
    assert pa.classify(0.5, 0.5) == "neither"


def test_the_audit_report_carries_no_price(tmp_path):
    res = {"per": [("GOOD", 30, 1.0, 1.0, 0, "2024-01-01", "2024-01-30"),
                   ("BAD", 30, 0.2, 0.3, 1, "2024-01-01", "2024-01-30")],
           "steps": [("BAD", "2024-01-15", -50.0)], "kite_symbols": 3}
    text = pa.render(res)
    assert "BAD" in text and "-50.0%" in text and "123.45" not in text
    assert "with NEITHER: 1" in text


def test_no_kite_credential_or_token_path_is_inside_the_repository():
    from src.common.paths import ROOT
    for p in (kite.CRED, kite.TOKEN):
        assert ROOT not in p.parents


def test_candle_files_are_gzipped_json_with_their_instrument(tmp_path, monkeypatch):
    monkeypatch.setattr(kite, "ROOT_DIR", tmp_path)
    p = kite._path("candles", "11_AAA", date(2026, 10, 8))
    assert p.name == "11_AAA_20261008.json.gz" and tmp_path in p.parents
    p.parent.mkdir(parents=True)
    p.write_bytes(gzip.compress(b"{}"))
    assert json.loads(gzip.decompress(p.read_bytes())) == {}


def test_run_end_to_end_on_a_tmp_warehouse(tmp_path, monkeypatch):
    """run() was untested and died on its first real call: `first` and `last`
    are reserved words in DuckDB."""
    days = [f"2024-01-{d:02d}" for d in range(1, 31)]
    _parquet(tmp_path / "k.parquet", [("GOOD", d, 100.0) for d in days])
    for name in ("price_spine", "price_spine_adj"):
        (tmp_path / name / "_y=2024").mkdir(parents=True)
        _parquet(tmp_path / name / "_y=2024" / "p.parquet", [("GOOD", d, 100.0) for d in days])
    monkeypatch.setattr(pa, "warehouse_dir", lambda env=None: tmp_path)
    res = pa.run(tmp_path / "k.parquet")
    assert res["per"] == [("GOOD", 30, 1.0, 1.0, 0, "2024-01-01", "2024-01-30")]
    assert res["steps"] == [] and res["kite_symbols"] == 1

"""verify_copy.py: prove the cloud copy is the laptop's copy, file for file.

A copy that "finished" is not a copy that is right: a file cut short, skipped or
changed after the copy looks fine until a study reads it. So each side writes a
manifest (every file's size and SHA-256, and each DuckDB table's row count), and the
two manifests are compared. Nothing on the laptop is deleted until they match.

    # on each side, from the repo folder
    .venv/bin/python cloud/verify_copy.py manifest data db -o manifest.json
    # then, with both manifests on one machine
    .venv/bin/python cloud/verify_copy.py compare laptop.json server.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

SKIP_NAMES = {".DS_Store"}
SKIP_SUFFIXES = (".partial", ".wal")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tables(path: Path) -> dict[str, int]:
    """Row count per table of one DuckDB file, opened read-only."""
    import duckdb
    con = duckdb.connect(str(path), read_only=True)
    try:
        names = [r[0] for r in con.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
        return {n: con.execute(f'SELECT count(*) FROM {".".join(chr(34) + p + chr(34) for p in n.split("."))}').fetchone()[0]
                for n in names}
    finally:
        con.close()


def manifest(roots: list[Path], base: Path) -> dict:
    """{'files': {relative path: [size, sha256]}, 'tables': {db path: {table: rows}}}."""
    files: dict[str, list] = {}
    tables: dict[str, dict] = {}
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name in SKIP_NAMES or p.name.endswith(SKIP_SUFFIXES):
                continue
            rel = p.relative_to(base).as_posix()
            files[rel] = [p.stat().st_size, _sha256(p)]
            if p.suffix == ".duckdb":
                tables[rel] = _tables(p)
    return {"files": files, "tables": tables}


def compare(a: dict, b: dict) -> dict[str, list]:
    """What differs between two manifests. Empty lists everywhere means a match."""
    fa, fb = a["files"], b["files"]
    out = {
        "missing": sorted(set(fa) - set(fb)),
        "extra": sorted(set(fb) - set(fa)),
        "different": sorted(k for k in set(fa) & set(fb) if fa[k] != fb[k]),
        "table_rows": [],
    }
    for db in sorted(set(a["tables"]) | set(b["tables"])):
        ta, tb = a["tables"].get(db, {}), b["tables"].get(db, {})
        for t in sorted(set(ta) | set(tb)):
            if ta.get(t) != tb.get(t):
                out["table_rows"].append(f"{db} {t}: {ta.get(t)} vs {tb.get(t)}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest")
    m.add_argument("roots", nargs="+")
    m.add_argument("-o", "--out", required=True)
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    args = ap.parse_args()
    if args.cmd == "manifest":
        base = Path.cwd()
        man = manifest([base / r for r in args.roots], base)
        Path(args.out).write_text(json.dumps(man))
        size = sum(v[0] for v in man["files"].values())
        print(f"  manifest: {len(man['files']):,} files, {size / 1e9:.1f} GB, "
              f"{sum(len(t) for t in man['tables'].values())} tables -> {args.out}")
        return 0
    diff = compare(json.loads(Path(args.a).read_text()), json.loads(Path(args.b).read_text()))
    bad = {k: v for k, v in diff.items() if v}
    if not bad:
        print("  compare: the two copies match, file for file")
        return 0
    for k, v in bad.items():
        print(f"  compare: {len(v):,} {k}")
        for x in v[:10]:
            print(f"    {x}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

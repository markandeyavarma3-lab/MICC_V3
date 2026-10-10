"""mf_portfolios.py — every fund house's monthly portfolio files, as served.

WHY (2026-10-10). Part D of the site plan: which mutual-fund schemes hold a
stock, how much, month by month (src/ingest/mf_portfolios.py says why the
shareholding filings are not enough). SEBI makes each fund house publish its
schemes' month-end portfolios on its own website within ten days; AMFI only
links to those pages. There is no central file.

HOW THE FILES ARE FOUND. Most of the pages build their download lists in
JavaScript, so a plain fetch sees no links. Each source in
configs/mf_sources.yml names a page; the page is rendered in the installed
Google Chrome through Playwright, and the candidate files are
  links   the page's <a href>s that match the source's pattern, or
  api     file paths inside the JSON the page itself fetched (ICICI's
          download list is an API the browser may call and curl may not).
The month of each candidate is read from its URL or link text; candidates
older than --months are left alone. Each file is downloaded once (by URL),
through the same browser context, so a site's cookies and referer travel
with it.

WHAT IS NOT DONE. Kotak's site answers automated browsers with a bot-check
page (Radware, measured 2026-10-10); that is a refusal and it is respected,
not worked around. A fund house missing from the config is missing from the
data, and the site says which houses are covered.

ITS OWN MANIFEST (ARCHIVE/MF/manifest.jsonl), like the results archive:
these are filings, not sessions.

    RESEARCH_ENV=prod .venv/bin/python -m src.archive.mf_portfolios                # every source, last 3 months
    RESEARCH_ENV=prod .venv/bin/python -m src.archive.mf_portfolios --only SBI --months 13
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import unquote, urljoin

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.common.paths import ARCHIVE, CONFIGS  # noqa: E402
from src.ingest.mf_portfolios import parse_date  # noqa: E402

ROOT_DIR = ARCHIVE / "MF"
MANIFEST = ROOT_DIR / "manifest.jsonl"
SOURCES = CONFIGS / "mf_sources.yml"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0 Safari/537.36")
FILE = re.compile(r"""[^"'\s<>]*?\.(?:xlsx?|xlsb|zip)(?:\?[^"'\s<>]*)?""", re.I)
JSON_FILE = re.compile(r'"([^"]+?\.(?:xlsx?|xlsb|zip)(?:\?[^"]*)?)"', re.I)
_MON = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON_RX = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|apirl|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"


def record(entry: dict, manifest: Path | None = None) -> None:
    manifest = manifest or MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def stored_urls(manifest: Path | None = None) -> set[str]:
    manifest = manifest or MANIFEST
    out: set[str] = set()
    if manifest.exists():
        for ln in manifest.read_text().splitlines():
            try:
                r = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "file" and r.get("status") in ("STORED", "DUPLICATE"):
                out.add(r["url"])
    return out


def month_of(text: str) -> str | None:
    """'YYYY-MM' named by a file URL or link text, or None. Measured forms:
    'as-on-30th-september-2026', '30-Sep-26', '2026/Sep/', 'sept2026',
    'july-2020', 'dec12', '30092026', '30-09-2026'."""
    t = unquote(text)
    d = parse_date(t)
    if d:
        return f"{d.year:04d}-{d.month:02d}"
    low = t.lower()
    # 'Feb_26_8ad9' (Old Bridge) is a year; 'December_31_2025' is a day, told
    # apart by the four-digit year that follows the day.
    for sep, yr in ((r"[\s_\-./]*'?", r"(20\d{2})"), (r"[\s_\-./]*'?", r"(\d{2})(?![\s_\-./,]*(?:19|20)\d{2}(?![0-9a-z]))")):
        m = re.search(r"(?<![a-z])" + _MON_RX + sep + yr + r"(?!\d)", low)
        if m:
            y = int(m.group(2)) + (2000 if len(m.group(2)) == 2 else 0)
            return f"{y:04d}-{_MON[m.group(1)[:3].replace('api', 'apr')]:02d}"
    m = re.search(r"(\d{4})[/_\-]" + _MON_RX + r"(?![a-z])", low)
    if m:
        return f"{int(m.group(1)):04d}-{_MON[m.group(2)[:3].replace('api', 'apr')]:02d}"
    m = re.search(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)", low)                 # 30092026 (ABSL)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(3)}-{m.group(2)}"
    return None


def candidates(src: dict, links: list[tuple[str, str]], blobs: list[str], months: int,
               today: date | None = None) -> list[dict]:
    """The files to fetch for one source. Pure, so the choice is testable:
    links are (href, text) pairs from the page, blobs the JSON bodies it fetched."""
    today = today or datetime.now(UTC).date()
    lo = (today.year * 12 + today.month - 1) - months
    inc = re.compile(src.get("match", r"portfolio"), re.I)
    exc = re.compile(src.get("exclude", r"fortnight|half[- ]?year|debt|aaum|factsheet|riskometer|risk-o-meter"), re.I)
    base = src.get("base") or src["page"]
    found: dict[str, str] = {}
    for href, text in links:
        if FILE.fullmatch(href or "") and inc.search(href + " " + text) and not exc.search(href + " " + text):
            found.setdefault(href, text)
    if src.get("mode") == "api":
        for body in blobs:
            # Whole JSON strings: ICICI's paths have spaces in them.
            for f in JSON_FILE.findall(body.replace("\\/", "/")):
                f = f.replace(" ", "%20")
                u = base.rstrip("/") + f if f.startswith("/") and src.get("base") else urljoin(base, f)
                if inc.search(u) and not exc.search(u):
                    found.setdefault(u, "")
    out = []
    for u, text in found.items():
        m = month_of(u) or month_of(text)
        if m and (int(m[:4]) * 12 + int(m[5:]) - 1) > today.year * 12 + today.month - 1:
            m = None                                   # a month not yet over is a misread, never a file
        if m is None and src.get("undated"):
            # Invesco names files by a hash: the page lists the current month
            # only, each URL is fetched once, and the file's own title dates it.
            m = "undated"
        elif m is None or (int(m[:4]) * 12 + int(m[5:]) - 1) < lo:
            continue
        out.append({"url": u, "month": m, "text": text[:120]})
    return sorted(out, key=lambda c: (c["month"], c["url"]), reverse=True)


def _render(ctx, src: dict) -> tuple[list[tuple[str, str]], list[str]]:
    page = ctx.new_page()
    resp: list = []
    page.on("response", lambda r: resp.append(r) if r.request.resource_type in ("xhr", "fetch") else None)
    try:
        page.goto(src["page"], wait_until="networkidle", timeout=45000)
    except Exception:  # noqa: BLE001 - a page that never goes idle still has its links
        pass
    page.wait_for_timeout(src.get("wait_ms", 3000))
    for c in src.get("clicks", []):
        try:
            page.get_by_text(re.compile(c, re.I)).first.click(timeout=6000)
            page.wait_for_timeout(3500)
        except Exception:  # noqa: BLE001
            pass
    links: list = []
    # A paginated list (Mirae: ten files a page) is walked by its Next control.
    for _ in range(src.get("max_pages", 1)):
        try:
            links += page.eval_on_selector_all("a", "as => as.map(a => [a.href, (a.innerText || '').trim()])")
        except Exception:  # noqa: BLE001
            break
        if not src.get("next"):
            break
        try:
            page.get_by_text(re.compile(src["next"], re.I)).first.click(timeout=4000)
            page.wait_for_timeout(1500)
        except Exception:  # noqa: BLE001 - the last page has no Next
            break
    blobs = []
    if src.get("mode") == "api":
        rx = re.compile(src.get("api", "."), re.I)
        for r in resp[:300]:
            if rx.search(r.url) and "json" in (r.headers.get("content-type") or ""):
                try:
                    blobs.append(r.text())
                except Exception:  # noqa: BLE001
                    continue
    page.close()
    return [(h, t) for h, t in links if h], blobs


def _save(amc: str, month: str, url: str, body: bytes) -> tuple[str, Path]:
    digest = hashlib.sha256(body).hexdigest()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", unquote(url.split("?")[0].rsplit("/", 1)[-1]))[-80:]
    dest = ROOT_DIR / amc / month / f"{digest[:8]}_{name}.gz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        tmp = dest.with_suffix(".partial")
        tmp.write_bytes(gzip.compress(body))
        tmp.rename(dest)
    return digest, dest


def load_sources() -> list[dict]:
    import yaml
    return yaml.safe_load(SOURCES.read_text())["sources"]


def _one_source(src: dict, months: int, max_files: int, deadline: float, q) -> None:
    """One fund house, in its own process: render, choose, download. Puts
    (candidates, files, skipped, failed) on `q`."""
    from playwright.sync_api import sync_playwright
    have = stored_urls()
    seen_digest: set[str] = set()
    n = [0, 0, 0, 0]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(user_agent=UA, accept_downloads=False)
        try:
            links, blobs = _render(ctx, src)
            cands = candidates(src, links, blobs, months)
            record({"kind": "listing", "amc": src["amc"], "page": src["page"], "status": "STORED",
                    "links": len(links), "candidates": len(cands), "fetched_at": datetime.now(UTC).isoformat()})
        except Exception as e:  # noqa: BLE001
            record({"kind": "listing", "amc": src["amc"], "page": src["page"], "status": "FAILED",
                    "error": str(e)[:200], "fetched_at": datetime.now(UTC).isoformat()})
            q.put((0, 0, 0, 1))
            return
        n[0] = len(cands)
        for c in cands:
            if c["url"] in have:
                n[2] += 1
                continue
            if n[1] >= max_files or time.time() > deadline:
                break
            base = {"kind": "file", "amc": src["amc"], "month": c["month"], "url": c["url"],
                    "fetched_at": datetime.now(UTC).isoformat()}
            try:
                r = ctx.request.get(c["url"], headers={"Referer": src["page"]}, timeout=120000)
                body = r.body()
                if r.status != 200 or len(body) < 2000 or body[:2] not in (b"PK", b"\xd0\xcf"):
                    raise ValueError(f"HTTP {r.status}, {len(body)} bytes, not a spreadsheet")
                digest, dest = _save(src["amc"], c["month"], c["url"], body)
                status = "DUPLICATE" if digest in seen_digest else "STORED"
                seen_digest.add(digest)
                record({**base, "status": status, "sha256": digest, "bytes": len(body), "path": str(dest)})
                n[1] += 1
            except Exception as e:  # noqa: BLE001
                record({**base, "status": "FAILED", "error": str(e)[:200]})
                n[3] += 1
            time.sleep(src.get("rate", 0.7))
        browser.close()
    q.put(tuple(n))


def collect(only: list[str] | None = None, months: int = 3, max_files: int = 400,
            max_minutes: float = 60) -> dict:
    """Every source, each in its own process under a deadline. A page whose
    script blocks the browser (HSBC, 2026-10-10: eight idle minutes, no
    timeout fired) then costs one source, not the night."""
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    t0 = time.monotonic()
    st = {"sources": 0, "candidates": 0, "files": 0, "failed": 0, "skipped": 0, "by_amc": {}}
    for src in load_sources():
        if only and src["amc"] not in only or src.get("disabled"):
            continue
        left = max_minutes * 60 - (time.monotonic() - t0)
        if left <= 0 or st["files"] >= max_files:
            st["stopped"] = "time cap" if st["files"] < max_files else "file budget"
            break
        st["sources"] += 1
        limit = min(left, src.get("timeout_s", 600))
        q = ctx.Queue()
        proc = ctx.Process(target=_one_source, args=(src, months, max_files - st["files"], time.time() + limit - 30, q))
        proc.start()
        proc.join(limit)
        if proc.is_alive():
            proc.kill()
            proc.join()
            record({"kind": "listing", "amc": src["amc"], "page": src["page"], "status": "FAILED",
                    "error": f"no result in {limit:.0f} s; stopped", "fetched_at": datetime.now(UTC).isoformat()})
            st["failed"] += 1
            st["by_amc"][src["amc"]] = ("timeout", 0)
            continue
        cands, files, skipped, failed = q.get() if not q.empty() else (0, 0, 0, 1)
        st["candidates"] += cands
        st["files"] += files
        st["skipped"] += skipped
        st["failed"] += failed
        st["by_amc"][src["amc"]] = (cands, files)
    return st


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated source keys")
    ap.add_argument("--months", type=int, default=3, help="how many months back to fetch")
    ap.add_argument("--max-files", type=int, default=400)
    ap.add_argument("--max-minutes", type=float, default=60)
    a = ap.parse_args()
    st = collect([s.strip().upper() for s in a.only.split(",") if s.strip()] or None, a.months, a.max_files,
                 a.max_minutes)
    print(f"  MF: {st['sources']} sources, {st['candidates']} candidate files, {st['files']} stored, "
          f"{st['skipped']} already held, {st['failed']} failed{'; stopped: ' + st['stopped'] if st.get('stopped') else ''}")
    for amc, (n, g) in sorted(st["by_amc"].items()):
        print(f"    {amc:<12} {n!s:>7} candidates  {g:>4} new")
    return 0 if st["files"] or not st["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

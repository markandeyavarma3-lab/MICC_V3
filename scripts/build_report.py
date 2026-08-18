#!/usr/bin/env python3
"""build_report.py — compile the project report from Markdown to a PDF.

WHY THIS EXISTS AS A SCRIPT AND NOT A ONE-OFF EXPORT. The report makes factual
claims about a live system — row counts, test counts, dates, defect numbers. A
report produced by hand drifts from the system the moment either changes, and
then it is a document that asserts things nothing checks. Same defect class this
whole project was built to eliminate. Keeping the source in Markdown under
version control and the PDF a build artefact means the claims can be re-derived,
diffed, and regenerated after any change.

TOOLCHAIN. Deliberately minimal, because this machine has no Homebrew, no LaTeX
and no pandoc, and spent 2026-08-06..10 unable to resolve DNS:

    Markdown  --python-markdown-->  HTML  --headless Chrome-->  PDF

Chrome is already installed at the standard macOS path; puppeteer-core drives it
without downloading its own Chromium. mermaid.min.js is VENDORED rather than
pulled from a CDN at build time, so the report still builds with no network.

    python scripts/build_report.py                  # build the default report
    python scripts/build_report.py --no-pdf         # HTML only (fast iteration)
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "docs" / "report"
BUILD = REPORT_DIR / "build"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

DEFAULT_SRC = REPORT_DIR / "PROJECT_REPORT.md"


CSS = """
@page { size: A4; }
* { box-sizing: border-box; }
body {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 10.8pt; line-height: 1.5; color: #14181f; margin: 0;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}
h1, h2, h3, h4 { font-family: "Helvetica Neue", Arial, sans-serif; color: #0d1117;
  line-height: 1.25; page-break-after: avoid; }
h1 { font-size: 19pt; margin: 0 0 14px; padding-bottom: 7px;
     border-bottom: 2.5px solid #14181f; page-break-before: always; }
h1.nobreak { page-break-before: avoid; }
h2 { font-size: 13.5pt; margin: 22px 0 8px; }
h3 { font-size: 11.5pt; margin: 16px 0 6px; }
h4 { font-size: 10.8pt; margin: 13px 0 5px; font-style: italic; font-weight: 600; }
p { margin: 0 0 9px; text-align: justify; hyphens: auto; }
ul, ol { margin: 0 0 10px; padding-left: 20px; }
li { margin-bottom: 3px; }
strong { color: #000; }
code { font-family: "SF Mono", Menlo, monospace; font-size: 9pt;
       background: #f2f4f7; padding: 1px 4px; border-radius: 3px; }
pre { background: #f7f8fa; border: 1px solid #dfe3e8; border-left: 3px solid #55606e;
      padding: 9px 11px; font-size: 8.6pt; line-height: 1.42; overflow-x: hidden;
      white-space: pre-wrap; word-wrap: break-word; page-break-inside: avoid;
      margin: 0 0 11px; border-radius: 2px; }
pre code { background: none; padding: 0; font-size: inherit; }
table { border-collapse: collapse; width: 100%; margin: 0 0 13px;
        font-size: 9.2pt; page-break-inside: avoid; }
th { background: #eef1f5; text-align: left; font-weight: 600;
     font-family: "Helvetica Neue", Arial, sans-serif; font-size: 8.8pt; }
th, td { border: 1px solid #c7ced8; padding: 4.5px 7px; vertical-align: top; }
tbody tr:nth-child(even) { background: #fafbfc; }
blockquote { margin: 0 0 12px; padding: 8px 13px; background: #f6f8fa;
             border-left: 3px solid #8a94a3; font-size: 10pt; }
blockquote p:last-child { margin-bottom: 0; }
hr { border: none; border-top: 1px solid #d4dae2; margin: 18px 0; }
a { color: #14181f; text-decoration: none; }
/* Mermaid blocks arrive as <pre class="mermaid">, so they inherit the code-block
   background, border and left rule. That drew a grey slab around every diagram.
   Reset them completely — a diagram is a figure, not a listing. */
pre.mermaid, .mermaid {
  background: none; border: none; padding: 0; margin: 14px 0 6px;
  text-align: center; page-break-inside: avoid; overflow: visible;
}
/* No diagram may exceed the printable height of one page, or it is silently
   clipped by the paginator with no error anywhere. */
.mermaid svg { max-width: 100%; max-height: 195mm; height: auto; }
figcaption, p.caption, .caption {
  font-size: 8.6pt; color: #5b6572; text-align: center; hyphens: none;
  margin: 0 auto 16px; max-width: 88%; font-style: italic; line-height: 1.4;
  page-break-before: avoid;
}
.toc { font-size: 10pt; }
.toc a { display: block; padding: 2.5px 0; border-bottom: 1px dotted #dde2e8; }
.toc .l2 { padding-left: 17px; font-size: 9.4pt; color: #3d4653; }
"""


def md_to_html(md: str) -> str:
    """Markdown -> HTML body, with mermaid fences preserved as live diagrams."""
    import markdown as md_lib

    blocks: list[str] = []

    def stash(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}ENDBLOCK\n\n"

    md = re.sub(r"```mermaid\n(.*?)```", stash, md, flags=re.S)

    html = md_lib.markdown(
        md, extensions=["tables", "fenced_code", "attr_list", "toc", "sane_lists"]
    )

    for i, code in enumerate(blocks):
        html = html.replace(
            f"<p>MERMAIDBLOCK{i}ENDBLOCK</p>", f'<pre class="mermaid">{code}</pre>'
        )
    return html


def build_toc(html: str) -> str:
    """Contents list from the h1/h2 the document already declares."""
    rows = []
    seen_title = False
    for m in re.finditer(r"<h([12])[^>]*>(.*?)</h\1>", html):
        level, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if level == "1" and not seen_title:
            seen_title = True          # the document's own title is not a section
            continue
        if text.lower().startswith(("contents", "table of contents")):
            continue
        cls = "" if level == "1" else "l2"
        rows.append(f'<a class="{cls}">{text}</a>')
    return '<div class="toc">' + "".join(rows) + "</div>"


def wrap(body: str, title: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<style>{CSS}</style>
<script src="mermaid.min.js"></script>
</head><body>
{body}
<script>
mermaid.initialize({{startOnLoad: true, theme: 'neutral',
  themeVariables: {{fontFamily: 'Helvetica Neue, Arial, sans-serif', fontSize: '13px'}},
  flowchart: {{curve: 'basis', useMaxWidth: true}} }});
</script>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    src = Path(argv[argv.index("--src") + 1]) if "--src" in argv else DEFAULT_SRC
    if not src.exists():
        print(f"REPORT BUILD: no source at {src}")
        return 1

    BUILD.mkdir(parents=True, exist_ok=True)
    text = src.read_text()

    title = next((l.lstrip("# ").strip() for l in text.splitlines()
                  if l.startswith("# ")), src.stem)

    body = md_to_html(text)
    if "<!--TOC-->" in body or "&lt;!--TOC--&gt;" in body:
        toc = build_toc(body)
        body = body.replace("<p>&lt;!--TOC--&gt;</p>", toc).replace("<!--TOC-->", toc)

    html_path = BUILD / (src.stem + ".html")
    html_path.write_text(wrap(body, title))
    print(f"  html  {html_path.relative_to(ROOT)}  ({len(body):,} chars)")

    if "--no-pdf" in argv:
        print("REPORT BUILD: HTML ONLY")
        return 0

    if not Path(CHROME).exists():
        print(f"REPORT BUILD: FAILED — Chrome not found at {CHROME}")
        return 1
    if not (BUILD / "node_modules").exists():
        print("  installing puppeteer-core ...")
        subprocess.run(["npm", "install", "puppeteer-core"], cwd=BUILD,
                       capture_output=True, timeout=300)

    # Output beside the SOURCE, not in a hardcoded directory. Building the four
    # plan documents on 2026-08-18 silently dropped all four PDFs into
    # docs/report/ while the stale copies sat in docs/plan/pdf/ — so the build
    # reported GREEN and the stale files were what anyone would still have read.
    src_abs = src.resolve()
    out_dir = (src_abs.parent / "pdf") if src_abs.parent.name == "plan" else src_abs.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / (src.stem + ".pdf")
    r = subprocess.run(["node", str(BUILD / "render.js"), str(html_path), str(pdf_path)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        print(f"REPORT BUILD: FAILED — {r.stderr.strip()[:300]}")
        return 1

    size = pdf_path.stat().st_size
    print(f"  pdf   {pdf_path.relative_to(ROOT)}  ({size:,} bytes)")
    print("REPORT BUILD: GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface.

    pid-scan scan drawing.pdf
    pid-scan scan drawing.pdf --preset thorough --pages 1,3 -o out/
    pid-scan serve --port 8000
    pid-scan sample fixture.pdf
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .report import render_html, render_json, render_markdown
from .scan import ScanConfig, scan_pdf
from .tags import load_conventions
from .vision import DEFAULT_MODEL, RefusalError, Scanner


def _parse_pages(spec: Optional[str]) -> Optional[List[int]]:
    """Parse a page spec like ``1,3,5-8``."""
    if not spec:
        return None
    pages: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            pages.extend(range(int(lo), int(hi) + 1))
        else:
            pages.append(int(part))
    return sorted(set(pages))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pid-scan",
        description="Read a P&ID PDF and report every component, loop and stream on it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="scan a P&ID PDF")
    scan.add_argument("pdf", help="path to the P&ID PDF")
    scan.add_argument("-o", "--out", default=None,
                      help="output directory (default: alongside the PDF)")
    scan.add_argument("-f", "--format", default="html,md,json",
                      help="comma separated: html, md, json (default: all three)")
    scan.add_argument("--preset", default="balanced",
                      choices=["fast", "balanced", "thorough"],
                      help="how carefully to read the sheet (default: balanced)")
    scan.add_argument("--pages", default=None, help="pages to scan, e.g. 1,3,5-8")
    scan.add_argument("--dpi", type=int, default=None, help="override render DPI")
    scan.add_argument("--tile-px", type=int, default=None, help="override tile size in pixels")
    scan.add_argument("--overlap", type=float, default=None, help="override tile overlap (0-0.5)")
    scan.add_argument("--max-tiles", type=int, default=None, help="cap tiles per page")
    scan.add_argument("--concurrency", type=int, default=None, help="parallel tile requests")
    scan.add_argument("--model", default=DEFAULT_MODEL, help=f"model id (default: {DEFAULT_MODEL})")
    scan.add_argument("--min-confidence", type=float, default=0.0,
                      help="drop detections below this confidence (default: keep all)")
    scan.add_argument("--no-synthesis", action="store_true",
                      help="inventory only - skip the process narrative pass")
    scan.add_argument("--conventions", default=None,
                      help="JSON file of site-specific tag prefixes")
    scan.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")

    serve = sub.add_parser("serve", help="run the upload web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--model", default=DEFAULT_MODEL)

    sample = sub.add_parser("sample", help="write a synthetic P&ID for testing")
    sample.add_argument("out", nargs="?", default="sample_pid.pdf")

    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"error: {pdf} not found", file=sys.stderr)
        return 2

    overrides = {k: v for k, v in (
        ("dpi", args.dpi), ("tile_px", args.tile_px), ("overlap", args.overlap),
        ("max_tiles", args.max_tiles), ("concurrency", args.concurrency),
    ) if v is not None}

    config = ScanConfig.preset(args.preset, **overrides)
    config.pages = _parse_pages(args.pages)
    config.synthesize = not args.no_synthesis
    config.min_confidence = args.min_confidence
    config.conventions = load_conventions(args.conventions)

    say = (lambda m: None) if args.quiet else (lambda m: print(f"  {m}", file=sys.stderr))

    try:
        scanner = Scanner(model=args.model, concurrency=config.concurrency)
    except Exception as exc:  # missing credentials is the usual cause
        print(f"error: could not create the Claude client: {exc}", file=sys.stderr)
        print("Set ANTHROPIC_API_KEY, or run `ant auth login`.", file=sys.stderr)
        return 2

    images: Dict[int, bytes] = {}
    try:
        drawing = scan_pdf(pdf, scanner, config, progress=say, images=images)
    except RefusalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: scan failed: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.out) if args.out else pdf.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf.stem
    formats = {f.strip().lower() for f in args.format.split(",") if f.strip()}
    written: List[Path] = []

    if "json" in formats:
        path = out_dir / f"{stem}.pid.json"
        path.write_text(render_json(drawing))
        written.append(path)
    if "md" in formats or "markdown" in formats:
        path = out_dir / f"{stem}.pid.md"
        path.write_text(render_markdown(drawing))
        written.append(path)
    if "html" in formats:
        path = out_dir / f"{stem}.pid.html"
        path.write_text(render_html(drawing, images))
        written.append(path)

    stats = drawing.stats
    usage = stats.get("usage", {})
    print(f"\n{pdf.name}: {stats.get('components', 0)} components "
          f"({stats.get('tagged', 0)} tagged), "
          f"{stats.get('control_loops', 0)} control loops, "
          f"{len(stats.get('line_numbers', []))} line numbers")
    for kind, n in stats.get("by_kind", {}).items():
        print(f"  {kind:16} {n}")
    if usage:
        print(f"\n{usage.get('calls', 0)} API calls, ~${usage.get('estimated_usd', 0):.2f}")
    for path in written:
        print(f"wrote {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    uvicorn.run(create_app(model=args.model), host=args.host, port=args.port)
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
    from make_sample_pid import build

    build(args.out)
    print(f"wrote {args.out}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return {"scan": cmd_scan, "serve": cmd_serve, "sample": cmd_sample}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

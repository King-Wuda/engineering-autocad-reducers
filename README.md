# pid-scan

Read a P&ID PDF with Claude and get back an inventory of everything on it —
vessels, pumps, compressors, heat exchangers and coolers, valves, instruments,
control loops and line numbers — plus a written description of what the drawing
shows.

Works on drawings tagged to ISA-5.1 (`P-101A`, `FIC-1010`) and on European /
OEM drawings tagged to IEC 81346 (`=Q1`, `=A2A5`, `=P1P1`), with imperial
(`6"-P-1201-A1A-HC`) or metric (`RR-125-A14.510-002`) line numbering.

```bash
pip install -e ".[web]"
export ANTHROPIC_API_KEY=sk-ant-...

pid-scan scan drawing.pdf          # writes drawing.pid.html, .md and .json
pid-scan serve                     # upload UI at http://127.0.0.1:8000
```

## Why it is built this way

A P&ID is an A0 or E-size sheet. Handed to a vision model whole, it is
downsampled until a 3 mm valve symbol is a few pixels across and the tag text
is unreadable. So the sheet is cut into **overlapping tiles** sized to land
just under the API's internal image-resize threshold, each tile is read at full
resolution, and the results are merged back into one page inventory.

The second idea matters more. A P&ID exported from AutoCAD carries **every tag
as real text with exact coordinates**. Extracting that costs nothing and
removes OCR guesswork entirely: the model is handed the exact strings in its
tile and only has to decide which symbol each one belongs to. Tags are then
decoded deterministically against ISA-5.1 — `FIC-1010` is a Flow Indicating
Controller on loop `F1010` because the standard says so, not because a model
inferred it.

That also gives a free quality check. The text layer is ground truth for which
tags are printed, so any tag it contains that no component ended up carrying is
flagged in the report as something the scan may have missed.

## What you get

| Output | Use |
|---|---|
| `*.pid.html` | Self-contained report: the drawing with every detection boxed on it, click-to-cross-reference inventory, loops, narrative, findings. Emailable. |
| `*.pid.md` | Same content as text, for a PR, an email or a ticket. |
| `*.pid.json` | The full structured result — every component with tag, type, subtype, actuator, fail position, page coordinates and confidence. |

Each component carries two honesty signals: `confidence` (the model's own) and
`detections` (how many overlapping tiles independently found it). Two or more
detections is strong corroboration; one detection at low confidence is worth a
look by eye.

## Options

```
pid-scan scan drawing.pdf \
  --preset thorough \          # fast | balanced (default) | thorough
  --pages 1,3,5-8 \
  --conventions site.json \    # your plant's tag prefixes
  --no-synthesis \             # inventory only, skip the narrative
  --min-confidence 0.4
```

Presets trade resolution against cost. On an A0 sheet: `fast` is 20 tiles,
`balanced` 30, `thorough` 70. The report prints the actual token usage and an
estimated cost for the run.

### Site tag conventions

Every owner-operator tags differently. `conventions.example.json` shows the
shape; pass it with `--conventions`:

```json
{
  "equipment_prefixes": {"OS": {"kind": "vessel", "desc": "Oil Separator"}},
  "stop_prefixes": ["CPI", "WR"]
}
```

`stop_prefixes` is for strings that look like tags but are not — `DN15` is a
nominal diameter, `CPI-40` is a valve product code.

## Limitations — read this before trusting it

- **Symbol recognition and tag reading are the strong parts.** Both are
  corroborated: symbols by overlapping tiles, tags by the PDF text layer.
- **Cross-sheet pipe tracing is the weak part.** Each tile is read
  independently, so a line running the width of the sheet is seen in pieces.
  Connectivity and the process narrative are a well-informed first read, not a
  verified line list. Line *numbers* are exact — they come from the text layer.
- **Scanned (raster) drawings degrade.** With no text layer every tag is read
  by vision alone, and the report says so at the top of the run.
- This is a drafting and review aid. It does not replace a P&ID review by a
  qualified engineer.

## Development

```bash
pip install -e ".[web,dev]"
pytest                             # 65 tests, no API key needed
python tools/make_sample_pid.py s.pdf   # synthetic P&ID fixture
```

The test suite runs the whole pipeline offline through a fake scanner that
fabricates tile results from the PDF text layer, so tiling, coordinate mapping,
overlap de-duplication, tag reconciliation, loop derivation and report
rendering are all covered without spending credits.

## Layout

| File | Role |
|---|---|
| `pid_scan/pdfdoc.py` | PDF loading, tiling, text-layer extraction |
| `pid_scan/tags.py` | ISA-5.1 and IEC 81346 tag parsing, line numbers |
| `pid_scan/prompts.py` | The domain knowledge — symbol conventions, in plain text |
| `pid_scan/vision.py` | The two Claude passes: per-tile extraction, page synthesis |
| `pid_scan/merge.py` | Reconciling overlapping tile results into one inventory |
| `pid_scan/scan.py` | Pipeline orchestration, loop derivation, statistics |
| `pid_scan/report.py` | HTML / Markdown / JSON rendering |
| `pid_scan/server.py` | Upload web UI |

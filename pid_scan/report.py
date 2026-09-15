"""Render a :class:`Drawing` as HTML, Markdown or JSON.

The HTML report is the one people actually use: the drawing on the left with
every detection boxed on it, the inventory on the right, and clicking either
one highlights the other. Being able to see *where* on the sheet a component
was found is what makes the output checkable rather than something you have to
take on faith.

It is a single self-contained file - image inlined, no network - so it can be
emailed to someone who does not have the tool installed.
"""

from __future__ import annotations

import base64
import html
import json
from collections import Counter
from typing import Dict, List, Optional

from .schema import Component, Drawing, Page
from .tags import find_component_tags

#: Component families for the overlay. Three colour slots, because boxes on a
#: drawing sit in arbitrary adjacency (the all-pairs case), and only the first
#: three slots of the validated categorical palette clear the colour-vision
#: floors under all-pairs. Everything else folds into a neutral "other".
FAMILIES = {
    "vessel": "equipment", "heat_exchanger": "equipment", "driver": "equipment",
    "equipment_other": "equipment", "pump": "equipment", "compressor": "equipment",
    "inline_device": "equipment",
    "valve": "valve",
    "instrument": "instrument",
    "connector": "other",
}

FAMILY_LABEL = {
    "equipment": "Equipment",
    "valve": "Valves",
    "instrument": "Instruments",
    "other": "Other",
}

KIND_LABEL = {
    "vessel": "Vessel", "pump": "Pump", "compressor": "Compressor",
    "heat_exchanger": "Heat exchanger", "driver": "Driver", "valve": "Valve",
    "instrument": "Instrument", "inline_device": "Inline device",
    "connector": "Off-page connector", "equipment_other": "Other equipment",
}


def family(kind: str) -> str:
    return FAMILIES.get(kind, "other")


def _esc(value) -> str:
    # Not `value or ""` - that renders a real count of 0 as a blank tile.
    return html.escape("" if value is None else str(value), quote=True)


def missed_tags(page: Page) -> List[str]:
    """Tags the sheet's text layer proves exist, that no component carries.

    The single most useful quality check available: the text layer is ground
    truth for what tags are printed, so anything here is either a component the
    vision pass missed or a reference to something on another sheet.
    """
    found = {c.tag.upper() for c in page.components if c.tag}
    candidates = set(page.text_tags)
    if not candidates:  # older results, or a page with no text layer
        text = " ".join(page.texts)
        candidates = {t.normalized for t in find_component_tags(text)}
    return sorted(c for c in candidates if c.upper() not in found)


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def render_json(drawing: Drawing) -> str:
    return drawing.model_dump_json(indent=2)


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def render_markdown(drawing: Drawing) -> str:
    out: List[str] = []
    stats = drawing.stats
    out.append(f"# P&ID scan - {drawing.source}\n")
    out.append(f"*{stats.get('components', 0)} components across "
               f"{stats.get('pages', 0)} page(s), scanned {drawing.scanned_at} "
               f"with {drawing.model}*\n")

    for page in drawing.pages:
        a = page.analysis
        out.append(f"\n## Page {page.number}"
                   + (f" - {a.title}" if a.title else ""))
        if a.drawing_number:
            out.append(f"\n**Drawing:** {a.drawing_number}"
                       + (f"  **Rev:** {a.revision}" if a.revision else ""))
        if a.summary:
            out.append(f"\n{a.summary}\n")
        if a.process_description:
            out.append(f"\n### Process\n\n{a.process_description}\n")
        if a.major_streams:
            out.append("\n### Major streams\n")
            out.extend(f"- {s}" for s in a.major_streams)
            out.append("")
        if a.control_narrative:
            out.append(f"\n### Control\n\n{a.control_narrative}\n")
        if a.loops:
            out.append("\n| Loop | Variable | Members | Final element |")
            out.append("|---|---|---|---|")
            for loop in a.loops:
                out.append(f"| {loop.loop_id} | {loop.measured_variable} | "
                           f"{', '.join(loop.members)} | {loop.final_element or '-'} |")
            out.append("")
        if a.safety_narrative:
            out.append(f"\n### Safety\n\n{a.safety_narrative}\n")
        if a.utilities:
            out.append("\n### Utilities\n")
            out.extend(f"- {u}" for u in a.utilities)
            out.append("")

        out.append(f"\n### Components ({len(page.components)})\n")
        out.append("| Tag | Type | Detail | Function | Conf | Seen |")
        out.append("|---|---|---|---|---|---|")
        for c in sorted(page.components, key=lambda c: (family(c.kind), c.tag or "zzz")):
            detail = c.subtype.replace("_", " ") if c.subtype else ""
            if c.actuator not in ("none", "", "unknown"):
                detail += f" / {c.actuator} actuator"
            if c.fail_position:
                detail += f" / {c.fail_position}"
            out.append(f"| {c.tag or '-'} | {KIND_LABEL.get(c.kind, c.kind)} | "
                       f"{detail or '-'} | {c.isa_function or c.label or '-'} | "
                       f"{c.confidence:.2f} | {c.detections} |")

        if a.findings:
            out.append("\n### Findings\n")
            for f in a.findings:
                refs = f" ({', '.join(f.refs)})" if f.refs else ""
                out.append(f"- **{f.severity.upper()}** [{f.category}] {f.message}{refs}")

        missed = missed_tags(page)
        if missed:
            out.append("\n### Tags in the drawing text with no matching component\n")
            out.append(", ".join(missed))

    if stats.get("line_numbers"):
        out.append("\n## Line numbers\n")
        out.extend(f"- `{ln}`" for ln in stats["line_numbers"])

    usage = stats.get("usage", {})
    if usage:
        out.append(f"\n---\n*{usage.get('calls', 0)} API calls, "
                   f"{usage.get('input_tokens', 0):,} in / "
                   f"{usage.get('output_tokens', 0):,} out, "
                   f"~${usage.get('estimated_usd', 0):.2f}*")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

_CSS = """
:root{color-scheme:light;
--surface-0:#f6f6f4;--surface-1:#fcfcfb;--surface-2:#efefec;
--border:#dedcd5;--border-strong:#c4c2b8;
--text-primary:#0b0b0b;--text-secondary:#52514e;--text-muted:#84837c;
--equipment:#2a78d6;--valve:#eb6834;--instrument:#1baf7a;--other:#84837c;
--good:#008300;--warning:#eda100;--critical:#e34948;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--surface-2:#242422;
--border:#35342f;--border-strong:#4b4a43;
--text-primary:#ffffff;--text-secondary:#c3c2b7;--text-muted:#8e8d83;
--equipment:#3987e5;--valve:#d95926;--instrument:#199e70;--other:#8e8d83;
--good:#008300;--warning:#c98500;--critical:#e66767;}}
:root[data-theme="dark"]{color-scheme:dark;
--surface-0:#121211;--surface-1:#1a1a19;--surface-2:#242422;
--border:#35342f;--border-strong:#4b4a43;
--text-primary:#ffffff;--text-secondary:#c3c2b7;--text-muted:#8e8d83;
--equipment:#3987e5;--valve:#d95926;--instrument:#199e70;--other:#8e8d83;
--good:#008300;--warning:#c98500;--critical:#e66767;}

*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
font:14px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1600px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:16px;margin:32px 0 12px;letter-spacing:-.01em}
h3{font-size:13px;margin:20px 0 8px;text-transform:uppercase;
letter-spacing:.06em;color:var(--text-secondary)}
p{margin:0 0 10px;color:var(--text-secondary);max-width:72ch}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.92em}
.sub{color:var(--text-muted);font-size:13px;margin-bottom:20px}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
gap:10px;margin:0 0 24px}
.tile{background:var(--surface-1);border:1px solid var(--border);
border-radius:10px;padding:12px 14px}
.tile .n{font-size:26px;font-weight:600;letter-spacing:-.02em;
font-variant-numeric:tabular-nums;line-height:1.1}
.tile .l{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
color:var(--text-muted);margin-top:4px}

.cols{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:20px;align-items:start}
@media (max-width:1100px){.cols{grid-template-columns:1fr}}

.sheet{position:sticky;top:12px;background:var(--surface-1);
border:1px solid var(--border);border-radius:10px;padding:10px}
.canvas{position:relative;line-height:0}
.canvas img{width:100%;height:auto;border-radius:6px;display:block}
.box{position:absolute;border:2px solid var(--other);border-radius:3px;
cursor:pointer;transition:box-shadow .1s,transform .1s}
.box[data-f="equipment"]{border-color:var(--equipment)}
.box[data-f="valve"]{border-color:var(--valve)}
.box[data-f="instrument"]{border-color:var(--instrument)}
.box:hover,.box.on{box-shadow:0 0 0 2px var(--surface-1),0 0 0 4px currentColor;z-index:5}
.box[data-f="equipment"]{color:var(--equipment)}
.box[data-f="valve"]{color:var(--valve)}
.box[data-f="instrument"]{color:var(--instrument)}
.box.dim{opacity:.12}

.legend{display:flex;flex-wrap:wrap;gap:14px;margin:10px 2px 2px;
font-size:12px;color:var(--text-secondary)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;
margin-right:5px;vertical-align:-1px}

.tip{position:fixed;z-index:50;pointer-events:none;background:var(--surface-1);
border:1px solid var(--border-strong);border-radius:7px;padding:7px 9px;
font-size:12px;max-width:280px;box-shadow:0 6px 20px rgba(0,0,0,.18);display:none}
.tip b{display:block;font-size:13px;margin-bottom:2px}
.tip span{color:var(--text-secondary)}

.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 12px}
.chip{border:1px solid var(--border-strong);background:var(--surface-1);
color:var(--text-secondary);border-radius:999px;padding:4px 11px;font-size:12px;
cursor:pointer;font-family:inherit}
.chip[aria-pressed="true"]{background:var(--text-primary);color:var(--surface-1);
border-color:var(--text-primary)}
.bar input{flex:1;min-width:140px;background:var(--surface-1);color:inherit;
border:1px solid var(--border-strong);border-radius:7px;padding:5px 10px;
font:inherit;font-size:12px}

table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.05em;
color:var(--text-muted);font-weight:600;padding:6px 8px;
border-bottom:1px solid var(--border-strong);position:sticky;top:0;
background:var(--surface-0)}
td{padding:6px 8px;border-bottom:1px solid var(--border);vertical-align:top}
tbody tr{cursor:pointer}
tbody tr:hover{background:var(--surface-2)}
tbody tr.on{background:var(--surface-2);box-shadow:inset 3px 0 0 currentColor}
tr[data-f="equipment"]{color:var(--equipment)}
tr[data-f="valve"]{color:var(--valve)}
tr[data-f="instrument"]{color:var(--instrument)}
tr[data-f="other"]{color:var(--other)}
td,th{color:var(--text-primary)}
td.tag{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:600;
white-space:nowrap}
td.dim{color:var(--text-secondary)}
.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.scroll{max-height:70vh;overflow:auto;border:1px solid var(--border);
border-radius:10px;background:var(--surface-1)}
.scrollx{overflow-x:auto}

.card{background:var(--surface-1);border:1px solid var(--border);
border-radius:10px;padding:14px 16px;margin:0 0 12px}
.find{display:flex;gap:10px;padding:9px 0;border-bottom:1px solid var(--border)}
.find:last-child{border-bottom:0}
.find .sev{flex:none;font-size:10px;font-weight:700;letter-spacing:.06em;
text-transform:uppercase;padding:2px 7px;border-radius:999px;height:fit-content;
border:1px solid currentColor}
.find.warning .sev{color:var(--critical)}
.find.note .sev{color:var(--warning)}
.find.info .sev{color:var(--text-muted)}
.find div{color:var(--text-secondary)}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;
border:1px solid var(--border-strong);color:var(--text-secondary);margin:2px 4px 2px 0}
.lowconf{color:var(--warning)}
.foot{margin-top:40px;padding-top:16px;border-top:1px solid var(--border);
color:var(--text-muted);font-size:12px}
.foot p{color:var(--text-muted);font-size:12px}
"""

_JS = """
(function(){
 const tip=document.getElementById('tip');
 function boxes(){return document.querySelectorAll('.box')}
 function rows(){return document.querySelectorAll('tbody tr[data-id]')}

 function select(id,scroll){
  boxes().forEach(b=>b.classList.toggle('on',b.dataset.id===id));
  rows().forEach(r=>{
   const on=r.dataset.id===id;
   r.classList.toggle('on',on);
   if(on&&scroll)r.scrollIntoView({block:'nearest',behavior:'smooth'});
  });
 }
 function show(e,el){
  tip.innerHTML='<b>'+(el.dataset.tag||'(untagged)')+'</b><span>'+el.dataset.desc+'</span>';
  tip.style.display='block';
  const r=tip.getBoundingClientRect();
  tip.style.left=Math.min(e.clientX+14,innerWidth-r.width-10)+'px';
  tip.style.top=Math.min(e.clientY+14,innerHeight-r.height-10)+'px';
 }
 boxes().forEach(b=>{
  b.addEventListener('mousemove',e=>show(e,b));
  b.addEventListener('mouseleave',()=>tip.style.display='none');
  b.addEventListener('click',()=>select(b.dataset.id,true));
 });
 rows().forEach(r=>{
  r.addEventListener('click',()=>select(r.dataset.id,false));
  r.addEventListener('mousemove',e=>show(e,r));
  r.addEventListener('mouseleave',()=>tip.style.display='none');
 });

 let fam='all',q='';
 function apply(){
  rows().forEach(r=>{
   const okF=fam==='all'||r.dataset.f===fam;
   const okQ=!q||r.dataset.search.includes(q);
   r.hidden=!(okF&&okQ);
  });
  boxes().forEach(b=>{
   const okF=fam==='all'||b.dataset.f===fam;
   const okQ=!q||b.dataset.search.includes(q);
   b.classList.toggle('dim',!(okF&&okQ));
  });
 }
 document.querySelectorAll('.chip[data-fam]').forEach(c=>{
  c.addEventListener('click',()=>{
   fam=c.dataset.fam;
   document.querySelectorAll('.chip[data-fam]').forEach(o=>
     o.setAttribute('aria-pressed',String(o===c)));
   apply();
  });
 });
 const s=document.getElementById('q');
 if(s)s.addEventListener('input',()=>{q=s.value.toLowerCase().trim();apply()});
})();
"""


def _tile(n, label) -> str:
    return f'<div class="tile"><div class="n">{_esc(n)}</div><div class="l">{_esc(label)}</div></div>'


def _component_rows(components: List[Component]) -> str:
    rows = []
    order = {"equipment": 0, "valve": 1, "instrument": 2, "other": 3}
    for c in sorted(components, key=lambda c: (order[family(c.kind)], c.tag or "zzzz")):
        detail = c.subtype.replace("_", " ") if c.subtype else ""
        if c.actuator not in ("none", "", "unknown"):
            detail += f" · {c.actuator}"
        if c.fail_position:
            detail += f" · {c.fail_position}"
        desc = c.isa_function or c.label or c.notes or ""
        conf_cls = " lowconf" if c.confidence < 0.5 else ""
        search = " ".join([c.tag, c.kind, c.subtype, c.label, c.isa_function,
                           c.notes, c.loop]).lower()
        rows.append(
            f'<tr data-id="{_esc(c.id)}" data-f="{family(c.kind)}" data-search="{_esc(search)}"'
            f' data-tag="{_esc(c.tag)}" data-desc="{_esc(KIND_LABEL.get(c.kind, c.kind) + (" · " + desc if desc else ""))}">'
            f'<td class="tag">{_esc(c.tag or "—")}</td>'
            f'<td>{_esc(KIND_LABEL.get(c.kind, c.kind))}</td>'
            f'<td class="dim">{_esc(detail or "—")}</td>'
            f'<td class="dim">{_esc(desc or "—")}</td>'
            f'<td class="num{conf_cls}">{c.confidence:.2f}</td>'
            f'<td class="num dim">{c.detections}</td></tr>'
        )
    return "\n".join(rows)


def _overlay(components: List[Component]) -> str:
    out = []
    for c in components:
        w = max(c.box.x1 - c.box.x0, 4) / 10.0
        h = max(c.box.y1 - c.box.y0, 4) / 10.0
        desc = c.isa_function or c.label or c.subtype.replace("_", " ") or ""
        search = " ".join([c.tag, c.kind, c.subtype, c.label, c.isa_function,
                           c.notes, c.loop]).lower()
        out.append(
            f'<div class="box" data-id="{_esc(c.id)}" data-f="{family(c.kind)}"'
            f' data-search="{_esc(search)}" data-tag="{_esc(c.tag)}"'
            f' data-desc="{_esc(KIND_LABEL.get(c.kind, c.kind) + (" · " + desc if desc else ""))}"'
            f' style="left:{c.box.x0/10:.2f}%;top:{c.box.y0/10:.2f}%;'
            f'width:{w:.2f}%;height:{h:.2f}%"></div>'
        )
    return "\n".join(out)


def render_html(drawing: Drawing, images: Optional[Dict[int, bytes]] = None) -> str:
    images = images or {}
    stats = drawing.stats
    by_kind = stats.get("by_kind", {})
    equip = sum(v for k, v in by_kind.items() if FAMILIES.get(k) == "equipment")

    first = drawing.pages[0].analysis if drawing.pages else None
    title = (first.title if first and first.title else drawing.source)
    dwg_no = first.drawing_number if first else ""
    rev = first.revision if first else ""

    parts: List[str] = []
    parts.append(f"<title>P&amp;ID scan — {_esc(title)}</title>")
    parts.append(f"<style>{_CSS}</style>")
    parts.append('<div class="wrap">')
    parts.append(f"<h1>{_esc(title)}</h1>")
    meta = [drawing.source]
    if dwg_no:
        meta.append(f"Drawing {dwg_no}")
    if rev:
        meta.append(f"Rev {rev}")
    meta.append(f"scanned {drawing.scanned_at}")
    meta.append(drawing.model)
    parts.append(f'<div class="sub">{_esc(" · ".join(m for m in meta if m))}</div>')

    usage = stats.get("usage", {})
    parts.append('<div class="tiles">')
    parts.append(_tile(stats.get("components", 0), "Components"))
    parts.append(_tile(equip, "Equipment"))
    parts.append(_tile(by_kind.get("valve", 0), "Valves"))
    parts.append(_tile(by_kind.get("instrument", 0), "Instruments"))
    parts.append(_tile(stats.get("control_loops", 0), "Control loops"))
    parts.append(_tile(len(stats.get("line_numbers", [])), "Line numbers"))
    if usage:
        parts.append(_tile(f"${usage.get('estimated_usd', 0):.2f}", "Scan cost"))
    parts.append("</div>")

    for page in drawing.pages:
        a = page.analysis
        if len(drawing.pages) > 1:
            parts.append(f"<h2>Page {page.number}</h2>")

        parts.append('<div class="cols"><div class="sheet">')
        png = images.get(page.number)
        if png:
            b64 = base64.standard_b64encode(png).decode()
            parts.append('<div class="canvas">')
            parts.append(f'<img alt="Page {page.number} of {_esc(drawing.source)}" src="data:image/png;base64,{b64}">')
            parts.append(_overlay(page.components))
            parts.append("</div>")
        else:
            parts.append('<p class="dim">Drawing image not embedded.</p>')
        parts.append('<div class="legend">')
        for fam, var in (("equipment", "--equipment"), ("valve", "--valve"),
                         ("instrument", "--instrument"), ("other", "--other")):
            n = sum(1 for c in page.components if family(c.kind) == fam)
            parts.append(f'<span><i style="background:var({var})"></i>{FAMILY_LABEL[fam]} ({n})</span>')
        parts.append("</div></div>")

        # ---- right column ------------------------------------------------
        parts.append("<div>")
        parts.append('<div class="bar">')
        for fam in ("all", "equipment", "valve", "instrument", "other"):
            label = "All" if fam == "all" else FAMILY_LABEL[fam]
            pressed = "true" if fam == "all" else "false"
            parts.append(f'<button class="chip" data-fam="{fam}" aria-pressed="{pressed}">{label}</button>')
        parts.append('<input id="q" type="search" placeholder="Search tag, type, function…" aria-label="Search components">')
        parts.append("</div>")

        parts.append('<div class="scroll"><table><thead><tr>'
                     "<th>Tag</th><th>Type</th><th>Detail</th><th>Function</th>"
                     '<th class="num">Conf</th><th class="num">Seen</th>'
                     "</tr></thead><tbody>")
        parts.append(_component_rows(page.components))
        parts.append("</tbody></table></div>")
        parts.append("</div></div>")

        # ---- narrative ---------------------------------------------------
        if a.summary:
            parts.append('<h2>What this drawing shows</h2>')
            parts.append(f'<div class="card"><p>{_esc(a.summary)}</p></div>')
        if a.process_description:
            parts.append("<h3>Process</h3>")
            parts.append(f'<div class="card"><p>{_esc(a.process_description)}</p></div>')
        if a.major_streams:
            parts.append("<h3>Major streams</h3><div class='card'>")
            parts.extend(f"<p>· {_esc(s)}</p>" for s in a.major_streams)
            parts.append("</div>")
        if a.control_narrative or a.loops:
            parts.append("<h3>Control</h3><div class='card'>")
            if a.control_narrative:
                parts.append(f"<p>{_esc(a.control_narrative)}</p>")
            if a.loops:
                parts.append('<div class="scrollx"><table><thead><tr><th>Loop</th><th>Variable</th>'
                             "<th>Members</th><th>Final element</th><th>Description</th>"
                             "</tr></thead><tbody>")
                for loop in a.loops:
                    parts.append(
                        f'<tr><td class="tag">{_esc(loop.loop_id)}</td>'
                        f"<td>{_esc(loop.measured_variable or '—')}</td>"
                        f'<td class="dim">{_esc(", ".join(loop.members))}</td>'
                        f'<td class="tag">{_esc(loop.final_element or "—")}</td>'
                        f'<td class="dim">{_esc(loop.description or "—")}</td></tr>')
                parts.append("</tbody></table></div>")
            parts.append("</div>")
        if a.safety_narrative:
            parts.append("<h3>Safety</h3>")
            parts.append(f'<div class="card"><p>{_esc(a.safety_narrative)}</p></div>')
        if a.utilities:
            parts.append("<h3>Utilities</h3><div class='card'>")
            parts.extend(f'<span class="pill">{_esc(u)}</span>' for u in a.utilities)
            parts.append("</div>")

        if a.findings:
            parts.append("<h3>Findings</h3><div class='card'>")
            for f in a.findings:
                refs = "".join(f'<span class="pill">{_esc(r)}</span>' for r in f.refs)
                parts.append(
                    f'<div class="find {_esc(f.severity)}"><span class="sev">{_esc(f.severity)}</span>'
                    f"<div>{_esc(f.message)} {refs}</div></div>")
            parts.append("</div>")

        missed = missed_tags(page)
        if missed:
            parts.append("<h3>Tags in the drawing text with no matching component</h3>")
            parts.append('<div class="card"><p>These tags appear in the PDF text layer but were '
                         "not attached to any recognised symbol. Each is either a component the "
                         "scan missed or a reference to something on another sheet.</p>")
            parts.extend(f'<span class="pill">{_esc(t)}</span>' for t in missed)
            parts.append("</div>")

    if stats.get("line_numbers"):
        parts.append("<h2>Line numbers</h2><div class='card'>")
        parts.extend(f'<span class="pill"><code>{_esc(ln)}</code></span>'
                     for ln in stats["line_numbers"])
        parts.append("</div>")

    parts.append('<div class="foot">')
    parts.append("<p><strong>How to read this.</strong> Every box on the drawing is one "
                 "detection. <em>Conf</em> is the model's own confidence; <em>Seen</em> is how "
                 "many overlapping tiles independently found the item — 2 or more is strong "
                 "corroboration, 1 with low confidence is worth checking by eye.</p>")
    parts.append("<p><strong>Limitations.</strong> Symbol recognition and tag reading are "
                 "reliable; tracing a pipe across the whole sheet is not, because each tile is "
                 "read independently. Treat connectivity and the process narrative as a "
                 "well-informed first read, not as a verified line list. This is a drafting "
                 "aid, not a substitute for a P&amp;ID review by a qualified engineer.</p>")
    if usage:
        parts.append(f"<p>{usage.get('calls', 0)} API calls · "
                     f"{usage.get('input_tokens', 0):,} input tokens "
                     f"({usage.get('cache_read_tokens', 0):,} cached) · "
                     f"{usage.get('output_tokens', 0):,} output tokens · "
                     f"~${usage.get('estimated_usd', 0):.2f}</p>")
    parts.append("</div></div>")
    parts.append('<div class="tip" id="tip"></div>')
    parts.append(f"<script>{_JS}</script>")
    return "\n".join(parts)

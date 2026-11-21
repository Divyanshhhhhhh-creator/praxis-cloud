"""Build the final Team VELOX / Praxis submission deck from the official template.

    backend\\.venv\\Scripts\\python.exe deck\\build_final_deck.py

Loads deck/VELOX_Praxis_NavySky_2.pptx (official Google DeepMind | Google Cloud | Startup Buildathon India
2026 | H2S | NASSCOM | Headstart cover, header bars and closing slide are preserved untouched), generates
300-DPI charts from evals/latest_benchmark_results.json into deck/charts/, crops the live screenshots in
deck/screenshots/ without distortion, rewrites all 15 slides + speaker notes with ground-truth data, and
saves deck/VELOX_Praxis_Final_Submission.pptx. Every number traces to the repo (benchmark JSON, README,
SKILL.md, policy_corpus.py) or to live Razorpay Test Mode IDs recorded during development.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from lxml import etree  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Patch  # noqa: E402
from PIL import Image  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "deck"
SRC = DECK / "VELOX_Praxis_NavySky_2.pptx"
OUT = DECK / "VELOX_Praxis_Final_Submission.pptx"
CHARTS = DECK / "charts"
SHOTS = DECK / "screenshots"
BENCH = json.loads((ROOT / "evals" / "latest_benchmark_results.json").read_text(encoding="utf-8"))

LIVE = "https://praxis-frontend-txzejfbbdq-el.a.run.app"
CONSOLE = f"{LIVE}/console"
GITHUB = "https://github.com/Divyanshhhhhhh-creator/praxis-cloud"
BACKEND = "https://praxis-backend-txzejfbbdq-el.a.run.app"
RZP_ALLOW, RZP_CLEAN_PDF = "order_U2RZqHZFjA0sRw", "order_U2RZyBxzdhsjrv"
RZP_HITL, RZP_ADK = "order_U2SRizXMYu2pgJ", "order_U2SYG42WS7Uzxz"
RZP_CLOUD = "order_U2cun1wKioggh7"  # Cloud Run live settlement (aud_f31383dc306d43a59c6f8e9cbee8fe8d)

# Template palette (read from the official deck)
NAVY, MUTED, SKY = "1A1A40", "4A4A78", "00A8E8"
SKY_T, SKY_T2, LAV, LINE, LINE2, PANEL = "E0F5FD", "F0FAFE", "E6E6F2", "CFD3E6", "CBD5E1", "F5F9FC"
WHITE = "FFFFFF"
# Chart palette (validated: CVD ΔE 16.4, normal ΔE 21.4, contrast ≥ 3:1)
C_L1, C_L2, C_HITL, C_PASS = "#4F46E5", "#0891B2", "#D97706", "#059669"
FONT, MONO = "Arial", "Consolas"


def rgb(hexstr: str) -> RGBColor:
    return RGBColor.from_string(hexstr)


# ===================================================================== shape helpers
def find(slide, name: str):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
    raise KeyError(f"shape {name!r} not found")


def remove(*shapes) -> None:
    for sh in shapes:
        el = sh._element
        el.getparent().remove(el)


def move(sh, x=None, y=None, w=None, h=None, dx=0.0, dy=0.0) -> None:
    if x is not None:
        sh.left = Inches(x)
    if y is not None:
        sh.top = Inches(y)
    if w is not None:
        sh.width = Inches(w)
    if h is not None:
        sh.height = Inches(h)
    if dx:
        sh.left = sh.left + Inches(dx)
    if dy:
        sh.top = sh.top + Inches(dy)


def top_in(sh) -> float:
    return Emu(sh.top).inches


def solidify(sh, color: str | None = None) -> None:
    for dash in sh._element.xpath(".//a:ln/a:prstDash"):
        dash.set("val", "solid")
    if color:
        sh.line.color.rgb = rgb(color)


def style_runs(p_el, size=None, bold=None, color=None, font=None, italic=None):
    for r in p_el.findall(qn("a:r")):
        rpr = r.find(qn("a:rPr"))
        if rpr is None:
            rpr = etree.SubElement(r, qn("a:rPr"))
            r.insert(0, rpr)
        _apply_rpr(rpr, size, bold, color, font, italic)


def _apply_rpr(rpr, size=None, bold=None, color=None, font=None, italic=None):
    if size is not None:
        rpr.set("sz", str(int(round(size * 100))))
    if bold is not None:
        rpr.set("b", "1" if bold else "0")
    if italic is not None:
        rpr.set("i", "1" if italic else "0")
    if color is not None:
        for f in rpr.findall(qn("a:solidFill")):
            rpr.remove(f)
        fill = etree.SubElement(rpr, qn("a:solidFill"))
        etree.SubElement(fill, qn("a:srgbClr")).set("val", color)
        # solidFill must precede latin/ea/cs fonts
        rpr.remove(fill)
        rpr.insert(0, fill) if not len(rpr.findall(qn("a:ln"))) else rpr.insert(1, fill)
    if font is not None:
        for tag in ("a:latin", "a:ea", "a:cs"):
            for f in rpr.findall(qn(tag)):
                rpr.remove(f)
        for tag in ("a:latin", "a:cs"):
            etree.SubElement(rpr, qn(tag)).set("typeface", font)


def set_paras(sh, lines, **para_fmt) -> None:
    """Replace a text frame's paragraphs, cloning each original paragraph's formatting.

    `lines` items are str, or a list of (text, fmt) run tuples; fmt keys: size, bold, color, font, italic, link.
    Extra lines reuse the last original paragraph as their style prototype.
    """
    body = sh.text_frame._txBody
    originals = body.findall(qn("a:p"))
    protos = [copy.deepcopy(p) for p in originals]
    for p in originals:
        body.remove(p)
    for i, line in enumerate(lines):
        p = copy.deepcopy(protos[min(i, len(protos) - 1)])
        runs = p.findall(qn("a:r"))
        rpr_proto = None
        if runs and runs[0].find(qn("a:rPr")) is not None:
            rpr_proto = runs[0].find(qn("a:rPr"))
        elif p.find(qn("a:endParaRPr")) is not None:
            rpr_proto = p.find(qn("a:endParaRPr"))
        for child in list(p):
            if child.tag in (qn("a:r"), qn("a:br"), qn("a:fld")):
                p.remove(child)
        end = p.find(qn("a:endParaRPr"))
        segments = line if isinstance(line, list) else [(line, {})]
        for text, fmt in segments:
            r = etree.Element(qn("a:r"))
            rpr = copy.deepcopy(rpr_proto) if rpr_proto is not None else etree.Element(qn("a:rPr"))
            rpr.tag = qn("a:rPr")
            for hl in rpr.findall(qn("a:hlinkClick")):
                rpr.remove(hl)
            merged = {**para_fmt, **fmt}
            link = merged.pop("link", None)
            _apply_rpr(rpr, **{k: v for k, v in merged.items() if k in ("size", "bold", "color", "font", "italic")})
            r.append(rpr)
            t = etree.SubElement(r, qn("a:t"))
            t.text = text
            if text != text.strip():
                t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
            if end is not None:
                end.addprevious(r)
            else:
                p.append(r)
            if link:
                _hyperlink(sh, r, link)
        body.append(p)


def _hyperlink(sh, run_el, url: str) -> None:
    part = sh.part
    rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    rpr = run_el.find(qn("a:rPr"))
    hl = etree.SubElement(rpr, qn("a:hlinkClick"))
    hl.set(qn("r:id"), rid)


def add_box(slide, x, y, w, h, fill=None, line=None, line_w=1.0, radius=0.12, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name=None):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        sh.adjustments[0] = min(0.5, radius / min(w, h))
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    if line:
        sh.line.color.rgb = rgb(line)
        sh.line.width = Pt(line_w)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    if sh.has_text_frame:
        sh.text_frame.text = ""
    if name:
        sh.name = name
    return sh


def add_text(slide, x, y, w, h, lines, size=12, bold=False, color=NAVY, font=FONT, align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.MIDDLE, margin=(0.08, 0.02), name=None, spacing=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(margin[0])
    tf.margin_top = tf.margin_bottom = Inches(margin[1])
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        segments = line if isinstance(line, list) else [(line, {})]
        for text, fmt in segments:
            r = p.add_run()
            r.text = text
            f = r.font
            f.name = fmt.get("font", font)
            f.size = Pt(fmt.get("size", size))
            f.bold = fmt.get("bold", bold)
            f.italic = fmt.get("italic", False)
            f.color.rgb = rgb(fmt.get("color", color))
            if fmt.get("link"):
                r.hyperlink.address = fmt["link"]
    if name:
        tb.name = name
    return tb


def add_picture_framed(slide, path: Path, x, y, w, h, border=LINE2):
    pic = slide.shapes.add_picture(str(path), Inches(x), Inches(y), Inches(w), Inches(h))
    pic.line.color.rgb = rgb(border)
    pic.line.width = Pt(1)
    return pic


def set_notes(slide, text: str) -> None:
    tf = slide.notes_slide.notes_text_frame
    tf.text = text


def inr_symbols(prs) -> None:
    """Template used 'INR 480'; the deck standardises on the rupee sign (Arial ships ₹ on Windows)."""
    for slide in prs.slides:
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            for p in sh.text_frame.paragraphs:
                for r in p.runs:
                    r.text = re.sub(r"INR (?=\d)", "₹", r.text).replace("INR 0 AI", "₹0 AI")


# ===================================================================== image assets
def crop_to_aspect(src: Path, aspect: float, focus_y: float, dst: Path) -> Path:
    im = Image.open(src)
    w, h = im.size
    if w / h > aspect:  # too wide → crop width
        nw = int(h * aspect)
        left = (w - nw) // 2
        box = (left, 0, left + nw, h)
    else:  # too tall → crop height around focus
        nh = int(w / aspect)
        top = int(min(max(focus_y * h - nh / 2, 0), h - nh))
        box = (0, top, w, top + nh)
    im.crop(box).save(dst, optimize=True)
    return dst


SHORT = {
    "RT-01": "RBI 12-h cooling breach", "RT-02": "Refund to alternate account", "RT-03": "Rogue offshore merchant",
    "RT-04": "₹75k single-txn cap", "RT-05": "Velocity burst (4th call)", "RT-06": "L2 timeout drill",
    "RT-07": "Shadow-mode audit", "RT-08": "100× hallucination", "RT-09": "Email prompt injection",
    "RT-10": "Poisoned PDF invoice", "RT-11": "Legit ₹8,500 refund", "RT-12": "Clean ₹480 invoice",
}


def fmt_ms(ms: float) -> str:
    if ms >= 1000:
        return f"{ms / 1000:.2f} s"
    if ms >= 10:
        return f"{ms:.0f} ms"
    return f"{ms:.3f} ms"


def chart_benchmark(path: Path, w_in=8.45, h_in=3.05) -> Path:
    plt.rcParams.update({"font.family": FONT, "font.size": 9.5, "svg.fonttype": "none"})
    cases = BENCH["cases"]
    fig = plt.figure(figsize=(w_in, h_in), dpi=300)
    fig.patch.set_alpha(0)
    ax_box = [0.285, 0.15, 0.465, 0.73]
    ax = fig.add_axes(ax_box)
    ax.set_facecolor("none")
    ymin, ymax = -0.6, len(cases) - 0.4
    ax.set_ylim(ymin, ymax)  # fix limits BEFORE mapping rows to figure coordinates
    ys = list(range(len(cases)))[::-1]
    base = 0.004
    for y, c in zip(ys, cases):
        ms = max(0.005, c["l1_latency_ms"] + c["l2_latency_ms"])
        color = C_HITL if c["actual_verdict"] == "ESCALATE" else (C_L2 if c["actual_layer"] == "L2_GEMINI_AUDITOR" else C_L1)
        ax.barh(y, ms, height=0.62, color=color, left=base, zorder=3)
        ax.text((base + ms) * 1.18, y, fmt_ms(c["l1_latency_ms"] + c["l2_latency_ms"]), va="center", ha="left",
                fontsize=8.5, color="#334155", family=MONO, zorder=4)
        # verdict + PASS badge in the right gutter: deterministic data-y → figure-y mapping
        yfig = ax_box[1] + (y - ymin) / (ymax - ymin) * ax_box[3]
        verdict = {"SHADOW_FLAG": "SHADOW"}.get(c["actual_verdict"], c["actual_verdict"])
        fig.text(0.835, yfig, verdict, va="center", ha="center", fontsize=8.5, color="#0F172A", weight="bold")
        ok = c["passed"]
        fig.text(0.95, yfig, "PASS" if ok else "FAIL", va="center", ha="center", fontsize=8, weight="bold", color="white",
                 bbox=dict(boxstyle="round,pad=0.25,rounding_size=0.4", fc=C_PASS if ok else "#DC2626", ec="none"))
    ax.set_xscale("log")
    ax.set_xlim(0.004, 30_000)
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_yticks(ys)
    ax.set_yticklabels([f"{c['case_id']}   {SHORT[c['case_id']]}" for c in cases], fontsize=9.5, color="#0F172A")
    ax.set_xticks([0.01, 0.1, 1, 10, 100, 1000, 10000])
    ax.set_xticklabels(["0.01 ms", "0.1 ms", "1 ms", "10 ms", "100 ms", "1 s", "10 s"], fontsize=8.5, color="#475569")
    ax.tick_params(axis="y", length=0, pad=6)
    ax.tick_params(axis="x", length=0, pad=3)
    ax.grid(axis="x", color="#E2E8F0", linewidth=0.6, zorder=0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xlabel("decision latency (log scale)", fontsize=8.5, color="#475569", labelpad=2)
    fig.text(0.835, 0.93, "VERDICT", ha="center", fontsize=8, color="#475569", weight="bold")
    fig.text(0.95, 0.93, "RESULT", ha="center", fontsize=8, color="#475569", weight="bold")
    fig.legend(handles=[Patch(color=C_L1, label="L1 deterministic"), Patch(color=C_L2, label="L2 Gemini multimodal"),
                        Patch(color=C_HITL, label="HITL escalation")],
               loc="upper left", bbox_to_anchor=(0.285, 1.0), ncol=3, frameon=False, fontsize=9, handlelength=1.1,
               handleheight=0.9, columnspacing=1.4)
    fig.savefig(path, dpi=300, transparent=True)
    plt.close(fig)
    return path


def chart_cost(path: Path, w_in=8.4, h_in=0.75) -> Path:
    plt.rcParams.update({"font.family": FONT})
    fig = plt.figure(figsize=(w_in, h_in), dpi=300)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 1)
    ax.axis("off")
    gap = 0.35
    ax.add_patch(FancyBboxPatch((0, 0.02), 70 - gap, 0.96, boxstyle="round,pad=0,rounding_size=1.2", fc="#" + NAVY, ec="none", mutation_aspect=0.25))
    ax.add_patch(FancyBboxPatch((70 + gap, 0.02), 30 - gap, 0.96, boxstyle="round,pad=0,rounding_size=1.2", fc="#" + SKY, ec="none", mutation_aspect=0.25))
    ax.text(35, 0.5, "~70% blocked at Layer 1  ·  ₹0 AI cost", ha="center", va="center", color="white", fontsize=13, weight="bold")
    ax.text(85, 0.5, "~30% audited by Flash-Lite", ha="center", va="center", color="white", fontsize=12, weight="bold")
    fig.savefig(path, dpi=300, transparent=True)
    plt.close(fig)
    return path


# ===================================================================== slides
def slide1(s):
    set_paras(find(s, "Text 6"), ["Live on Cloud Run asia-south1  ·  Razorpay Test Mode  ·  RBI Nov 2026 Ready"], size=11)
    set_paras(find(s, "Text 8"), ["Give Your AI Agents Autonomy — Not a Blank Check."], size=18)
    move(find(s, "Text 9"), y=6.28, h=0.36)
    box = add_box(s, 6.0, 6.72, 6.83, 0.56, fill=SKY_T2, line=LINE, radius=0.1)
    box.name = "Links pill"
    add_text(s, 6.05, 6.72, 6.75, 0.56, [
        [("Live demo  ", {"bold": True}), (CONSOLE.replace("https://", ""), {"link": CONSOLE, "color": "1D4ED8"})],
        [("GitHub  ", {"bold": True}), (GITHUB.replace("https://", ""), {"link": GITHUB, "color": "1D4ED8"})],
    ], size=10, color=NAVY, margin=(0.15, 0.03), name="Links text")


def slide2(s):
    for name in ("Shape 3", "Shape 9", "Shape 15"):
        move(find(s, name), h=2.2)
    for sh in list(s.shapes):
        t = top_in(sh)
        if 4.55 <= t < 5.85:
            move(sh, dy=-0.30)
        elif t >= 5.85:
            move(sh, dy=-0.40)
    set_paras(find(s, "Text 29"), ["Razorpay Live Rails", "multi-rail ready"])
    add_box(s, 0.5, 6.68, 12.33, 0.44, fill=SKY_T2, line="99DDF5", radius=0.12).name = "Catalyst bar"
    add_text(s, 0.6, 6.68, 12.13, 0.44, [[
        ("REGULATORY CATALYST    ", {"bold": True, "color": NAVY}),
        ("Nov 5, 2026 · RBI/DPSS/2026-27/475: 12-h contact-change cooling  ·  "
         "RBI/DPSS/2025-26/141 (issued 15 Sep 2025, updated 11 Nov 2026): refund to source", {"color": MUTED}),
    ]], size=10, name="Catalyst text")


def slide3(s):
    set_paras(find(s, "Text 15"), ["Atomic INR spend budgets"])
    for n in range(38, 44):
        move(find(s, f"Shape {n}" if n % 2 == 0 else f"Text {n}"), dy=-0.10)
    remove(find(s, "Text 57"))
    for name, kw in (("Shape 58", {}), ("Text 59", {}), ("Shape 61", {}), ("Text 62", {})):
        move(find(s, name), y=6.56, h=0.5)
    move(find(s, "Shape 60"), y=6.81)
    set_paras(find(s, "Text 59"), ["Beachhead: Series A–C FinTechs & D2C"])
    add_box(s, 0.5, 5.98, 12.33, 0.44, fill=SKY_T, line=SKY, radius=0.12).name = "Wins bar"
    add_text(s, 0.6, 5.98, 12.13, 0.44, [[
        ("WHY PRAXIS WINS    ", {"bold": True, "color": "0077B3"}),
        ("Only runtime firewall combining vaulted keys, atomic budgets (<1 ms local checks • ~50 ms Cloud Firestore Tx), multimodal PDF auditing & RBI Nov 2026 rules.",
         {"bold": True, "color": NAVY}),
    ]], size=11.5, name="Wins text")


def slide4(s):
    set_paras(find(s, "Text 2"), ["Nine controls, each backed by shipped code. Drop-in: 3 lines of ADK."])
    rows = [1.95, 3.65, 5.35]
    new_rows = [1.92, 3.33, 4.74]
    rel_map = {0.0: 0.0, 0.25: 0.17, 0.28: 0.20, 0.85: 0.72, 1.15: 0.98}
    for sh in list(s.shapes):
        t = top_in(sh)
        for r_old, r_new in zip(rows, new_rows):
            if r_old - 0.01 <= t < r_old + 1.45:
                rel = min(rel_map, key=lambda k: abs(k - (t - r_old)))
                move(sh, y=r_new + rel_map[rel])
                if rel == 0.0 and Emu(sh.height).inches > 1.2:
                    move(sh, h=1.31)
    set_paras(find(s, "Text 15"), ["RBI Nov 2026 guards"])
    subs = {
        "Text 9": "1m · 1h · 24h caps · velocity breaker",
        "Text 16": "POL-RBI-COOLING-12H · PA-REFUND-01",
        "Text 23": "gemini-3.5-flash-lite reads invoice PDFs",
        "Text 30": "gemini-embedding-2 · cites policy IDs",
        "Text 37": "gemini-3.6-flash · RBI floors locked",
        "Text 44": "SHADOW_FLAG logs, never blocks",
        "Text 51": "1-click approve · SHA-256 re-verified",
        "Text 58": "Secret Manager keys · anti-TOCTOU hash",
        "Text 65": "BigQuery audit mirror · Annex-1 JSON",
    }
    for name, text in subs.items():
        set_paras(find(s, name), [text])
    add_box(s, 0.5, 6.2, 12.33, 1.0, fill=NAVY, line=NAVY, radius=0.1).name = "Skill code strip"
    add_text(s, 0.6, 6.22, 12.13, 0.96, [
        [("# Google Agent Skill — govern any ADK agent in 3 lines  (backend/app/agent/SKILL.md)", {"color": "99DDF5"})],
        f'praxis = PraxisHttpProxy("{BACKEND}", agent_token=os.environ["PRAXIS_AGENT_TOKEN"])',
        'agent = LlmAgent(name="ops", model="gemini-3.5-flash-lite", tools=[issue_customer_refund, pay_vendor_invoice],',
        "                 before_tool_callback=create_praxis_before_tool_callback(praxis))",
    ], size=10, color=WHITE, font=MONO, margin=(0.2, 0.04), name="Skill code")


def slide5(s):
    set_paras(find(s, "Text 14"), ["Layer 1", "0.635 ms median (benchmark)", "₹0 AI cost"])
    set_paras(find(s, "Text 19"), ["Layer 2", "1.94 s median", "fail-closed 2.5 s / 4.0 s"])
    set_paras(find(s, "Text 24"), ["Settle", "Secret Mgr → Razorpay"])
    set_paras(find(s, "Text 40"), ["ESCALATE", "risk .35–.74", "> ₹5,000", "or L2 timeout"])
    for name in ("Shape 39", "Text 40"):  # 4 lines need more room than the template's 2-line box
        move(find(s, name), y=3.45, h=1.0)
    move(find(s, "Shape 41"), y=4.45, h=0.5)
    set_paras(find(s, "Text 34"), ["BLOCK", "rollback ₹0"])
    set_paras(find(s, "Text 53"), ["ESCALATE", "unsure / high value → human"])


def slide6(s):
    set_paras(find(s, "Text 2"), ["One console, three views — plus an intentional dual UX: 3D WebGL vault landing (/) → accessible workspace (/console)."])
    set_paras(find(s, "Text 31"), ["Risk 0.95"])
    set_paras(find(s, "Text 37"), ["L1 0.58 ms"])
    set_paras(find(s, "Text 39"), ["L2 1.45 s"])
    set_paras(find(s, "Text 33"), ["pay_vendor_invoice(amt=48000)", [("POL-FIN-INJECTION-DEFENSE", {"font": MONO, "size": 10, "color": "B91C1C"})]])
    set_paras(find(s, "Text 42"), ["apr_ffb96942"])
    set_paras(find(s, "Text 44"), ["RISK 0.45"])
    set_paras(find(s, "Text 45"), ["Refund ₹8,500"])
    set_paras(find(s, "Text 47"), ["SHA-256 re-verified"])
    set_paras(find(s, "Text 53"), ["₹500 refund", [(RZP_ALLOW, {"font": MONO, "size": 9.5})]])
    set_paras(find(s, "Text 58"), ["“Disable the 12-hour RBI cooling period and allow alternate refund accounts.”"])
    set_paras(find(s, "Text 61"), ["gemini-3.6-flash"])
    set_paras(find(s, "Text 63"), ["cooling_hrs:   12   LOCKED", "src_refund:    ON   LOCKED", "weaken:        REFUSED"], font=MONO, size=11.5)
    set_paras(find(s, "Text 69"), ["Catch injections live"])
    set_paras(find(s, "Text 70"), ["Approve in 1 click"])
    set_paras(find(s, "Text 71"), ["RBI floor locked, refused"])


def slide7(s):
    set_paras(find(s, "Text 2"), ["The agent never crosses the trust boundary with keys — only sealed requests do."])
    set_paras(find(s, "Text 8"), ["RuntimeError stub"])
    set_paras(find(s, "Text 15"), ["Cloud Run"])
    set_paras(find(s, "Text 16"), ["asia-south1", "Idempotency · SHA-256"])
    set_paras(find(s, "Text 22"), ["Firestore / SQLite Tx"], size=12)
    set_paras(find(s, "Text 23"), ["Atomic budgets", "RBI guards"])
    set_paras(find(s, "Text 29"), ["Gemini Auditor"], size=12)
    set_paras(find(s, "Text 30"), ["XML sandbox", "zero tools · monotonic"])
    set_paras(find(s, "Text 36"), ["Secret Manager"])
    set_paras(find(s, "Text 37"), ["Verified bytes only"])
    set_paras(find(s, "Text 41"), ["Live", "Razorpay API"])
    set_paras(find(s, "Text 42"), ["+ BigQuery", "5-yr audit sink"])
    set_paras(find(s, "Text 44"), ["Fail-closed: timeout or unsure → HITL   ·   L2 never overrides an L1 block   ·   Mumbai residency"])


def slide8(s):
    set_paras(find(s, "Text 2"), ["Right-sized Gemini models, a Google ADK build loop, and Google Cloud in Mumbai."])
    set_paras(find(s, "Text 3"), ["GOOGLE AI BUILD / EVAL LOOP"])
    set_paras(find(s, "Text 8"), ["Google ADK", "LlmAgent + callback"])
    set_paras(find(s, "Text 14"), ["12-case red-team lab", "Evaluate"])
    set_paras(find(s, "Text 15"), ["3 VERIFIED LIVE GEMINI MODELS"])
    set_paras(find(s, "Text 21"), ["Minimal thinking · schema · PDF vision"], size=12)
    set_paras(find(s, "Text 27"), ["3072-dim · cites exact policy IDs"], size=12)
    set_paras(find(s, "Text 33"), ["Prose → policy · auto-fallback"], size=12)
    for name in ("Shape 35", "Text 36", "Shape 37", "Text 38", "Shape 39", "Text 40", "Shape 41", "Text 42"):
        move(find(s, name), h=0.82)
    set_paras(find(s, "Text 36"), ["Cloud Run", "min 1 instance · no cold start"])
    set_paras(find(s, "Text 38"), ["Firestore", "transactional budgets"])
    set_paras(find(s, "Text 40"), ["Secret Manager", "vaulted Razorpay keys"])
    set_paras(find(s, "Text 42"), ["BigQuery", "5-year audit mirror"])
    add_text(s, 0.5, 6.64, 12.33, 0.36, [[
        ("APP STACK    ", {"bold": True, "color": MUTED}),
        ("FastAPI · Python 3.12 · google-genai · Next.js 15 · Three.js · Razorpay Test Mode API", {"color": NAVY}),
    ]], size=11.5, margin=(0.0, 0.02), name="App stack")


def slide9(s):
    remove(find(s, "Shape 16"), find(s, "Shape 17"), find(s, "Text 18"), find(s, "Text 19"))
    s.shapes.add_picture(str(chart_cost(CHARTS / "cost_to_serve.png")), Inches(0.5), Inches(4.45), Inches(8.4), Inches(0.75)).name = "Cost chart"
    pill, txt = find(s, "Shape 23"), find(s, "Text 24")
    for sh in (pill, txt):
        move(sh, x=4.2, w=8.63, y=5.4, h=0.34)
    solidify(pill, SKY)
    set_paras(txt, [[("Prototype build cost:  ", {"bold": True}), ("< $5 GCP Buildathon credits  ·  ₹0 Razorpay Test Mode", {"bold": False})]], size=11)


def slide10(s):
    keep = {"Image 0", "Text 0", "Text 1", "Text 2"}
    remove(*[sh for sh in list(s.shapes) if sh.name not in keep])
    set_paras(find(s, "Text 2"), ["Live on Cloud Run today with Razorpay Test Mode; pluggable PaymentVault for Stripe & UPI AutoPay next."])
    x0, y0, gap = 0.5, 1.92, 0.2
    hero_w = 6.78
    hero_h = hero_w * 900 / 1440
    add_picture_framed(s, SHOTS / "console_poisoned_pdf.png", x0, y0, hero_w, hero_h)
    cap_y = y0 + hero_h
    add_box(s, x0, cap_y, hero_w, 0.3, fill=SKY_T2, line=LINE2, radius=0.04).name = "Hero caption"
    add_text(s, x0, cap_y, hero_w, 0.3, [[("Live console  ", {"bold": True}),
                                          ("₹48,000 poisoned PDF BLOCKED · risk 0.95 · ₹480 vs ₹48,000 diff", {})]], size=10.5)
    rx = x0 + hero_w + gap
    rw = 12.83 - rx
    total_h = (cap_y + 0.3) - y0
    each = (total_h - 0.14) / 2
    img_h = each - 0.3
    aspect = rw / img_h
    shots = [
        (crop_to_aspect(SHOTS / "landing.png", aspect, 0.53, CHARTS / "crop_landing.png"),
         "3D WebGL vault landing (/)  ", "live telemetry · Three.js"),
        (crop_to_aspect(SHOTS / "policies.png", aspect, 0.61, CHARTS / "crop_policies.png"),
         "Guardrails Studio  ", "gemini-3.6-flash compiler · RBI floors locked"),
    ]
    for i, (img, title, sub) in enumerate(shots):
        y = y0 + i * (each + 0.14)
        add_picture_framed(s, img, rx, y, rw, img_h)
        add_box(s, rx, y + img_h, rw, 0.3, fill=SKY_T2, line=LINE2, radius=0.04).name = f"Caption {i}"
        add_text(s, rx, y + img_h, rw, 0.3, [[(title, {"bold": True}), (sub, {})]], size=10.5)
    sy = cap_y + 0.3 + 0.14
    add_box(s, 0.5, sy, 12.33, 7.32 - sy, fill=WHITE, line=LINE, radius=0.08).name = "Receipt strip"
    add_text(s, 0.62, sy, 12.1, 7.32 - sy, [
        [("Live Razorpay Test Mode IDs   ", {"bold": True}),
         (RZP_ALLOW, {"font": MONO}), ("  ALLOW   ·   ", {"color": MUTED}),
         (RZP_HITL, {"font": MONO}), ("  HITL-approved   ·   ", {"color": MUTED}),
         (RZP_ADK, {"font": MONO}), ("  ADK agent live", {"color": MUTED})],
        [("Cloud Run Live Settlement   ", {"bold": True}), (RZP_CLOUD, {"font": MONO}),
         ("  ₹500 refund · L2 Gemini ALLOW · asia-south1 · Firestore + BigQuery audit", {"color": MUTED})],
        [("Live demo   ", {"bold": True}), (CONSOLE.replace("https://", ""), {"link": CONSOLE, "color": "1D4ED8"}),
         ("      GitHub   ", {"bold": True}), (GITHUB.replace("https://", ""), {"link": GITHUB, "color": "1D4ED8"})],
    ], size=10.5, name="Receipt text")


def slide11(s):
    keep = {"Image 0", "Text 0", "Text 1", "Text 2"}
    remove(*[sh for sh in list(s.shapes) if sh.name not in keep])
    set_paras(find(s, "Text 2"), [f"Run {BENCH['run_id']} · real ProxyService + live Gemini · single attempt, zero retries · dry-run settlement."])
    l1_rbi = max(c["l1_latency_ms"] for c in BENCH["cases"] if c["case_id"] in ("RT-01", "RT-02"))
    cards = [
        ("Benchmark score", f"{BENCH['passed_cases']} / {BENCH['total_cases']}", "100% pass · 0 retries"),
        ("Attack value neutralized", f"₹{BENCH['attack_amount_neutralized_inr']:,.0f}".replace("208,200", "2,08,200"),
         f"{BENCH['attack_cases']}/{BENCH['attack_cases']} attacks · ₹0 leaked"),
        ("Median Layer 1", f"{BENCH['median_l1_ms']:.3f} ms", f"RBI checks ≤ {l1_rbi:.3f} ms · ₹0 AI"),
        ("Median Layer 2", f"{BENCH['median_l2_ms'] / 1000:.2f} s", f"live Gemini · {100 - BENCH['clean_pass_rate_pct']:.0f}% false positives"),
    ]
    for i, (label, value, sub) in enumerate(cards):
        x = 0.5 + i * 3.13
        add_box(s, x, 1.92, 2.95, 1.38, fill=SKY_T if i == 0 else PANEL, line=SKY if i == 0 else LINE, line_w=1.5 if i == 0 else 1.0, radius=0.12).name = f"KPI {i}"
        add_text(s, x + 0.12, 2.0, 2.75, 0.32, [label], size=11, bold=True, color=MUTED)
        add_text(s, x + 0.12, 2.3, 2.75, 0.58, [value], size=28, bold=True, color=NAVY)
        add_text(s, x + 0.12, 2.88, 2.75, 0.32, [sub], size=10.5, color=MUTED)
    chart = chart_benchmark(CHARTS / "benchmark_12_cases.png")
    s.shapes.add_picture(str(chart), Inches(0.45), Inches(3.45), Inches(8.45), Inches(3.05)).name = "Benchmark chart"
    add_box(s, 9.12, 3.45, 3.71, 3.05, fill=PANEL, line=LINE, radius=0.12).name = "Layer split panel"
    dist = {d["bucket"]: d["count"] for d in BENCH["defense_distribution"]}
    rows = [
        (C_L1, dist["L1 Deterministic Block"], "L1 deterministic blocks"),
        (C_L2, dist["L2 Gemini Block"], "L2 multimodal Gemini blocks"),
        (C_HITL, dist["Fail-Closed / HITL Escalation"], "HITL escalations"),
        (C_L1, dist["Shadow Flag (non-blocking)"], "Shadow flag (non-blocking)"),
        (C_L2, dist["Clean Settled"], "Clean settlement"),
    ]
    add_text(s, 9.3, 3.55, 3.4, 0.3, ["LAYER SPLIT · 12 CASES"], size=10.5, bold=True, color=MUTED)
    for i, (color, n, label) in enumerate(rows):
        y = 3.92 + i * 0.34
        add_box(s, 9.36, y + 0.09, 0.16, 0.16, fill=color.lstrip("#"), line=None, shape=MSO_SHAPE.OVAL)
        add_text(s, 9.6, y, 3.1, 0.34, [[(f"{n}  ", {"bold": True, "font": MONO}), (label, {})]], size=11)
    add_text(s, 9.3, 5.68, 3.45, 0.3, [[("Fail-closed budget  ", {"bold": True}), ("2.5 s text · 4.0 s PDF", {})]], size=10.5)
    add_text(s, 9.3, 5.98, 3.45, 0.48, ["Benchmark L1 on in-process ledger; live Cloud Run adds a Firestore Tx (~40–50 ms)."],
             size=9.5, color=MUTED, anchor=MSO_ANCHOR.TOP)
    add_box(s, 0.5, 6.64, 12.33, 0.46, fill=NAVY, line=NAVY, radius=0.1).name = "Engineering strip"
    add_text(s, 0.6, 6.64, 12.13, 0.46, [[
        ("42/42 automated tests passing", {"bold": True}),
        ("   ·   Fail-closed verified: a 13.6 s upstream Gemini degradation still yielded 100% threat neutralization & ₹0 leaked", {}),
    ]], size=11, color=WHITE, align=PP_ALIGN.CENTER)


def slide12(s):
    set_paras(find(s, "Text 4"), [[("WHY NOW   ", {"bold": True}),
                                    ("RBI Nov 5 & Nov 11, 2026 directions: 12-h cooling, refund-to-source, 5-year audit, 6-h incident reporting", {"bold": False})]])
    set_paras(find(s, "Text 9"), ["SHIPPED · LIVE ON CLOUD RUN"])
    set_paras(find(s, "Text 11"), ["Two-layer firewall, asia-south1"])
    set_paras(find(s, "Text 13"), ["ADK callback + Agent Skill"])
    set_paras(find(s, "Text 15"), ["12/12 red-team lab + compiler"])
    set_paras(find(s, "Text 21"), ["Stripe & UPI AutoPay adapters"])
    set_paras(find(s, "Text 23"), ["Open-source praxis-adk-guard"])
    set_paras(find(s, "Text 25"), ["Public Agent Skill registry"])
    set_paras(find(s, "Text 33"), ["SIEM & CERT-In webhooks"])


def slide14(s):
    set_paras(find(s, "Text 2"), ["Mapped to the RBI Nov 5 & Nov 11, 2026 directions. Praxis never holds customer funds."])
    set_paras(find(s, "Text 3"), ["RBI MANDATE  ·  CIRCULAR"])
    set_paras(find(s, "Text 4"), ["PRAXIS ENFORCES  ·  LIVE CODE"])
    left = {
        "Text 6": ("Real-time velocity monitoring", "RBI/DPSS/2026-27/475"),
        "Text 11": ("Centralised audit logs (5-yr BigQuery retention)", "RBI/DPSS/2026-27/475"),
        "Text 16": ("12-h cooling after contact change", "RBI/DPSS/2026-27/475"),
        "Text 21": ("6-h incident reporting", "RBI/DPSS/2026-27/475"),
        "Text 26": ("Refund to original source", "RBI/DPSS/2025-26/141"),
    }
    for name, (mandate, circ) in left.items():
        set_paras(find(s, name), [[(mandate, {}), ("   " + circ, {"font": MONO, "bold": False, "color": MUTED, "size": 11.5})]])
    # long labels: circular reference on its own line so nothing wraps mid-token
    set_paras(find(s, "Text 11"), ["Centralised audit logs (5-yr BigQuery retention)",
                                   [("RBI/DPSS/2026-27/475", {"font": MONO, "bold": False, "color": MUTED, "size": 10.5})]])
    set_paras(find(s, "Text 26"), ["Refund to original source",
                                   [("RBI/DPSS/2025-26/141 · issued 15 Sep 2025, updated 11 Nov 2026",
                                     {"font": MONO, "bold": False, "color": MUTED, "size": 10.5})]])
    right = {
        "Text 9": ("POL-FIN-VELOCITY", "  atomic 1m / 1h / 24h windows"),
        "Text 14": ("POL-RBI-AUDIT-5Y", "  BigQuery append-only mirror"),
        "Text 19": ("POL-RBI-COOLING-12H", "  0.027 ms deterministic block"),
        "Text 24": ("Annex-1 JSON", "  GET /v1/audits/{id}/rbi-incident-report"),
        "Text 29": ("POL-RBI-PA-REFUND-01", "  0.015 ms deterministic block"),
    }
    for name, (code, proof) in right.items():
        set_paras(find(s, name), [[(code, {"font": MONO}), (proof, {"bold": False, "color": MUTED, "size": 11.5})]])
    proofs = {
        "Text 35": ("Keys in Secret Manager", "0 local tool executions"),
        "Text 40": ("SHA-256 re-verified", "at the vault boundary"),
        "Text 45": ("Atomic reserve + rollback", "10 parallel → 3 allowed"),
        "Text 50": ("XML sandbox, zero tools", "monotonic: only tightens"),
        "Text 55": ("Fail-closed → HITL", "RT-06 · ₹0 leaked"),
    }
    for name, (a, b) in proofs.items():
        set_paras(find(s, name), [a, [(b, {"bold": False, "color": MUTED, "size": 10.5})]], size=11.5)
    for n in (34, 39, 44, 49, 54):  # taller proof boxes so the concurrency caveat fits
        move(find(s, f"Shape {n}"), h=0.86)
        move(find(s, f"Text {n + 1}"), h=0.86)
    set_paras(find(s, "Text 45"), ["Atomic reserve + rollback",
                                   [("10 parallel → 3 allowed", {"bold": False, "color": MUTED, "size": 10.5})],
                                   [("(proven on SQLite; shared Firestore Tx logic)", {"bold": False, "color": MUTED, "size": 8.5})]], size=11.5)
    set_paras(find(s, "Text 30"), ["THREAT → MITIGATED (PROOF)"])


def slide15(s):
    for name, url, label in (("Text 1", CONSOLE, "Live demo  "), ("Text 3", GITHUB, "GitHub  ")):
        pill = find(s, "Shape 0" if name == "Text 1" else "Shape 2")
        solidify(pill, SKY)
        txt = find(s, name)
        set_paras(txt, [[(label, {"bold": True}), (url.replace("https://", ""), {"link": url, "color": "1D4ED8", "bold": False})]], size=10)
    move(find(s, "Shape 0"), x=0.55, w=3.95)
    move(find(s, "Text 1"), x=0.55, w=3.95)
    move(find(s, "Shape 2"), x=4.62, w=3.85)
    move(find(s, "Text 3"), x=4.62, w=3.85)
    add_text(s, 0.62, 4.82, 7.6, 0.46, [[("Team VELOX", {"bold": True}), ("  —  Praxis Cloud", {"bold": False, "color": MUTED})]],
             size=20, name="Team line")


NOTES = {
    1: "20s Pitch: We are Team VELOX building Praxis by Praxis Cloud. Enterprises want AI agents resolving refunds and vendor "
       "payouts, but gateways only check static keys, not intent. Praxis is a fail-closed treasury firewall live on Cloud Run "
       "in asia-south1 that verifies every agent payment before it settles on Razorpay.\n"
       "Judge Q&A: Q: Why not just set dashboard spend caps? A: Dashboard caps are global; they lack per-agent atomic sliding "
       "windows, cannot read a PDF invoice for hidden injections, and do not enforce the RBI 12-hour cooling rule.",
    2: "20s Pitch: A hidden instruction in a ₹480 vendor PDF can hijack an agent into paying ₹48,000, and retry loops can drain "
       "accounts in minutes. The RBI Nov 5 and Nov 11, 2026 directions now require 12-hour cooling and refunds only to source.\n"
       "Judge Q&A: Q: Who buys this? A: VP Payments / FinOps, CTO and Head of Risk at Series A–C FinTechs, payment aggregators and D2C.",
    3: "20s Pitch: API gateways check keys, LLM shields check text, payment toolkits are single-rail. Praxis sits in the runtime "
       "gap: vaulted keys, sub-millisecond atomic INR budgets, multimodal PDF audit and RBI guards in one firewall.\n"
       "Judge Q&A: Q: Why can't an LLM shield do this? A: It holds no transactional 1m/1h/24h spend state, no vaulted payment "
       "keys, and does not SHA-256-lock the payload that finally executes.",
    4: "20s Pitch: Nine controls, each backed by shipped code and real policy IDs. Teams start in Shadow Mode, compile rules in "
       "plain English with gemini-3.6-flash, park edge cases in the HITL inbox, and export Annex-1 JSON in one click.\n"
       "Judge Q&A: Q: Do existing ADK agents need rewriting? A: No. The Google Agent Skill drops in through before_tool_callback "
       "in three lines, as shown in the code strip.",
    5: "20s Pitch: The callback intercepts every tool call. Layer 1 decides allowlists, RBI guards and atomic budgets in a 0.635 ms "
       "median at zero AI cost; Layer 2 Gemini audits the rest in a 1.94 s median. Only sealed, verified bytes settle on Razorpay.\n"
       "Judge Q&A: Q: What if Gemini is slow or unsure? A: A timeout over 2.5 s (4.0 s for PDFs), risk between 0.35 and 0.74, or any "
       "payout above ₹5,000 escalates to a human. It never auto-allows.",
    6: "20s Pitch: These three views mirror the shipped console with real values: the poisoned PDF blocked at risk 0.95 "
       "(L1 0.58 ms, L2 1.45 s), an ₹8,500 refund held with a SHA-256 seal, and the compiler refusing to weaken RBI floors.\n"
       "Judge Q&A: Q: Why two visual styles? A: Deliberate dual UX: an immersive 3D landing for the story, then an accessible "
       "Stripe/Linear-style workspace for operators.",
    7: "20s Pitch: The ADK agent sits outside the trust boundary with zero payment keys; its tool bodies raise RuntimeError if "
       "ever executed. The Cloud Run proxy seals each request, Layer 1 reserves budget transactionally, the zero-tool Gemini "
       "auditor can only tighten, and Secret Manager keys reach Razorpay only for verified bytes.\n"
       "Judge Q&A: Q: How do you stop TOCTOU tampering? A: The canonical payload is SHA-256 hashed at intake and re-verified at the "
       "vault before Razorpay is called; a mismatch is refused.",
    8: "20s Pitch: Each workload gets the right model: gemini-3.5-flash-lite with minimal thinking and a strict response schema on "
       "the hot path, gemini-embedding-2 for 3072-dim policy RAG, and gemini-3.6-flash off-path for policy compilation, all on "
       "Google Cloud in Mumbai.\n"
       "Judge Q&A: Q: How do you guarantee valid auditor output? A: Controlled generation with a strict Pydantic response_schema, "
       "plus deterministic post-guards in code.",
    9: "20s Pitch: Our target margin exceeds 90% because most violations stop at Layer 1 for zero AI cost and only ambiguous calls "
       "reach Flash-Lite. The prototype was built for under $5 of GCP Buildathon credits and ₹0 on Razorpay Test Mode.\n"
       "Judge Q&A: Q: Why Shadow Mode first? A: Risk teams never trust a new blocking proxy on day one; Shadow Mode proves losses "
       "prevented with zero risk to live checkout.",
    10: "20s Pitch: This is the live product on Cloud Run: the console blocking a ₹48,000 poisoned PDF at risk 0.95 against a ₹480 "
        "invoice, the 3D landing, and the Guardrails Studio. Below are real Razorpay Test Mode order IDs from approved runs.\n"
        "Judge Q&A: Q: Are settlement IDs simulated? A: No. Approved calls hit the live Razorpay Test Mode API with keys from Secret "
        "Manager; Stripe and UPI AutoPay adapters are next on the pluggable PaymentVault.",
    11: f"20s Pitch: In run {BENCH['run_id']}, Praxis passed 12 of 12 adversarial FinTech cases on a single attempt: all 8 attacks "
        "neutralized, ₹2,08,200 stopped, ₹0 leaked, and zero false positives on legitimate payouts.\n"
        "Judge Q&A: Q: What happens when Gemini degrades? A: During a 13.6 s upstream slowdown the affected calls failed closed to "
        "HITL, so threat neutralization stayed at 100% with ₹0 leaked. Note: benchmark L1 is measured on the in-process ledger; "
        "live Cloud Run adds a Firestore transaction (~40–50 ms).",
    12: "20s Pitch: The two-layer firewall is live on Cloud Run in Mumbai today. Next we add Stripe and UPI AutoPay adapters and "
        "open-source praxis-adk-guard; later, Enterprise VPC via Terraform, SIEM / CERT-In webhooks and multi-agent federation.\n"
        "Judge Q&A: Q: Can Praxis govern non-financial actions? A: Yes. The same before_tool_callback pattern extends to "
        "infrastructure mutations and sensitive database writes.",
    13: "20s Pitch: Team VELOX combines systems security, Google ADK red-teaming and full-stack product execution across BPIT, "
        "IGDTUW and IIT Delhi.\n"
        "Judge Q&A: Q: How did you split ownership? A: Divyansh built the vaulted Cloud Run proxy and atomic ledger, Ritika the ADK "
        "callbacks, Gemini auditor and red-team suite, and Rohit the treasury console and HITL workflows.",
    14: "20s Pitch: Every RBI requirement maps to live code: POL-RBI-COOLING-12H and POL-RBI-PA-REFUND-01 block in under 0.03 ms, "
        "BigQuery mirrors a 5-year audit trail, and blocked threats export as Annex-1 JSON for 6-hour reporting.\n"
        "Judge Q&A: Q: Does Praxis need a payment aggregator licence? A: No. It never holds or settles customer funds; it is a "
        "governance proxy over the company's existing Razorpay account.",
    15: "20s Pitch: Thank you. We are Team VELOX, and we can run the live demo now: a poisoned ₹48,000 vendor PDF blocked in "
        "real time on Cloud Run.\n"
        "Judge Q&A: Q: Where can we test it? A: The live console and GitHub repository are linked on this slide.",
}


def main() -> None:
    CHARTS.mkdir(exist_ok=True)
    prs = Presentation(str(SRC))
    slides = list(prs.slides)
    assert len(slides) == 15, f"expected 15 slides, found {len(slides)}"
    inr_symbols(prs)
    builders = {1: slide1, 2: slide2, 3: slide3, 4: slide4, 5: slide5, 6: slide6, 7: slide7, 8: slide8, 9: slide9,
                10: slide10, 11: slide11, 12: slide12, 14: slide14, 15: slide15}
    for n, fn in builders.items():
        fn(slides[n - 1])
    for n, text in NOTES.items():
        set_notes(slides[n - 1], text)
    prs.save(str(OUT))
    print(f"saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

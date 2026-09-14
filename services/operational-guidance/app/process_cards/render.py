from __future__ import annotations

from pathlib import Path

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.process_cards.domain import HumanProcessCard


def _font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("ImperialSans", path))
            return "ImperialSans"
    return "Helvetica"


def render_pdf(card: HumanProcessCard, output: Path) -> Path:
    font = _font()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=12*mm, leftMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm)
    title = ParagraphStyle("title", fontName=font, fontSize=16, leading=19, textColor=colors.HexColor("#0B2E59"), spaceAfter=5)
    meta = ParagraphStyle("meta", fontName=font, fontSize=8, leading=10, textColor=colors.HexColor("#4B5563"))
    heading = ParagraphStyle("heading", fontName=font, fontSize=9, leading=11, textColor=colors.white)
    body = ParagraphStyle("body", fontName=font, fontSize=8.4, leading=10.5, textColor=colors.HexColor("#172033"), alignment=TA_LEFT)
    story = [Paragraph(card.title, title), Paragraph(f"Felelős: {card.role.value} | Verzió: {card.version} | Státusz: {card.status}", meta), Spacer(1, 4*mm)]

    def box(
        label: str,
        items: list[str] | str,
        accent: str = "#0B2E59",
        width: float = 186 * mm,
    ) -> Table:
        values = [items] if isinstance(items, str) else items
        if not values:
            values = ["Nincs külön előírás."]
        content = "<br/>".join(f"• {x}" for x in values)
        table = Table([[Paragraph(label, heading)], [Paragraph(content, body)]], colWidths=[width])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor(accent)),
            ("BACKGROUND", (0,1), (-1,-1), colors.HexColor("#F7F9FC")),
            ("BOX", (0,0), (-1,-1), 0.6, colors.HexColor("#CBD5E1")),
            ("LEFTPADDING", (0,0), (-1,-1), 6), ("RIGHTPADDING", (0,0), (-1,-1), 6),
            ("TOPPADDING", (0,0), (-1,-1), 5), ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        return table

    story += [box("1. MIKOR KELL CSINÁLNI?", card.when_to_do), Spacer(1, 2*mm)]
    two = Table([[box("2. MIT VESZEL ÁT?", card.receive, width=91*mm), box("3. MIT ADSZ ÁT?", card.handover, "#E87822", width=91*mm)]], colWidths=[92*mm, 92*mm], hAlign="LEFT")
    two.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 2)]))
    story += [two, Spacer(1, 2*mm), box("4. LÉPÉSEK - EZT CSINÁLD", [f"{i}. {s}" for i,s in enumerate(card.steps,1)]), Spacer(1,2*mm)]
    two2 = Table([[box("5. STOP - ÁLLJ MEG ÉS SZÓLJ", card.stop_conditions, "#B42318", width=91*mm), box("6. KÉSZ, HA", card.done_when, "#18794E", width=91*mm)]], colWidths=[92*mm, 92*mm], hAlign="LEFT")
    two2.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (0,0), (-1,-1), 2)]))
    refs = "Források: " + (", ".join(card.policy_refs) if card.policy_refs else "nincs megadva")
    checklist = f"Kapcsolódó checklist: {card.checklist_template_id} v{card.checklist_version} | Kapu: {card.gate_id}" if card.checklist_template_id else "Kapcsolódó checklist: nincs"
    story += [KeepTogether(two2), Spacer(1, 2*mm), Paragraph(checklist, meta), Paragraph(refs, meta)]
    doc.build(story)
    return output


def render_png(pdf_path: Path, png_path: Path, dpi: int = 160) -> Path:
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(png_path))
    with Image.open(png_path) as img:
        img.verify()
    return png_path

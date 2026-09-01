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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.checklists.domain import ChecklistInstance, ChecklistTemplate


def _font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            if "ImperialChecklistSans" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("ImperialChecklistSans", path))
            return "ImperialChecklistSans"
    return "Helvetica"


def _styles():
    font = _font()
    return {
        "title": ParagraphStyle("cl-title", fontName=font, fontSize=15, leading=18, textColor=colors.HexColor("#0B2E59")),
        "meta": ParagraphStyle("cl-meta", fontName=font, fontSize=8, leading=10, textColor=colors.HexColor("#4B5563")),
        "heading": ParagraphStyle("cl-heading", fontName=font, fontSize=9, leading=11, textColor=colors.white),
        "body": ParagraphStyle("cl-body", fontName=font, fontSize=8.2, leading=10.2, textColor=colors.HexColor("#172033"), alignment=TA_LEFT),
        "small": ParagraphStyle("cl-small", fontName=font, fontSize=7.2, leading=8.8, textColor=colors.HexColor("#374151")),
    }


def _box(label: str, content: str, styles: dict, accent: str = "#0B2E59", width: float = 186 * mm) -> Table:
    table = Table([[Paragraph(label, styles["heading"])], [Paragraph(content or "Nincs külön előírás.", styles["body"])]], colWidths=[width])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(accent)),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F7F9FC")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def render_template_pdf(template: ChecklistTemplate, output: Path) -> Path:
    styles = _styles()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    story = [
        Paragraph(template.title, styles["title"]),
        Paragraph(
            f"Checklist: {template.template_id} | Folyamat: {template.process_key} | Felelős: {template.primary_role.value} | Verzió: {template.version}",
            styles["meta"],
        ),
        Spacer(1, 3 * mm),
        _box("MIKOR HASZNÁLD?", template.when_to_use, styles),
        Spacer(1, 2 * mm),
    ]
    rows = [[Paragraph("ELLENŐRZÉSI PONT", styles["heading"]), Paragraph("IGEN", styles["heading"]), Paragraph("NEM", styles["heading"]), Paragraph("N.A.", styles["heading"]), Paragraph("BIZONYÍTÉK / MEGJEGYZÉS", styles["heading"])]]
    for item in template.items:
        rows.append([
            Paragraph(item.text, styles["body"]),
            Paragraph("□", styles["body"]),
            Paragraph("□", styles["body"]),
            Paragraph("□", styles["body"]),
            Paragraph("", styles["small"]),
        ])
    checklist = Table(rows, colWidths=[104 * mm, 13 * mm, 13 * mm, 13 * mm, 43 * mm], repeatRows=1)
    checklist.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2E59")),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [checklist, Spacer(1, 2 * mm)]
    stop = "<br/>".join(f"• {x}" for x in template.stop_conditions)
    evidence = "<br/>".join(f"• {x}" for x in template.required_evidence)
    two = Table([[
        _box("STOP - NE LÉPJ TOVÁBB", stop, styles, "#B42318", 91 * mm),
        _box("KÖTELEZŐ BIZONYÍTÉK", evidence, styles, "#E87822", 91 * mm),
    ]], colWidths=[93 * mm, 93 * mm])
    two.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    story += [two, Spacer(1, 2 * mm), Paragraph(f"Kapu: {template.gate_id} | Lezáró / jóváhagyó: {template.closer_approver}", styles["meta"])]
    doc.build(story)
    return output


def render_instance_pdf(instance: ChecklistInstance, template: ChecklistTemplate, output: Path) -> Path:
    styles = _styles()
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=12 * mm, leftMargin=12 * mm, topMargin=10 * mm, bottomMargin=10 * mm)
    story = [
        Paragraph(template.title, styles["title"]),
        Paragraph(
            f"Példány: {instance.instance_id} | Objektum: {instance.object_id} | Státusz: {instance.status.value} | Felelős: {instance.role.value}",
            styles["meta"],
        ),
        Spacer(1, 3 * mm),
    ]
    rows = [[Paragraph("ELLENŐRZÉSI PONT", styles["heading"]), Paragraph("VÁLASZ", styles["heading"]), Paragraph("MEGJEGYZÉS / BIZONYÍTÉK", styles["heading"])]]
    for item in instance.items:
        evidence = ", ".join(item.evidence_ids)
        note = "<br/>".join(x for x in [item.note or "", evidence] if x)
        rows.append([
            Paragraph(item.text, styles["body"]),
            Paragraph(item.answer.value if item.answer else "-", styles["body"]),
            Paragraph(note or "-", styles["small"]),
        ])
    table = Table(rows, colWidths=[112 * mm, 22 * mm, 52 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B2E59")),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 3 * mm), Paragraph("Bizonyítékok: " + (", ".join(instance.evidence_ids) or "nincs csatolva"), styles["meta"]), Paragraph(f"Jóváhagyó: {instance.approved_by or '-'} | Jóváhagyás: {instance.approved_at or '-'}", styles["meta"])]
    doc.build(story)
    return output


def render_png(pdf_path: Path, png_path: Path, dpi: int = 160) -> Path:
    import fitz

    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(png_path))
    with Image.open(png_path) as image:
        image.verify()
    return png_path

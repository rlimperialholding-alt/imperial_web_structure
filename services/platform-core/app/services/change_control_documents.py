from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..models import ChangeControlCase, ChangeControlLine, ChangeControlVersion

OUTPUT_ROOT = Path(__file__).resolve().parents[2] / "runtime" / "change_control"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "change"


def _fonts() -> tuple[str, str]:
    font_root = Path(reportlab.__file__).resolve().parent / "fonts"
    regular_path = font_root / "Vera.ttf"
    bold_path = font_root / "VeraBd.ttf"
    if regular_path.exists() and bold_path.exists():
        if "ImperialVera" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ImperialVera", regular_path))
            pdfmetrics.registerFont(TTFont("ImperialVera-Bold", bold_path))
        return "ImperialVera", "ImperialVera-Bold"
    return "Helvetica", "Helvetica-Bold"


def _text(value: object) -> str:
    return html.escape(str(value or "")).replace("\n", "<br/>")


def _money(value: object) -> str:
    try:
        amount = float(str(value or 0))
    except (TypeError, ValueError):
        return str(value or "0")
    return f"{amount:,.2f} Ft".replace(",", " ")


def _document_styles():
    regular, bold = _fonts()
    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "ImperialBody",
        parent=styles["BodyText"],
        fontName=regular,
        fontSize=9,
        leading=12,
        spaceAfter=4,
    )
    heading = ParagraphStyle(
        "ImperialHeading",
        parent=styles["Heading2"],
        fontName=bold,
        textColor=colors.HexColor("#14213D"),
        fontSize=14,
        leading=18,
        spaceBefore=8,
        spaceAfter=6,
    )
    title = ParagraphStyle(
        "ImperialTitle",
        parent=styles["Title"],
        fontName=bold,
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#14213D"),
    )
    small = ParagraphStyle(
        "ImperialSmall",
        parent=body,
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#4B5563"),
    )
    return regular, bold, body, heading, title, small


def render_change_control_pdf(
    case: ChangeControlCase,
    version: ChangeControlVersion,
    lines: list[ChangeControlLine],
    *,
    audience: str,
    variant: str,
) -> tuple[Path, str]:
    if audience not in {"internal", "customer"}:
        raise ValueError("Ismeretlen ChangeControl dokumentumközönség.")
    regular, bold, body, heading, title, small = _document_styles()
    target_dir = OUTPUT_ROOT / _safe_name(case.project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    output_path = target_dir / (
        f"{_safe_name(case.change_id)}_v{version.version}_{_safe_name(variant)}.pdf"
    )
    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"{case.change_id} v{version.version}",
        author="Imperial Intelligence ChangeControl",
        subject="Változtatási dokumentumcsomag",
    )
    story: list[object] = [
        Paragraph(
            "ÜGYFÉL VÁLTOZTATÁSI CSOMAG"
            if audience == "customer"
            else "BELSŐ VÁLTOZTATÁSI LAP",
            title,
        ),
        Spacer(1, 4 * mm),
    ]
    summary_rows = [
        ["ProjectID", case.project_id, "ChangeID", case.change_id],
        ["Verzió", f"v{version.version}", "Típus", case.change_type],
        ["Cím", case.title, "Státusz", version.status],
        ["Felelős", case.responsible, "Határidőhatás", f"{version.deadline_impact_days} nap"],
    ]
    summary = Table(
        [[Paragraph(f"<b>{_text(cell)}</b>" if index % 2 == 0 else _text(cell), body)
          for index, cell in enumerate(row)] for row in summary_rows],
        colWidths=[29 * mm, 61 * mm, 29 * mm, 61 * mm],
    )
    summary.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
                ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#F1F5F9")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([summary, Paragraph("Műszaki és szerződéses tartalom", heading)])
    for label, value in (
        ("Indok", version.reason),
        ("Műszaki tartalom", version.technical_scope),
        ("Kizárások", version.exclusions),
        ("Feltételezések", version.assumptions),
    ):
        story.append(Paragraph(f"<b>{label}:</b> {_text(value)}", body))

    story.append(Paragraph("Tételes pénzügyi tartalom", heading))
    if audience == "internal":
        headers = ["Kategória / leírás", "Mennyiség", "Önköltség", "Eladási ár", "Összes eladás"]
        widths = [72 * mm, 24 * mm, 28 * mm, 28 * mm, 30 * mm]
    else:
        headers = ["Kategória / leírás", "Mennyiség", "Egységár", "Összes eladás"]
        widths = [88 * mm, 28 * mm, 31 * mm, 35 * mm]
    table_rows: list[list[Paragraph]] = [
        [Paragraph(f"<b>{_text(value)}</b>", small) for value in headers]
    ]
    for line in lines:
        common = [
            Paragraph(f"{_text(line.category)}<br/>{_text(line.description)}", small),
            Paragraph(f"{_text(line.quantity)} {_text(line.unit)}", small),
        ]
        if audience == "internal":
            common.extend(
                [
                    Paragraph(_money(line.unit_cost_net), small),
                    Paragraph(_money(line.unit_sale_net), small),
                    Paragraph(_money(line.total_sale_net), small),
                ]
            )
        else:
            common.extend(
                [
                    Paragraph(_money(line.unit_sale_net), small),
                    Paragraph(_money(line.total_sale_net), small),
                ]
            )
        table_rows.append(common)
    item_table = Table(table_rows, colWidths=widths, repeatRows=1)
    item_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#14213D")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(item_table)
    finance_rows = [
        ["Nettó eladási ár", _money(version.sale_net)],
        ["ÁFA", _money(version.vat_amount)],
        ["Bruttó eladási ár", _money(version.sale_gross)],
        ["Ügyfélelőleg nettó", _money(version.customer_advance_net)],
    ]
    if audience == "internal":
        finance_rows.extend(
            [
                ["Nettó önköltség", _money(version.cost_net)],
                ["Korai közvetlen költség", _money(version.early_direct_cost_net)],
                ["Fedezet", _money(version.margin_net)],
                ["Fedezeti arány", f"{version.margin_percent}%"],
            ]
        )
    finance_table = Table(
        [[Paragraph(f"<b>{_text(label)}</b>", body), Paragraph(_text(value), body)]
         for label, value in finance_rows],
        colWidths=[70 * mm, 50 * mm],
        hAlign="RIGHT",
    )
    finance_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F8FAFC")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.extend([Spacer(1, 5 * mm), finance_table])

    if audience == "internal":
        story.extend(
            [
                PageBreak(),
                Paragraph("Jóváhagyási és integritási nyom", heading),
                Paragraph(
                    f"<b>Műszaki:</b> {_text(version.technical_approved_by or 'függő')}<br/>"
                    f"{_text(version.technical_approval_note)}",
                    body,
                ),
                Paragraph(
                    f"<b>Pénzügy:</b> {_text(version.finance_approved_by or 'függő')}<br/>"
                    f"{_text(version.finance_approval_note)}",
                    body,
                ),
                Paragraph(
                    "<b>Vezetői:</b> "
                    f"{_text(version.leadership_approved_by or 'nem rögzített')}<br/>"
                    f"{_text(version.leadership_approval_note)}",
                    body,
                ),
            ]
        )
    story.extend(
        [
            Spacer(1, 5 * mm),
            Paragraph(
                f"Tartalmi SHA-256: <font name='{regular}'>{_text(version.content_sha256)}</font>",
                small,
            ),
            Paragraph(
                "A dokumentum az Imperial Intelligence ChangeControl rekordjának változatlan, "
                "verzióhoz kötött példánya. Új tartalom vagy ár kizárólag új verzióban rögzíthető.",
                small,
            ),
        ]
    )
    document.build(story)
    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return output_path, digest

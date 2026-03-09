"""
Exportacion de reportes ejecutivos a PDF para gerencia.

Usa fpdf2 (puro Python, sin dependencias del sistema).
pip install fpdf2
"""

import re
from pathlib import Path

from fpdf import FPDF


# Font name used throughout — set during _setup_font()
_FONT_NAME = "Helvetica"


def _setup_font(pdf: FPDF):
    """
    Register a Unicode TTF font if available on the system.
    Falls back to Helvetica (latin-1 only) if no TTF found.
    """
    global _FONT_NAME
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    for font_path in candidates:
        if font_path.exists():
            pdf.add_font("CustomUTF8", "", str(font_path))
            pdf.add_font("CustomUTF8", "B", str(font_path))
            pdf.add_font("CustomUTF8", "I", str(font_path))
            _FONT_NAME = "CustomUTF8"
            return
    _FONT_NAME = "Helvetica"


def _safe_text(text: str) -> str:
    """Strip emojis and chars that break even Unicode TTF fonts."""
    # Remove common emoji ranges but keep Spanish accented chars
    return re.sub(
        r"[\U0001F300-\U0001F9FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F]",
        "", text,
    )


class _ReportPDF(FPDF):
    """PDF personalizado con header/footer."""

    def __init__(self, title: str = "Reporte"):
        super().__init__()
        self._report_title = title
        self.set_auto_page_break(auto=True, margin=20)
        _setup_font(self)

    def header(self):
        self.set_font(_FONT_NAME, "B", 9)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, _safe_text(self._report_title), align="L")
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font(_FONT_NAME, "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")


# Status icons as text fallback (PDF fonts don't support emojis)
_STATUS_TEXT = {
    "on_track": "[OK]",
    "at_risk": "[RIESGO]",
    "blocked": "[BLOQUEADO]",
    "completed": "[COMPLETADO]",
}


def report_to_pdf(data: dict, output_path: Path) -> Path:
    """
    Genera un PDF ejecutivo a partir del dict de reporte.

    Args:
        data: JSON del reporte (output de generate_report).
        output_path: Ruta donde guardar el PDF.

    Returns:
        Path del archivo PDF generado.
    """
    title = _safe_text(data.get("report_title", "Reporte Ejecutivo"))
    pdf = _ReportPDF(title=title)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Titulo ──
    pdf.set_font(_FONT_NAME, "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # ── Metadata ──
    pdf.set_font(_FONT_NAME, "", 10)
    pdf.set_text_color(80, 80, 80)
    period = data.get("period", "")
    count = data.get("meetings_count", 0)
    generated = data.get("_meta", {}).get("generated_at", "")[:10]
    pdf.cell(0, 6, f"Periodo: {period}  |  Reuniones: {count}  |  Generado: {generated}",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Resumen ejecutivo ──
    pdf.set_draw_color(200, 200, 200)
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font(_FONT_NAME, "I", 10)
    pdf.set_text_color(50, 50, 50)
    summary = _safe_text(data.get("executive_summary", ""))
    pdf.multi_cell(0, 6, summary, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ── Logros clave ──
    achievements = data.get("key_achievements", [])
    if achievements:
        _section_title(pdf, "Logros Clave")
        for a in achievements:
            _bullet(pdf, a)
        pdf.ln(4)

    # ── Progreso por proyecto ──
    projects = data.get("project_progress", [])
    if projects:
        _section_title(pdf, "Progreso por Proyecto")

        # Tabla resumen
        pdf.set_font(_FONT_NAME, "B", 9)
        pdf.set_fill_color(230, 230, 230)
        col_w = [120, 50]
        pdf.cell(col_w[0], 7, "Proyecto", border=1, fill=True)
        pdf.cell(col_w[1], 7, "Estado", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(_FONT_NAME, "", 9)
        for p in projects:
            status = p.get("status", "on_track")
            label = _STATUS_TEXT.get(status, status)
            pdf.cell(col_w[0], 6, _safe_text(p.get("project", "?")), border=1)
            pdf.cell(col_w[1], 6, label, border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Detalle por proyecto
        for p in projects:
            status = p.get("status", "on_track")
            label = _STATUS_TEXT.get(status, status)
            pdf.set_font(_FONT_NAME, "B", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.cell(0, 7, f"{label} {_safe_text(p.get('project', '?'))}", new_x="LMARGIN", new_y="NEXT")

            for h in p.get("highlights", []):
                _bullet(pdf, h)

            next_steps = p.get("next", [])
            if next_steps:
                _bullet(pdf, "Siguiente: " + "; ".join(next_steps))

            blockers = p.get("blockers", [])
            if blockers:
                pdf.set_text_color(180, 0, 0)
                _bullet(pdf, "Bloqueado: " + "; ".join(blockers))
                pdf.set_text_color(50, 50, 50)

            pdf.ln(2)

    # ── Decisiones ──
    decisions = data.get("decisions_summary", [])
    if decisions:
        _section_title(pdf, "Decisiones")
        for d in decisions:
            text = d.get("decision", "")
            owner = d.get("owner")
            if owner:
                text += f" ({owner})"
            _bullet(pdf, text)
        pdf.ln(4)

    # ── Riesgos ──
    risks = data.get("top_risks", [])
    if risks:
        _section_title(pdf, "Riesgos")
        pdf.set_text_color(180, 0, 0)
        for r in risks:
            _bullet(pdf, r)
        pdf.set_text_color(50, 50, 50)
        pdf.ln(4)

    # ── Recomendaciones ──
    recs = data.get("recommendations", [])
    if recs:
        _section_title(pdf, "Recomendaciones")
        for r in recs:
            _bullet(pdf, r)
        pdf.ln(4)

    # ── Footer ──
    meetings_files = data.get("_meta", {}).get("meetings_included", [])
    pdf.set_font(_FONT_NAME, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 6, f"Fuente: {len(meetings_files)} reuniones", new_x="LMARGIN", new_y="NEXT")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path


def _section_title(pdf: FPDF, text: str):
    """Agrega un titulo de seccion."""
    pdf.set_font(_FONT_NAME, "B", 12)
    pdf.set_text_color(30, 30, 100)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(30, 30, 100)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
    pdf.ln(3)
    pdf.set_text_color(50, 50, 50)


def _bullet(pdf: FPDF, text: str, bold_prefix: str = ""):
    """Agrega un bullet point."""
    pdf.set_font(_FONT_NAME, "", 9)
    safe = _safe_text(text)
    pdf.multi_cell(0, 5, f"  - {safe}", new_x="LMARGIN", new_y="NEXT")

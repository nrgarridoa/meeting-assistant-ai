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


def report_to_pdf(data: dict, output_path: Path, stats: dict | None = None) -> Path:
    """
    Genera un PDF ejecutivo a partir del dict de reporte.

    Args:
        data: JSON del reporte (output de generate_report).
        output_path: Ruta donde guardar el PDF.
        stats: Metricas calculadas (output de compute_stats). Opcional.
               Si se provee, agrega secciones de estado por proyecto,
               tareas bloqueadas y alertas de vencimiento.

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

    # ── Secciones de datos reales (requieren stats) ────────────────────────────
    if stats:
        # Estado por proyecto
        tasks_by_project = stats.get("tasks_by_project", {})
        if tasks_by_project:
            _section_title(pdf, "Estado de Tareas por Proyecto")
            col_w = [70, 22, 22, 22, 26, 26]
            headers = ["Proyecto", "Total", "Hecho", "En curso", "Bloqueado", "Pendiente"]
            pdf.set_font(_FONT_NAME, "B", 8)
            pdf.set_fill_color(230, 230, 230)
            for i, h in enumerate(headers):
                pdf.cell(col_w[i], 6, h, border=1, fill=True)
            pdf.ln()
            pdf.set_font(_FONT_NAME, "", 8)
            for proj, counts in sorted(tasks_by_project.items()):
                blocked_count = counts.get("blocked", 0)
                if blocked_count > 0:
                    pdf.set_text_color(180, 0, 0)
                else:
                    pdf.set_text_color(50, 50, 50)
                pdf.cell(col_w[0], 5, _safe_text(proj), border=1)
                pdf.set_text_color(50, 50, 50)
                pdf.cell(col_w[1], 5, str(counts.get("total", 0)), border=1, align="C")
                pdf.cell(col_w[2], 5, str(counts.get("done", 0)), border=1, align="C")
                pdf.cell(col_w[3], 5, str(counts.get("in_progress", 0)), border=1, align="C")
                # Bloqueado en rojo si > 0
                if blocked_count > 0:
                    pdf.set_text_color(180, 0, 0)
                pdf.cell(col_w[4], 5, str(blocked_count), border=1, align="C")
                pdf.set_text_color(50, 50, 50)
                pdf.cell(col_w[5], 5, str(counts.get("todo", 0)), border=1, align="C")
                pdf.ln()
            pdf.ln(4)

        # Tareas bloqueadas
        blocked_tasks = stats.get("blocked_tasks", [])
        if blocked_tasks:
            _section_title(pdf, f"Tareas Bloqueadas ({len(blocked_tasks)})")
            pdf.set_font(_FONT_NAME, "I", 9)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5, "Requieren accion inmediata para desbloquear el avance.",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            for t in blocked_tasks:
                pri = t.get("priority", "medium").upper()
                text = f"[{pri}] {t.get('task', '')}"
                if t.get("owner"):
                    text += f" — {t['owner']}"
                if t.get("project"):
                    text += f" ({t['project']})"
                pdf.set_text_color(180, 0, 0)
                _bullet(pdf, text)
                pdf.set_text_color(50, 50, 50)
            pdf.ln(4)

        # Alertas vencidas
        overdue = stats.get("overdue_tasks", [])
        if overdue:
            _section_title(pdf, f"Alertas — {len(overdue)} Tareas Vencidas o Estancadas")
            for t in overdue[:10]:
                pri = t.get("priority", "medium").upper()
                text = f"[{pri}] {t.get('task', '')[:65]}"
                if t.get("owner"):
                    text += f" — {t['owner']}"
                pdf.set_text_color(180, 60, 0)
                _bullet(pdf, text)
                pdf.set_text_color(100, 100, 100)
                _bullet(pdf, t.get("reason", ""))
                pdf.set_text_color(50, 50, 50)
            if len(overdue) > 10:
                pdf.set_font(_FONT_NAME, "I", 8)
                pdf.cell(0, 5, f"  ...y {len(overdue) - 10} tareas mas",
                         new_x="LMARGIN", new_y="NEXT")
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


# ─────────────────────────────────────────────
# STATS TO PDF — Dashboard de metricas
# ─────────────────────────────────────────────

def _draw_bar_chart(pdf: FPDF, data: dict, title: str, x: float, y: float, w: float, h: float,
                    colors: dict | None = None):
    """Dibuja un chart de barras horizontal simple con fpdf2."""
    if not data:
        return

    default_colors = {
        "high": (220, 50, 50), "medium": (230, 180, 40), "low": (100, 160, 100),
        "todo": (180, 180, 180), "in_progress": (70, 130, 200), "done": (60, 160, 80),
        "blocked": (220, 50, 50),
    }
    colors = colors or default_colors

    pdf.set_font(_FONT_NAME, "B", 9)
    pdf.set_text_color(30, 30, 100)
    pdf.set_xy(x, y)
    pdf.cell(w, 6, title, new_x="LMARGIN", new_y="NEXT")
    y += 7

    max_val = max(data.values()) if data else 1
    bar_h = min(6, h / max(len(data), 1) - 1)

    for label, count in data.items():
        bar_w = (count / max_val) * (w - 55) if max_val > 0 else 0

        # Label
        pdf.set_font(_FONT_NAME, "", 8)
        pdf.set_text_color(60, 60, 60)
        pdf.set_xy(x, y)
        pdf.cell(50, bar_h, _safe_text(str(label)[:15]))

        # Bar
        color = colors.get(label, (100, 140, 200))
        pdf.set_fill_color(*color)
        pdf.rect(x + 50, y, max(bar_w, 1), bar_h, "F")

        # Value
        pdf.set_xy(x + 52 + bar_w, y)
        pdf.cell(20, bar_h, str(count))

        y += bar_h + 1


def stats_to_pdf(stats: dict, output_path, comparison: dict | None = None) -> Path:
    """
    Genera un PDF con el dashboard de metricas.

    Args:
        stats: Dict retornado por compute_stats().
        output_path: Ruta del PDF.
        comparison: Dict retornado por compare_periods() (opcional).

    Returns:
        Path del PDF generado.
    """
    from datetime import datetime

    output_path = Path(output_path)
    project = stats.get("project_filter", "")
    title_suffix = f" — {project}" if project and project != "(todas)" else ""
    title = f"Dashboard de Metricas{title_suffix}"

    pdf = _ReportPDF(title=title)
    pdf.alias_nb_pages()
    pdf.add_page()

    # ── Titulo ──
    pdf.set_font(_FONT_NAME, "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, _safe_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_FONT_NAME, "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # ── KPIs principales ──
    _section_title(pdf, "Resumen General")
    kpis = [
        ("Reuniones", stats["meetings"]),
        ("Tareas", stats["total_tasks"]),
        ("Decisiones", stats["total_decisions"]),
        ("Riesgos", stats["total_risks"]),
        ("Speakers unicos", stats["unique_speakers"]),
        ("Completado", f"{stats['completion_rate']:.1f}%"),
    ]

    pdf.set_font(_FONT_NAME, "", 10)
    col_w = 190 / 3
    for i, (label, value) in enumerate(kpis):
        col = i % 3
        if col == 0 and i > 0:
            pdf.ln(12)
        x = 10 + col * col_w
        pdf.set_xy(x, pdf.get_y())
        pdf.set_font(_FONT_NAME, "B", 18)
        pdf.set_text_color(30, 30, 100)
        pdf.cell(col_w, 8, str(value), align="C")
        pdf.set_xy(x, pdf.get_y() + 8)
        pdf.set_font(_FONT_NAME, "", 8)
        pdf.set_text_color(100, 100, 100)
        pdf.cell(col_w, 5, label, align="C")
    pdf.ln(16)

    # ── Comparativa (si existe) ──
    if comparison:
        _section_title(pdf, "Comparativa vs Periodo Anterior")
        d = comparison["deltas"]
        prev = comparison["previous"]
        curr = comparison["current"]

        pdf.set_font(_FONT_NAME, "B", 8)
        pdf.set_fill_color(230, 230, 230)
        cols = [60, 35, 35, 35]
        pdf.cell(cols[0], 6, "Metrica", border=1, fill=True)
        pdf.cell(cols[1], 6, "Anterior", border=1, fill=True, align="C")
        pdf.cell(cols[2], 6, "Actual", border=1, fill=True, align="C")
        pdf.cell(cols[3], 6, "Cambio", border=1, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(_FONT_NAME, "", 8)
        rows = [
            ("Reuniones", prev["meetings"], curr["meetings"], d["meetings"]),
            ("Tareas", prev["total_tasks"], curr["total_tasks"], d["total_tasks"]),
            ("Decisiones", prev["total_decisions"], curr["total_decisions"], d["total_decisions"]),
            ("Riesgos", prev["total_risks"], curr["total_risks"], d["total_risks"]),
        ]
        for label, p, c, delta in rows:
            arrow = f"+{delta}" if delta > 0 else str(delta)
            if delta > 0:
                pdf.set_text_color(60, 160, 60)
            elif delta < 0:
                pdf.set_text_color(200, 60, 60)
            else:
                pdf.set_text_color(60, 60, 60)

            pdf.set_text_color(60, 60, 60)
            pdf.cell(cols[0], 5, label, border=1)
            pdf.cell(cols[1], 5, str(p), border=1, align="C")
            pdf.cell(cols[2], 5, str(c), border=1, align="C")
            # Color del delta
            if delta > 0:
                pdf.set_text_color(40, 140, 40)
            elif delta < 0:
                pdf.set_text_color(200, 50, 50)
            pdf.cell(cols[3], 5, arrow, border=1, align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(60, 60, 60)

        # Completion rate
        cr_delta = d["completion_rate"]
        cr_arrow = f"+{cr_delta}" if cr_delta > 0 else str(cr_delta)
        pdf.cell(cols[0], 5, "Completado (%)", border=1)
        pdf.cell(cols[1], 5, f"{prev['completion_rate']:.1f}%", border=1, align="C")
        pdf.cell(cols[2], 5, f"{curr['completion_rate']:.1f}%", border=1, align="C")
        if cr_delta > 0:
            pdf.set_text_color(40, 140, 40)
        elif cr_delta < 0:
            pdf.set_text_color(200, 50, 50)
        pdf.cell(cols[3], 5, f"{cr_arrow}%", border=1, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(60, 60, 60)
        pdf.ln(6)

    # ── Charts ──
    y_pos = pdf.get_y()
    if y_pos > 220:
        pdf.add_page()
        y_pos = pdf.get_y()

    _draw_bar_chart(pdf, stats["tasks_by_status"], "Estado de tareas",
                    10, y_pos, 90, 40)
    _draw_bar_chart(pdf, stats["tasks_by_priority"], "Prioridad de tareas",
                    105, y_pos, 90, 40)

    pdf.set_y(y_pos + 45)

    # Top owners
    if stats["top_owners"]:
        owners_dict = dict(stats["top_owners"][:8])
        _draw_bar_chart(pdf, owners_dict, "Carga por responsable",
                        10, pdf.get_y(), 90, 55)

    # Top areas
    if stats["tasks_by_area"]:
        _draw_bar_chart(pdf, dict(list(stats["tasks_by_area"].items())[:8]),
                        "Tareas por area",
                        105, pdf.get_y() if not stats["top_owners"] else pdf.get_y() - 55,
                        90, 55)

    # Ajustar Y despues de los charts
    if stats["top_owners"] or stats["tasks_by_area"]:
        pdf.set_y(pdf.get_y() + 10 if not stats["top_owners"] else pdf.get_y() + 5)

    # ── Tareas vencidas ──
    overdue = stats.get("overdue_tasks", [])
    if overdue:
        if pdf.get_y() > 230:
            pdf.add_page()
        _section_title(pdf, f"Alertas — {len(overdue)} tareas vencidas/estancadas")
        pdf.set_font(_FONT_NAME, "", 8)
        pdf.set_fill_color(255, 240, 240)
        for t in overdue[:15]:
            pri = t.get("priority", "medium")
            tag = f"[{pri.upper()}]" if pri == "high" else f"[{pri}]"
            text = f"{tag} {t.get('task', '?')[:50]} — {t.get('owner', '?')}"
            pdf.set_text_color(160, 30, 30)
            pdf.multi_cell(0, 4, f"  {_safe_text(text)}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(120, 80, 80)
            pdf.multi_cell(0, 4, f"      {t.get('reason', '')}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(50, 50, 50)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    return output_path

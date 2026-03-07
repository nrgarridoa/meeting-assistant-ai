"""
Generacion de reportes semanales y mensuales consolidados.

Carga los JSONs estructurados de outputs/, filtra por rango de fechas,
y usa Gemini para sintetizar un reporte ejecutivo listo para CEO.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from google.genai import types
from .rate_limit import call_with_key_rotation


# ─────────────────────────────────────────────
# PARSEO DE FECHAS
# ─────────────────────────────────────────────

def _parse_date_from_filename(stem: str) -> datetime | None:
    """
    Extrae fecha del prefijo YYMMDD del nombre de archivo.
    Ej: '260304_daily' -> datetime(2026, 3, 4)
    """
    m = re.match(r"^(\d{6})_", stem)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%y%m%d")
    except ValueError:
        return None


_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_date_from_json(date_str: str | None) -> datetime | None:
    """
    Parsea fechas en formato natural del JSON.
    Ej: '4 de marzo de 2026' -> datetime(2026, 3, 4)
    """
    if not date_str:
        return None
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", date_str.strip(), re.I)
    if not m:
        return None
    day = int(m.group(1))
    month = _MONTHS_ES.get(m.group(2).lower())
    year = int(m.group(3))
    if not month:
        return None
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def get_meeting_date(json_path: Path, data: dict) -> datetime | None:
    """Obtiene la fecha de una reunion: primero del filename, luego del JSON."""
    date = _parse_date_from_filename(json_path.stem.replace("_structured", ""))
    if date:
        return date
    return _parse_date_from_json(data.get("date"))


# ─────────────────────────────────────────────
# CARGA Y FILTRADO
# ─────────────────────────────────────────────

def load_all_meetings(out_dir: Path) -> list[dict]:
    """
    Carga todos los JSONs estructurados de out_dir.
    Cada dict incluye '_source_file' y '_date' (datetime o None).
    Ordenados por fecha (los sin fecha van al final).
    """
    meetings = []
    for p in sorted(out_dir.glob("*_structured.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_source_file"] = p.name
            data["_date"] = get_meeting_date(p, data)
            meetings.append(data)
        except Exception as e:
            print(f"  Advertencia: no se pudo cargar {p.name}: {e}")

    meetings.sort(key=lambda m: (m["_date"] is None, m["_date"] or datetime.max))
    return meetings


def filter_by_date_range(
    meetings: list[dict],
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Filtra reuniones dentro del rango [date_from, date_to] inclusive."""
    filtered = []
    for m in meetings:
        d = m.get("_date")
        if d and date_from <= d <= date_to:
            filtered.append(m)
    return filtered


def get_week_range(ref_date: datetime) -> tuple[datetime, datetime]:
    """Retorna (lunes, domingo) de la semana que contiene ref_date."""
    monday = ref_date - timedelta(days=ref_date.weekday())
    sunday = monday + timedelta(days=6)
    return (
        monday.replace(hour=0, minute=0, second=0, microsecond=0),
        sunday.replace(hour=23, minute=59, second=59, microsecond=0),
    )


def get_month_range(ref_date: datetime) -> tuple[datetime, datetime]:
    """Retorna (primer dia, ultimo dia) del mes que contiene ref_date."""
    first = ref_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if ref_date.month == 12:
        last = ref_date.replace(year=ref_date.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        last = ref_date.replace(month=ref_date.month + 1, day=1) - timedelta(days=1)
    return first, last.replace(hour=23, minute=59, second=59, microsecond=0)


# ─────────────────────────────────────────────
# PREPARACION DEL CONTEXTO PARA GEMINI
# ─────────────────────────────────────────────

def _summarize_meeting_for_prompt(m: dict) -> str:
    """Convierte un JSON de reunion a texto compacto para el prompt."""
    lines = []
    date_str = m.get("date") or (m["_date"].strftime("%Y-%m-%d") if m.get("_date") else "sin fecha")
    lines.append(f"## {m.get('meeting_title', 'Reunion')} ({date_str})")
    lines.append(f"Archivo: {m.get('_source_file', '?')}")

    # Speakers
    speakers = [s.get("name", "?") for s in m.get("speakers", [])]
    if speakers:
        lines.append(f"Participantes: {', '.join(speakers)}")

    # Summary
    for b in m.get("summary_top_bullets", []):
        lines.append(f"- {b}")

    # Topics
    for t in m.get("topics", []):
        lines.append(f"\n### {t.get('name', '')}")
        for b in t.get("bullets", []):
            lines.append(f"  - {b}")

    # Decisions
    decisions = m.get("decisions", [])
    if decisions:
        lines.append("\n### Decisiones")
        for d in decisions:
            owner = d.get("owner") or ""
            line = f"  - {d.get('decision', '')}"
            if owner:
                line += f" (Owner: {owner})"
            lines.append(line)

    # Action items
    actions = m.get("action_items", [])
    if actions:
        lines.append("\n### Tareas")
        for a in actions:
            line = f"  - [{a.get('priority','?')}/{a.get('status','?')}] {a.get('task','')}"
            if a.get("owner"):
                line += f" → {a['owner']}"
            if a.get("area"):
                line += f" ({a['area']})"
            lines.append(line)

    # Risks
    risks = m.get("risks_blockers", [])
    if risks:
        lines.append("\n### Riesgos/Bloqueos")
        for r in risks:
            lines.append(f"  - {r}")

    return "\n".join(lines)


def _build_previous_context(prev_meetings: list[dict]) -> str:
    """Resume el periodo anterior para comparacion."""
    if not prev_meetings:
        return ""

    lines = ["CONTEXTO DEL PERIODO ANTERIOR (para comparacion de progreso):"]
    for m in prev_meetings:
        date_str = m.get("date") or (m["_date"].strftime("%Y-%m-%d") if m.get("_date") else "sin fecha")
        lines.append(f"\n- {m.get('meeting_title', 'Reunion')} ({date_str})")
        for t in m.get("topics", []):
            lines.append(f"  Tema: {t.get('name', '')}")
            for b in t.get("bullets", [])[:2]:
                lines.append(f"    - {b}")
        for a in m.get("action_items", []):
            lines.append(f"  Tarea: [{a.get('status','?')}] {a.get('task','')}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# PROMPT Y GENERACION
# ─────────────────────────────────────────────

REPORT_PROMPT = """
Eres un asistente ejecutivo. Genera un reporte BREVE para gerencia/CEO.
Gerencia NO lee textos largos. Cada bullet debe ser UNA linea corta y concreta.

PERIODO: {period_label}
REUNIONES: {n_meetings}

{previous_context}

DATOS:
\"\"\"
{meetings_text}
\"\"\"

Genera JSON con esta estructura:

{{
  "report_title": "string (ej: Reporte Semanal 03-07 Mar 2026)",
  "period": "string",
  "executive_summary": "string - MAXIMO 2-3 oraciones. Solo lo esencial.",
  "meetings_count": number,
  "key_achievements": ["string - maximo 5 logros TANGIBLES, 1 linea cada uno"],
  "project_progress": [
    {{
      "project": "string - nombre del proyecto",
      "status": "on_track|at_risk|blocked|completed",
      "highlights": ["string - maximo 3 avances clave, 1 linea cada uno"],
      "next": ["string - maximo 2 proximos pasos criticos"],
      "blockers": ["string - solo si existen, 1 linea"]
    }}
  ],
  "decisions_summary": [
    {{
      "decision": "string - 1 linea",
      "owner": "string|null"
    }}
  ],
  "top_risks": ["string - maximo 5 riesgos criticos, 1 linea cada uno"],
  "recommendations": ["string - maximo 3 recomendaciones accionables"]
}}

Reglas ESTRICTAS:
- BREVEDAD ante todo. Si puedes decirlo en menos palabras, hazlo.
- project_progress: agrupa por proyecto, NO por reunion. Solo incluye proyectos con actividad real.
- key_achievements: logros CONCRETOS, no "se discutio X" o "se reviso Y".
- decisions_summary: solo decisiones con impacto real, no detalles operativos.
- top_risks: solo riesgos que afectan resultados. NO listar inconvenientes menores.
- NO incluir team_workload ni next_period_outlook (gerencia no lo necesita en el reporte).
- NO inventes informacion.
- Idioma: espanol.
- Devuelve SOLO JSON valido.
""".strip()


def generate_report(
    client,
    model: str,
    key_manager,
    meetings: list[dict],
    period_label: str,
    previous_meetings: list[dict] | None = None,
) -> dict:
    """
    Genera un reporte ejecutivo consolidando multiples reuniones.

    Args:
        client: genai.Client.
        model: Nombre del modelo Gemini.
        key_manager: KeyManager.
        meetings: Lista de JSONs estructurados del periodo actual.
        period_label: Ej: "Semana 03-07 Mar 2026" o "Marzo 2026".
        previous_meetings: Reuniones del periodo anterior (para comparacion).

    Returns:
        dict con el reporte estructurado.
    """
    if not meetings:
        raise ValueError("No hay reuniones para generar el reporte.")

    meetings_text = "\n\n---\n\n".join(
        _summarize_meeting_for_prompt(m) for m in meetings
    )

    previous_context = ""
    if previous_meetings:
        previous_context = _build_previous_context(previous_meetings)

    prompt = REPORT_PROMPT.format(
        period_label=period_label,
        n_meetings=len(meetings),
        previous_context=previous_context,
        meetings_text=meetings_text,
    )

    resp = call_with_key_rotation(
        client=client, model=model, key_manager=key_manager,
        fn_builder=lambda c: (lambda: c.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.3
            )
        ))
    )

    raw = (resp.text or "").strip()

    # Extraer JSON
    from .extract_structured import extract_json
    candidate = extract_json(raw) or raw

    data = json.loads(candidate)
    data["_meta"] = {
        "period": period_label,
        "meetings_included": [m.get("_source_file", "?") for m in meetings],
        "generated_at": datetime.now().isoformat(),
        "had_previous_context": bool(previous_meetings),
    }
    return data


# ─────────────────────────────────────────────
# EXPORT MARKDOWN
# ─────────────────────────────────────────────

_STATUS_ICONS = {
    "on_track": "🟢",
    "at_risk": "🟡",
    "blocked": "🔴",
    "completed": "✅",
}


def report_to_markdown(data: dict) -> str:
    """Convierte el JSON del reporte a Markdown ejecutivo breve para gerencia."""
    lines = []
    generated = data.get("_meta", {}).get("generated_at", "")
    meetings_files = data.get("_meta", {}).get("meetings_included", [])

    # Header
    lines.append(f"# {data.get('report_title', 'Reporte')}")
    lines.append(f"**Periodo:** {data.get('period', '')}  |  "
                 f"**Reuniones:** {data.get('meetings_count', len(meetings_files))}"
                 + (f"  |  **Generado:** {generated[:10]}" if generated else ""))
    lines.append("")

    # Executive summary
    lines.append(f"> {data.get('executive_summary', '')}")
    lines.append("")

    # Key achievements
    achievements = data.get("key_achievements", [])
    if achievements:
        lines.append("## Logros Clave")
        for a in achievements:
            lines.append(f"- {a}")
        lines.append("")

    # Project progress — tabla resumen + detalle compacto
    projects = data.get("project_progress", [])
    if projects:
        lines.append("## Progreso por Proyecto")
        lines.append("")
        lines.append("| Proyecto | Estado |")
        lines.append("|---|---|")
        for p in projects:
            status = p.get("status", "on_track")
            icon = _STATUS_ICONS.get(status, "⚪")
            lines.append(f"| {p.get('project', '?')} | {icon} {status} |")
        lines.append("")

        for p in projects:
            status = p.get("status", "on_track")
            icon = _STATUS_ICONS.get(status, "⚪")
            lines.append(f"### {icon} {p.get('project', 'Proyecto')}")

            for h in p.get("highlights", []):
                lines.append(f"- {h}")

            next_steps = p.get("next", [])
            if next_steps:
                lines.append(f"- **Siguiente:** {'; '.join(next_steps)}")

            blockers = p.get("blockers", [])
            if blockers:
                lines.append(f"- **Bloqueado:** {'; '.join(blockers)}")

            lines.append("")

    # Decisions
    decisions = data.get("decisions_summary", [])
    if decisions:
        lines.append("## Decisiones")
        for d in decisions:
            owner = d.get("owner") or ""
            line = f"- {d.get('decision', '')}"
            if owner:
                line += f" _({owner})_"
            lines.append(line)
        lines.append("")

    # Risks
    risks = data.get("top_risks", [])
    if risks:
        lines.append("## Riesgos")
        for r in risks:
            lines.append(f"- {r}")
        lines.append("")

    # Recommendations
    recs = data.get("recommendations", [])
    if recs:
        lines.append("## Recomendaciones")
        for r in recs:
            lines.append(f"- {r}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"_Fuente: {len(meetings_files)} reuniones_")

    return "\n".join(lines)

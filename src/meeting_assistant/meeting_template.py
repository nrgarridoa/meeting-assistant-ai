"""
Generacion de templates/agendas para la siguiente reunion.

Analiza open_questions, next_steps y tareas pendientes del periodo actual
para sugerir una agenda estructurada.
"""

from datetime import datetime
from pathlib import Path

from .stats import sort_tasks


def generate_template(
    meetings: list[dict],
    meeting_type: str = "daily",
    ref_date: datetime | None = None,
) -> str:
    """
    Genera un template de agenda basado en pendientes de reuniones anteriores.

    Args:
        meetings: Lista de reuniones procesadas (JSONs).
        meeting_type: Tipo de reunion (daily, semanal, proyecto).
        ref_date: Fecha de referencia (default: hoy).

    Returns:
        Agenda en Markdown.
    """
    ref = ref_date or datetime.now()
    date_str = ref.strftime("%Y-%m-%d")

    # Recopilar pendientes
    pending_tasks = []
    open_questions = []
    next_steps = []
    recent_decisions = []
    risks = []

    for m in meetings:
        for a in m.get("action_items", []):
            if a.get("status") in ("todo", "in_progress", "blocked"):
                task = dict(a)
                task["_meeting"] = m.get("meeting_title", "?")
                pending_tasks.append(task)

        open_questions.extend(m.get("open_questions", []))
        next_steps.extend(m.get("next_steps", []))

        for d in m.get("decisions", []):
            recent_decisions.append(d)

        risks.extend(m.get("risks_blockers", []))

    # Ordenar tareas por urgencia
    pending_tasks = sort_tasks(pending_tasks)

    # Deduplicar listas
    open_questions = list(dict.fromkeys(open_questions))
    next_steps = list(dict.fromkeys(next_steps))
    risks = list(dict.fromkeys(risks))

    # Generar template segun tipo
    if meeting_type == "daily":
        return _daily_template(date_str, pending_tasks, risks)
    elif meeting_type == "semanal":
        return _weekly_template(date_str, pending_tasks, open_questions, next_steps, recent_decisions, risks)
    else:
        return _project_template(date_str, meeting_type, pending_tasks, open_questions, next_steps, risks)


def _daily_template(
    date_str: str,
    tasks: list[dict],
    risks: list[str],
) -> str:
    """Template para daily standup."""
    lines = [
        f"# Daily Standup — {date_str}",
        "",
        "## Asistentes",
        "- [ ] ...",
        "",
        "---",
        "",
        "## Revision de tareas pendientes",
        "",
    ]

    # Agrupar por owner
    by_owner: dict[str, list[dict]] = {}
    for t in tasks:
        owner = t.get("owner") or "Sin asignar"
        by_owner.setdefault(owner, []).append(t)

    if by_owner:
        for owner, owner_tasks in sorted(by_owner.items()):
            lines.append(f"### {owner}")
            for t in owner_tasks[:5]:
                status = t.get("status", "todo")
                pri = t.get("priority", "medium")
                tag = f"[{pri.upper()}]" if pri == "high" else f"[{pri}]"
                lines.append(f"- [ ] {tag} {t.get('task', '?')}")
                lines.append(f"      Status: {status} | Avance: ___")
            lines.append("")
    else:
        lines.append("- Sin tareas pendientes registradas")
        lines.append("")

    lines.extend([
        "## Bloqueos",
    ])
    if risks:
        for r in risks[:5]:
            lines.append(f"- {r}")
    else:
        lines.append("- (ninguno reportado)")

    lines.extend([
        "",
        "## Nuevos compromisos",
        "- [ ] ...",
        "",
        "---",
        f"*Template generado el {date_str}*",
    ])

    return "\n".join(lines)


def _weekly_template(
    date_str: str,
    tasks: list[dict],
    questions: list[str],
    next_steps: list[str],
    decisions: list[dict],
    risks: list[str],
) -> str:
    """Template para reunion semanal."""
    lines = [
        f"# Reunion Semanal — {date_str}",
        "",
        "## Asistentes",
        "- [ ] ...",
        "",
        "---",
        "",
        "## 1. Revision de la semana anterior",
        "",
    ]

    # Tareas de alta prioridad
    high = [t for t in tasks if t.get("priority") == "high"]
    if high:
        lines.append("### Tareas de alta prioridad")
        for t in high[:10]:
            status = t.get("status", "todo")
            owner = t.get("owner") or "?"
            lines.append(f"- [ ] {t.get('task', '?')} — {owner} [{status}]")
        lines.append("")

    # Blocked
    blocked = [t for t in tasks if t.get("status") == "blocked"]
    if blocked:
        lines.append("### Tareas bloqueadas")
        for t in blocked[:5]:
            owner = t.get("owner") or "?"
            lines.append(f"- [ ] {t.get('task', '?')} — {owner}")
        lines.append("")

    # Decisiones recientes a revisar
    if decisions:
        lines.append("### Decisiones recientes (seguimiento)")
        for d in decisions[:5]:
            text = d.get("decision", "?")
            owner = d.get("owner")
            lines.append(f"- {text}" + (f" ({owner})" if owner else ""))
        lines.append("")

    lines.extend([
        "## 2. Preguntas abiertas",
        "",
    ])
    if questions:
        for q in questions[:8]:
            lines.append(f"- [ ] {q}")
    else:
        lines.append("- (ninguna pendiente)")

    lines.extend([
        "",
        "## 3. Plan para la proxima semana",
        "",
    ])
    if next_steps:
        for n in next_steps[:8]:
            lines.append(f"- [ ] {n}")
    else:
        lines.append("- (definir en la reunion)")

    lines.extend([
        "",
        "## 4. Riesgos y bloqueos",
        "",
    ])
    if risks:
        for r in risks[:5]:
            lines.append(f"- {r}")
    else:
        lines.append("- (ninguno)")

    lines.extend([
        "",
        "## 5. Nuevos compromisos",
        "- [ ] ...",
        "",
        "---",
        f"*Template generado el {date_str}*",
    ])

    return "\n".join(lines)


def _project_template(
    date_str: str,
    project_name: str,
    tasks: list[dict],
    questions: list[str],
    next_steps: list[str],
    risks: list[str],
) -> str:
    """Template para reunion de proyecto especifico."""
    lines = [
        f"# Reunion Proyecto: {project_name} — {date_str}",
        "",
        "## Asistentes",
        "- [ ] ...",
        "",
        "---",
        "",
        f"## Estado del Proyecto",
        "- Estado general: ___",
        "- Avance estimado: ___%",
        "",
        "## Tareas pendientes",
        "",
    ]

    if tasks:
        for t in tasks[:15]:
            status = t.get("status", "todo")
            pri = t.get("priority", "medium")
            owner = t.get("owner") or "?"
            tag = f"[{pri.upper()}]" if pri == "high" else f"[{pri}]"
            lines.append(f"- [ ] {tag} {t.get('task', '?')} — {owner} [{status}]")
    else:
        lines.append("- Sin tareas pendientes")

    lines.extend([
        "",
        "## Preguntas abiertas",
        "",
    ])
    if questions:
        for q in questions[:5]:
            lines.append(f"- [ ] {q}")
    else:
        lines.append("- (ninguna)")

    lines.extend([
        "",
        "## Proximos pasos",
        "",
    ])
    if next_steps:
        for n in next_steps[:5]:
            lines.append(f"- [ ] {n}")
    else:
        lines.append("- (definir)")

    lines.extend([
        "",
        "## Riesgos",
        "",
    ])
    if risks:
        for r in risks[:5]:
            lines.append(f"- {r}")
    else:
        lines.append("- (ninguno)")

    lines.extend([
        "",
        "## Nuevos compromisos",
        "- [ ] ...",
        "",
        "---",
        f"*Template generado el {date_str}*",
    ])

    return "\n".join(lines)

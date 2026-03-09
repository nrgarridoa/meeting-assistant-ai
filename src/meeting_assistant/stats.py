"""
Dashboard de metricas — calculo puro sobre JSONs, 0 requests a Gemini.
"""

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime

from .report import load_all_meetings, filter_by_date_range


# ── Prioridad de atencion para ordenar tareas ──
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_STATUS_ORDER = {"blocked": 0, "in_progress": 1, "todo": 2, "done": 3}


def _normalize_speakers(raw_names: set[str]) -> list[str]:
    """
    Deduplica nombres de speakers usando similitud fuzzy.
    Agrupa variantes como 'Harold' / 'Harold Mayta' y usa el nombre más largo.
    Descarta placeholders como 'Participante 1'.
    """
    names = [n for n in raw_names if not n.lower().startswith("participante")]
    if not names:
        return []

    groups: list[list[str]] = []
    used = set()
    sorted_names = sorted(names, key=len, reverse=True)

    for name in sorted_names:
        if name in used:
            continue
        group = [name]
        used.add(name)
        for other in sorted_names:
            if other in used:
                continue
            ratio = SequenceMatcher(None, name.lower(), other.lower()).ratio()
            name_lower, other_lower = name.lower(), other.lower()
            contains = other_lower in name_lower or name_lower in other_lower
            if contains or ratio >= 0.8:
                group.append(other)
                used.add(other)
        groups.append(group)

    return sorted(group[0] for group in groups)


def _filter_by_project(meetings: list[dict], project: str) -> list[dict]:
    """Filtra reuniones que contienen tareas del proyecto indicado."""
    if not project:
        return meetings
    project_lower = project.lower()
    filtered = []
    for m in meetings:
        # Filtrar action_items por proyecto (inferido de meeting title o source file)
        source = m.get("_source_file", "").lower()
        title = m.get("meeting_title", "").lower()
        text = f"{source} {title}"
        if project_lower in text:
            filtered.append(m)
            continue
        # Revisar si alguna tarea tiene el proyecto (campo de Notion sync)
        for a in m.get("action_items", []):
            evidence = (a.get("evidence") or "").lower()
            task_text = (a.get("task") or "").lower()
            if project_lower in evidence or project_lower in task_text:
                filtered.append(m)
                break
    return filtered


def sort_tasks(tasks: list[dict]) -> list[dict]:
    """
    Ordena tareas por urgencia de atencion:
    1. Prioridad: high > medium > low
    2. Status: blocked > in_progress > todo > done
    3. Tareas vencidas primero
    """
    now = datetime.now()

    def sort_key(t):
        pri = _PRIORITY_ORDER.get(t.get("priority", "medium"), 1)
        sta = _STATUS_ORDER.get(t.get("status", "todo"), 2)
        # Tareas vencidas van primero (0), no vencidas despues (1)
        overdue = 1
        due = t.get("due_date")
        if due and t.get("status") not in ("done",):
            try:
                due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
                if due_dt < now:
                    overdue = 0
            except (ValueError, TypeError):
                pass
        return (overdue, pri, sta)

    return sorted(tasks, key=sort_key)


def get_overdue_tasks(meetings: list[dict], ref_date: datetime | None = None) -> list[dict]:
    """
    Detecta tareas vencidas o pendientes con demasiada antiguedad.

    Una tarea se considera vencida si:
    - Tiene due_date y ya paso, con status != done
    - No tiene due_date pero tiene mas de 14 dias desde la reunion y status == todo
    """
    ref = ref_date or datetime.now()
    overdue = []

    for m in meetings:
        meeting_date = m.get("_date")
        for a in m.get("action_items", []):
            if a.get("status") == "done":
                continue

            reason = ""
            due = a.get("due_date")

            if due:
                try:
                    due_dt = datetime.strptime(due[:10], "%Y-%m-%d")
                    if due_dt < ref:
                        days_late = (ref - due_dt).days
                        reason = f"Vencida hace {days_late} dias (due: {due[:10]})"
                except (ValueError, TypeError):
                    pass
            elif meeting_date and a.get("status") == "todo":
                days_old = (ref - meeting_date).days
                if days_old > 14:
                    reason = f"Pendiente hace {days_old} dias sin avance"

            if reason:
                overdue.append({
                    "task": a.get("task", ""),
                    "owner": a.get("owner", "Sin asignar"),
                    "priority": a.get("priority", "medium"),
                    "status": a.get("status", "todo"),
                    "reason": reason,
                    "source": m.get("_source_file", "?"),
                })

    return sort_tasks(overdue)


def compute_stats(meetings: list[dict], project: str = "") -> dict:
    """
    Calcula metricas consolidadas de una lista de reuniones.
    Si project != "", filtra solo tareas relacionadas al proyecto.
    """
    if project:
        meetings = _filter_by_project(meetings, project)

    total_meetings = len(meetings)
    all_actions = []
    all_decisions = []
    all_risks = []
    raw_speakers = set()
    tasks_by_owner = Counter()
    tasks_by_status = Counter()
    tasks_by_priority = Counter()
    tasks_by_area = Counter()
    tasks_by_project = Counter()

    for m in meetings:
        for s in m.get("speakers", []):
            name = s.get("name", "").strip()
            if name:
                raw_speakers.add(name)

        for a in m.get("action_items", []):
            all_actions.append(a)
            owner = a.get("owner") or "Sin asignar"
            tasks_by_owner[owner] += 1
            tasks_by_status[a.get("status", "todo")] += 1
            tasks_by_priority[a.get("priority", "medium")] += 1
            tasks_by_area[a.get("area", "general")] += 1

        all_decisions.extend(m.get("decisions", []))
        all_risks.extend(m.get("risks_blockers", []))

    speakers_deduped = _normalize_speakers(raw_speakers)
    top_owners = tasks_by_owner.most_common(10)

    # Ordenar todas las tareas por urgencia
    sorted_actions = sort_tasks(all_actions)

    # Tareas vencidas
    overdue = get_overdue_tasks(meetings)

    return {
        "meetings": total_meetings,
        "total_tasks": len(all_actions),
        "total_decisions": len(all_decisions),
        "total_risks": len(all_risks),
        "unique_speakers": len(speakers_deduped),
        "speakers_list": speakers_deduped,
        "tasks_by_status": dict(tasks_by_status),
        "tasks_by_priority": dict(tasks_by_priority),
        "tasks_by_area": dict(tasks_by_area.most_common(10)),
        "top_owners": top_owners,
        "completion_rate": (
            tasks_by_status.get("done", 0) / len(all_actions) * 100
            if all_actions else 0
        ),
        "overdue_tasks": overdue,
        "sorted_tasks": sorted_actions,
        "project_filter": project or "(todas)",
    }


def compare_periods(
    current_meetings: list[dict],
    previous_meetings: list[dict],
    project: str = "",
) -> dict:
    """
    Compara metricas entre dos periodos.

    Returns:
        dict con current, previous, y deltas.
    """
    curr = compute_stats(current_meetings, project)
    prev = compute_stats(previous_meetings, project)

    def delta(key):
        return curr.get(key, 0) - prev.get(key, 0)

    def delta_pct(key):
        p = prev.get(key, 0)
        c = curr.get(key, 0)
        if p == 0:
            return 100.0 if c > 0 else 0.0
        return ((c - p) / p) * 100

    return {
        "current": curr,
        "previous": prev,
        "deltas": {
            "meetings": delta("meetings"),
            "total_tasks": delta("total_tasks"),
            "total_decisions": delta("total_decisions"),
            "total_risks": delta("total_risks"),
            "completion_rate": round(curr["completion_rate"] - prev["completion_rate"], 1),
        },
        "pct_change": {
            "tasks": round(delta_pct("total_tasks"), 1),
            "decisions": round(delta_pct("total_decisions"), 1),
            "completion_rate": round(
                curr["completion_rate"] - prev["completion_rate"], 1
            ),
        },
    }


def comparison_to_text(comp: dict) -> str:
    """Formatea la comparativa entre periodos como texto."""
    curr = comp["current"]
    prev = comp["previous"]
    d = comp["deltas"]
    lines = []

    def arrow(val):
        if val > 0:
            return f"+{val}"
        return str(val)

    lines.append("  Comparativa entre periodos:")
    lines.append(f"  {'Metrica':<25s} {'Anterior':>10s} {'Actual':>10s} {'Cambio':>10s}")
    lines.append(f"  {'-'*55}")
    lines.append(f"  {'Reuniones':<25s} {prev['meetings']:>10d} {curr['meetings']:>10d} {arrow(d['meetings']):>10s}")
    lines.append(f"  {'Tareas':<25s} {prev['total_tasks']:>10d} {curr['total_tasks']:>10d} {arrow(d['total_tasks']):>10s}")
    lines.append(f"  {'Decisiones':<25s} {prev['total_decisions']:>10d} {curr['total_decisions']:>10d} {arrow(d['total_decisions']):>10s}")
    lines.append(f"  {'Riesgos':<25s} {prev['total_risks']:>10d} {curr['total_risks']:>10d} {arrow(d['total_risks']):>10s}")
    lines.append(f"  {'Completado (%)':<25s} {prev['completion_rate']:>9.1f}% {curr['completion_rate']:>9.1f}% {arrow(d['completion_rate']):>9s}%")

    return "\n".join(lines)


def stats_to_text(stats: dict) -> str:
    """Formatea las metricas como texto legible para terminal."""
    lines = []
    if stats.get("project_filter") and stats["project_filter"] != "(todas)":
        lines.append(f"  Proyecto: {stats['project_filter']}")
    lines.append(f"  Reuniones: {stats['meetings']}")
    lines.append(f"  Participantes unicos: {stats['unique_speakers']}")
    lines.append(f"  Total tareas: {stats['total_tasks']}")
    lines.append(f"  Total decisiones: {stats['total_decisions']}")
    lines.append(f"  Total riesgos: {stats['total_risks']}")
    lines.append(f"  Tasa de completado: {stats['completion_rate']:.1f}%")

    lines.append("\n  Estado de tareas:")
    for status, count in sorted(stats["tasks_by_status"].items()):
        lines.append(f"    {status}: {count}")

    lines.append("\n  Prioridad de tareas:")
    for priority, count in sorted(stats["tasks_by_priority"].items()):
        lines.append(f"    {priority}: {count}")

    lines.append("\n  Top owners (por carga):")
    for owner, count in stats["top_owners"]:
        lines.append(f"    {owner}: {count} tareas")

    lines.append("\n  Top areas:")
    for area, count in stats["tasks_by_area"].items():
        lines.append(f"    {area}: {count}")

    # Alertas de tareas vencidas
    overdue = stats.get("overdue_tasks", [])
    if overdue:
        lines.append(f"\n  ALERTAS — {len(overdue)} tareas vencidas/estancadas:")
        for t in overdue[:15]:
            pri_tag = f"[{t['priority'].upper()}]" if t["priority"] == "high" else f"[{t['priority']}]"
            lines.append(f"    {pri_tag} {t['task'][:55]}")
            lines.append(f"          Owner: {t['owner']} | {t['reason']}")
        if len(overdue) > 15:
            lines.append(f"    ... y {len(overdue) - 15} mas")

    return "\n".join(lines)

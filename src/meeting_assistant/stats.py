"""
Dashboard de metricas — calculo puro sobre JSONs, 0 requests a Gemini.
"""

import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime

from .report import load_all_meetings, filter_by_date_range


def _normalize_speakers(raw_names: set[str]) -> list[str]:
    """
    Deduplica nombres de speakers usando similitud fuzzy.
    Agrupa variantes como 'Harold' / 'Harold Mayta' y usa el nombre más largo.
    Descarta placeholders como 'Participante 1'.
    """
    # Filtrar placeholders
    names = [n for n in raw_names if not n.lower().startswith("participante")]
    if not names:
        return []

    # Agrupar por similitud
    groups: list[list[str]] = []
    used = set()

    # Ordenar por largo (más largo primero) para que sea el representante del grupo
    sorted_names = sorted(names, key=len, reverse=True)

    for name in sorted_names:
        if name in used:
            continue
        group = [name]
        used.add(name)
        for other in sorted_names:
            if other in used:
                continue
            # Match si uno contiene al otro o alta similitud
            ratio = SequenceMatcher(None, name.lower(), other.lower()).ratio()
            name_lower, other_lower = name.lower(), other.lower()
            contains = other_lower in name_lower or name_lower in other_lower
            if contains or ratio >= 0.8:
                group.append(other)
                used.add(other)
        groups.append(group)

    # Representante de cada grupo: el nombre más largo (más completo)
    return sorted(group[0] for group in groups)


def compute_stats(meetings: list[dict]) -> dict:
    """
    Calcula metricas consolidadas de una lista de reuniones.

    Returns:
        dict con todas las metricas.
    """
    total_meetings = len(meetings)
    all_actions = []
    all_decisions = []
    all_risks = []
    raw_speakers = set()
    tasks_by_owner = Counter()
    tasks_by_status = Counter()
    tasks_by_priority = Counter()
    tasks_by_area = Counter()

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

    # Deduplicate speakers
    speakers_deduped = _normalize_speakers(raw_speakers)

    # Top owners por carga
    top_owners = tasks_by_owner.most_common(10)

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
    }


def stats_to_text(stats: dict) -> str:
    """Formatea las metricas como texto legible para terminal."""
    lines = []
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

    return "\n".join(lines)

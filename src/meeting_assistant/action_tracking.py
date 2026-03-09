"""
Seguimiento de action items entre reuniones.

Compara tareas del periodo actual vs anterior para detectar:
- Tareas nuevas
- Tareas que siguen pendientes (carry-over)
- Tareas completadas
"""

import re
from difflib import SequenceMatcher


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparacion: minusculas, sin puntuacion extra."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_keywords(text: str) -> set[str]:
    """Extrae palabras clave significativas (>3 chars) de un texto."""
    stopwords = {"para", "como", "esto", "esta", "esos", "esas", "donde",
                 "sobre", "entre", "desde", "hacia", "todos", "todas",
                 "tiene", "hacer", "debe", "deben", "puede", "pueden",
                 "cada", "otro", "otra", "otros", "otras", "solo",
                 "bien", "sera", "sean", "sido", "haber", "estar",
                 "siendo", "cuando", "quien", "cual", "como", "tambien",
                 "pero", "sino", "porque", "aunque", "mientras", "durante",
                 "antes", "despues", "aqui", "alla", "ahora", "luego",
                 "mejor", "mayor", "menor", "mucho", "poco", "todo",
                 "nada", "algo", "algun", "alguno", "alguna", "ningun",
                 "ninguno", "ninguna", "mismo", "misma", "mismos", "mismas",
                 "with", "from", "that", "this", "have", "will", "been",
                 "more", "some", "than", "them", "they", "were", "what"}
    words = set(_normalize_text(text).split())
    return {w for w in words if len(w) > 3 and w not in stopwords}


def _similarity(a: str, b: str) -> float:
    """Similitud combinada: SequenceMatcher + Jaccard de keywords."""
    seq_ratio = SequenceMatcher(None, _normalize_text(a), _normalize_text(b)).ratio()
    kw_a = _extract_keywords(a)
    kw_b = _extract_keywords(b)
    if kw_a and kw_b:
        jaccard = len(kw_a & kw_b) / len(kw_a | kw_b)
    else:
        jaccard = 0.0
    # Promedio ponderado: keywords importan más que secuencia exacta
    return seq_ratio * 0.4 + jaccard * 0.6


def _find_match(task: dict, candidates: list[dict], threshold: float = 0.35) -> tuple[dict | None, float]:
    """Busca la tarea mas similar en una lista de candidatos."""
    task_text = task.get("task", "")
    best_match = None
    best_score = 0

    for c in candidates:
        score = _similarity(task_text, c.get("task", ""))
        # Bonus si coincide owner
        if task.get("owner") and task["owner"] == c.get("owner"):
            score += 0.15
        # Bonus si coincide area
        if task.get("area") and task["area"] == c.get("area"):
            score += 0.05
        if score > best_score:
            best_score = score
            best_match = c

    if best_match and best_score >= threshold:
        return best_match, best_score
    return None, 0.0


def _collect_tasks(meetings: list[dict]) -> list[dict]:
    """Extrae action items sin mutar los dicts originales."""
    tasks = []
    for m in meetings:
        source = m.get("_source_file", "?")
        for a in m.get("action_items", []):
            task_copy = dict(a)
            task_copy["_source"] = source
            tasks.append(task_copy)
    return tasks


def track_actions(
    current_meetings: list[dict],
    previous_meetings: list[dict],
) -> dict:
    """
    Compara action items del periodo actual vs anterior.

    Returns:
        dict con listas: new, completed, carried_over, all_current, all_previous
    """
    current_tasks = _collect_tasks(current_meetings)
    prev_tasks = _collect_tasks(previous_meetings)

    # Clasificar
    new_tasks = []
    carried_over = []
    completed = []

    matched_prev = set()

    for ct in current_tasks:
        match, score = _find_match(ct, prev_tasks)
        if match:
            idx = id(match)
            matched_prev.add(idx)
            if ct.get("status") == "done":
                completed.append({
                    "task": ct.get("task"),
                    "owner": ct.get("owner"),
                    "previous_status": match.get("status"),
                    "current_status": "done",
                    "source": ct["_source"],
                })
            else:
                carried_over.append({
                    "task": ct.get("task"),
                    "owner": ct.get("owner"),
                    "previous_status": match.get("status"),
                    "current_status": ct.get("status"),
                    "source": ct["_source"],
                })
        else:
            new_tasks.append({
                "task": ct.get("task"),
                "owner": ct.get("owner"),
                "status": ct.get("status"),
                "priority": ct.get("priority"),
                "source": ct["_source"],
            })

    # Tareas del periodo anterior que no aparecieron en el actual
    dropped = []
    for pt in prev_tasks:
        if id(pt) not in matched_prev:
            dropped.append({
                "task": pt.get("task"),
                "owner": pt.get("owner"),
                "last_status": pt.get("status"),
                "source": pt["_source"],
            })

    return {
        "new": new_tasks,
        "completed": completed,
        "carried_over": carried_over,
        "dropped": dropped,
        "summary": {
            "total_current": len(current_tasks),
            "total_previous": len(prev_tasks),
            "new_count": len(new_tasks),
            "completed_count": len(completed),
            "carried_over_count": len(carried_over),
            "dropped_count": len(dropped),
        },
    }


def tracking_to_text(tracking: dict) -> str:
    """Formatea el tracking como texto legible."""
    s = tracking["summary"]
    lines = []
    lines.append(f"  Periodo anterior: {s['total_previous']} tareas")
    lines.append(f"  Periodo actual:   {s['total_current']} tareas")
    lines.append(f"  Nuevas:           {s['new_count']}")
    lines.append(f"  Completadas:      {s['completed_count']}")
    lines.append(f"  Carry-over:       {s['carried_over_count']}")
    lines.append(f"  Sin seguimiento:  {s['dropped_count']}")

    if tracking["completed"]:
        lines.append("\n  Completadas:")
        for t in tracking["completed"]:
            lines.append(f"    [done] {t['task']} ({t.get('owner', '?')})")

    if tracking["carried_over"]:
        lines.append("\n  Carry-over (siguen pendientes):")
        for t in tracking["carried_over"]:
            lines.append(f"    [{t['current_status']}] {t['task']} ({t.get('owner', '?')})")

    if tracking["dropped"]:
        lines.append("\n  Sin seguimiento (desaparecieron):")
        for t in tracking["dropped"][:10]:
            lines.append(f"    [{t['last_status']}] {t['task']} ({t.get('owner', '?')})")
        if len(tracking["dropped"]) > 10:
            lines.append(f"    ... y {len(tracking['dropped']) - 10} mas")

    return "\n".join(lines)

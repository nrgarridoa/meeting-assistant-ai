from datetime import datetime


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt(v, default="—"):
    if v is None:
        return default
    if isinstance(v, str) and not v.strip():
        return default
    return str(v)


def md_evidence(ev) -> str:
    """Formatea evidencia como sub-item. Devuelve '' si no hay evidencia."""
    text = fmt(ev, default="")
    if not text or text == "—":
        return ""
    return f'  - _Evidencia:_ \u201c{text}\u201d'


def md_list(items) -> str:
    if not items:
        return "- —\n"
    return "\n".join(f"- {i}" for i in items) + "\n"


# ─────────────────────────────────────────────
# EXPORTACIÓN ÚNICA
# ─────────────────────────────────────────────

def to_markdown(data: dict) -> str:
    """
    Genera la minuta completa en Markdown, optimizada para importar en Notion.

    Estructura:
    - Encabezado (título, fecha, metadata)
    - Resumen ejecutivo (top bullets)
    - Temas tratados (topics dinámicos — solo los que se discutieron)
    - Decisiones
    - Tareas (tabla)
    - Riesgos / Bloqueos
    - Preguntas Abiertas
    - Próximos Pasos
    - Speakers
    """
    title        = fmt(data.get("meeting_title"), "Reunión")
    date         = fmt(data.get("date"))
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    meta         = data.get("_meta", {})
    mode         = meta.get("mode", "—")
    reqs         = meta.get("requests_generate", "—")

    speakers  = data.get("speakers", []) or []
    top       = data.get("summary_top_bullets", []) or []
    topics    = data.get("topics", []) or []
    decisions = data.get("decisions", []) or []
    actions   = data.get("action_items", []) or []
    risks     = data.get("risks_blockers", []) or []
    questions = data.get("open_questions", []) or []
    next_steps = data.get("next_steps", []) or []

    lines = []

    # ── Encabezado ────────────────────────────────────────────────────────────
    lines.append(f"# {title}\n")
    lines.append(f"**Fecha:** {date}  ")
    lines.append(f"**Generado:** {generated_at}  ")
    lines.append(f"**Modo:** {mode} · **Requests usados:** {reqs}")
    lines.append("")

    # ── Resumen ejecutivo ─────────────────────────────────────────────────────
    lines.append("## Resumen")
    lines.append(md_list(top))

    # ── Temas tratados (dinámicos) ────────────────────────────────────────────
    if topics:
        lines.append("## Temas tratados")
        for topic in topics:
            name    = fmt(topic.get("name"), "Sin nombre")
            bullets = topic.get("bullets", []) or []
            lines.append(f"\n### {name}")
            lines.append(md_list(bullets))

    # ── Decisiones ───────────────────────────────────────────────────────────
    lines.append("## Decisiones")
    if decisions:
        for d in decisions:
            line = f"- **{fmt(d.get('decision'))}**"
            meta_parts = []
            owner = fmt(d.get("owner"))
            due   = fmt(d.get("due_date"))
            if owner != "—": meta_parts.append(f"Owner: {owner}")
            if due   != "—": meta_parts.append(f"Fecha: {due}")
            if meta_parts:
                line += f" ({', '.join(meta_parts)})"
            lines.append(line)
            ev = md_evidence(d.get("evidence"))
            if ev:
                lines.append(ev)
        lines.append("")
    else:
        lines.append("- —\n")

    # ── Tareas (tabla) ────────────────────────────────────────────────────────
    lines.append("## Tareas")
    if actions:
        lines.append("| Área | Tarea | Owner | Fecha | Prioridad | Estado | Evidencia |")
        lines.append("|---|---|---|---|---|---|---|")
        for it in actions:
            area  = fmt(it.get("area")).replace("|", "/")
            task  = fmt(it.get("task")).replace("\n", " ").replace("|", "/")
            owner = fmt(it.get("owner"))
            due   = fmt(it.get("due_date"))
            pr    = fmt(it.get("priority"))
            st    = fmt(it.get("status"))
            ev    = fmt(it.get("evidence"), default="").replace("\n", " ").replace("|", "/")
            lines.append(f"| {area} | {task} | {owner} | {due} | {pr} | {st} | {ev} |")
        lines.append("")
    else:
        lines.append("| Área | Tarea | Owner | Fecha | Prioridad | Estado | Evidencia |")
        lines.append("|---|---|---|---|---|---|---|")
        lines.append("| — | — | — | — | — | — | — |")
        lines.append("")

    # ── Riesgos / Bloqueos ────────────────────────────────────────────────────
    lines.append("## Riesgos / Bloqueos")
    lines.append(md_list(risks))

    # ── Preguntas Abiertas ────────────────────────────────────────────────────
    lines.append("## Preguntas Abiertas")
    lines.append(md_list(questions))

    # ── Próximos Pasos ────────────────────────────────────────────────────────
    lines.append("## Próximos Pasos")
    lines.append(md_list(next_steps))

    # ── Speakers ─────────────────────────────────────────────────────────────
    lines.append("## Speakers")
    if speakers:
        for s in speakers:
            lines.append(f"- {fmt(s.get('name'))}")
            ev = md_evidence(s.get("evidence"))
            if ev:
                lines.append(ev)
        lines.append("")
    else:
        lines.append("- —\n")

    return "\n".join(lines)

import re
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


# ─────────────────────────────────────────────
# PARSE MD → JSON  (inverso de to_markdown)
# ─────────────────────────────────────────────

def parse_md_to_structured(md_text: str, existing_json: dict | None = None) -> dict:
    """
    Parsea el MD generado por to_markdown() de vuelta a la estructura JSON.

    Preserva todos los campos internos del existing_json que no aparecen en el MD
    (_meta, _date, _source_file, notion_meeting_page_id, notion_page_id en tasks, etc.)

    Args:
        md_text: Contenido Markdown tal como está en Notion (posiblemente editado).
        existing_json: JSON local existente para preservar campos internos.

    Returns:
        dict con la estructura completa actualizada.
    """
    from difflib import SequenceMatcher

    data = dict(existing_json) if existing_json else {}
    lines = md_text.split("\n")
    i = 0

    # ── Título ────────────────────────────────────────────────────────────────
    while i < len(lines):
        if lines[i].startswith("# "):
            data["meeting_title"] = lines[i][2:].strip()
            i += 1
            break
        i += 1

    # ── Metadata (Fecha, Generado, Modo — hasta primer ##) ───────────────────
    while i < len(lines) and not lines[i].startswith("##"):
        m = re.match(r"\*\*Fecha:\*\*\s*(.+?)(\s{2})?$", lines[i].strip())
        if m:
            data["date"] = m.group(1).strip()
        i += 1

    # ── Secciones ─────────────────────────────────────────────────────────────
    parsed = {
        "summary": [],
        "topics": [],
        "decisions": [],
        "tasks": [],
        "risks": [],
        "questions": [],
        "next_steps": [],
        "speakers": [],
    }

    current_section = None
    current_topic = None
    current_topic_bullets = []
    table_headers = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Encabezado de sección
        if stripped.startswith("## "):
            # Guardar topic anterior si quedó abierto
            if current_topic is not None:
                parsed["topics"].append({"name": current_topic, "bullets": current_topic_bullets})
                current_topic = None
                current_topic_bullets = []

            section_raw = stripped[3:].strip()
            if "Resumen" in section_raw:
                current_section = "summary"
            elif "Temas" in section_raw:
                current_section = "topics"
            elif "Decisi" in section_raw:
                current_section = "decisions"
            elif "Tareas" in section_raw:
                current_section = "tasks"
                table_headers = None
            elif "Riesgo" in section_raw or "Bloqueo" in section_raw:
                current_section = "risks"
            elif "Pregunta" in section_raw:
                current_section = "questions"
            elif "Pr" in section_raw and "ximo" in section_raw:
                current_section = "next_steps"
            elif "Speaker" in section_raw:
                current_section = "speakers"
            else:
                current_section = None
            i += 1
            continue

        # Sub-sección de temas tratados
        if stripped.startswith("### ") and current_section == "topics":
            if current_topic is not None:
                parsed["topics"].append({"name": current_topic, "bullets": current_topic_bullets})
            current_topic = stripped[4:].strip()
            current_topic_bullets = []
            i += 1
            continue

        # ── Contenido por sección ──────────────────────────────────────────────
        if current_section == "summary":
            if stripped.startswith("- ") and stripped != "- —":
                parsed["summary"].append(stripped[2:])

        elif current_section == "topics":
            if current_topic and stripped.startswith("- ") and stripped != "- —":
                current_topic_bullets.append(stripped[2:])

        elif current_section == "decisions":
            if stripped.startswith("- ") and stripped != "- —":
                m = re.match(r"- \*\*(.+?)\*\*(?:\s*\((.+?)\))?$", stripped)
                if m:
                    dec = {"decision": m.group(1).strip()}
                    meta_str = m.group(2) or ""
                    om = re.search(r"Owner:\s*([^,)]+)", meta_str)
                    fm = re.search(r"Fecha:\s*([^,)]+)", meta_str)
                    if om:
                        dec["owner"] = om.group(1).strip()
                    if fm:
                        dec["due_date"] = fm.group(1).strip()
                    parsed["decisions"].append(dec)
                else:
                    # Texto plano sin bold
                    text = re.sub(r"\*\*", "", stripped[2:]).strip()
                    if text:
                        parsed["decisions"].append({"decision": text})
            elif re.match(r"\s+-\s+_Evidencia", line) and parsed["decisions"]:
                ev = re.sub(r"^\s*-\s*_Evidencia:_\s*", "", stripped).strip('\u201c\u201d"\'')
                parsed["decisions"][-1]["evidence"] = ev

        elif current_section == "tasks":
            if stripped.startswith("|") and stripped.endswith("|"):
                if table_headers is None and "Área" in stripped:
                    table_headers = [h.strip() for h in stripped.strip("|").split("|")]
                elif table_headers and not all(c in "-| " for c in stripped):
                    cells = [c.strip() for c in stripped.strip("|").split("|")]
                    while len(cells) < len(table_headers):
                        cells.append("—")
                    row = dict(zip(table_headers, cells))
                    task_text = row.get("Tarea", "").replace("—", "").strip()
                    if task_text:
                        ai = {"task": task_text}
                        for md_col, json_key in [
                            ("Área", "area"), ("Owner", "owner"),
                            ("Fecha", "due_date"), ("Prioridad", "priority"),
                            ("Estado", "status"), ("Evidencia", "evidence"),
                        ]:
                            val = row.get(md_col, "").replace("—", "").strip()
                            if val:
                                ai[json_key] = val
                        if "priority" not in ai:
                            ai["priority"] = "medium"
                        if "status" not in ai:
                            ai["status"] = "todo"
                        parsed["tasks"].append(ai)

        elif current_section in ("risks", "questions", "next_steps"):
            if stripped.startswith("- ") and stripped != "- —":
                parsed[current_section].append(stripped[2:])

        elif current_section == "speakers":
            if stripped.startswith("- ") and stripped != "- —":
                name = stripped[2:].strip()
                if name:
                    parsed["speakers"].append({"name": name})

        i += 1

    # Flush último topic abierto
    if current_topic is not None:
        parsed["topics"].append({"name": current_topic, "bullets": current_topic_bullets})

    # ── Aplicar parsed al data, solo si hay contenido ─────────────────────────
    if parsed["summary"]:
        data["summary_top_bullets"] = parsed["summary"]
    if parsed["topics"]:
        data["topics"] = parsed["topics"]
    if parsed["decisions"]:
        data["decisions"] = parsed["decisions"]
    if parsed["risks"]:
        data["risks_blockers"] = parsed["risks"]
    if parsed["questions"]:
        data["open_questions"] = parsed["questions"]
    if parsed["next_steps"]:
        data["next_steps"] = parsed["next_steps"]
    if parsed["speakers"]:
        data["speakers"] = parsed["speakers"]

    # ── Action items: preservar notion_page_id y notion_deleted por similitud ──
    if parsed["tasks"]:
        old_tasks = {
            ai.get("task", "").lower(): ai
            for ai in (existing_json or {}).get("action_items", [])
        }
        for new_ai in parsed["tasks"]:
            new_text = new_ai.get("task", "").lower()
            best_match = old_tasks.get(new_text)
            if not best_match:
                best_ratio = 0
                for old_text, old_ai in old_tasks.items():
                    ratio = SequenceMatcher(None, new_text, old_text).ratio()
                    if ratio > best_ratio and ratio > 0.70:
                        best_ratio = ratio
                        best_match = old_ai
            if best_match:
                for field in ("notion_page_id", "notion_deleted"):
                    if field in best_match:
                        new_ai[field] = best_match[field]
        data["action_items"] = parsed["tasks"]

    return data

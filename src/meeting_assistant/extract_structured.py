import json
import re
from pathlib import Path
from google.genai import types

from .chunking import chunk_text_smart
from .rate_limit import call_with_key_rotation


# ─────────────────────────────────────────────
# SCHEMA + REGLAS
# ─────────────────────────────────────────────

SCHEMA_HINT = """
Devuelve SOLO JSON válido. Idioma: español.

{
  "meeting_title": "string",
  "date": "string|null",
  "speakers": [{"name":"string","evidence":"string|null"}],
  "summary_top_bullets": ["string"],
  "topics": [
    {"name":"string","bullets":["string"]}
  ],
  "decisions": [{"decision":"string","owner":"string|null","due_date":"string|null","evidence":"string|null"}],
  "action_items": [
    {"task":"string","area":"string",
     "owner":"string|null","due_date":"string|null",
     "priority":"low|medium|high","status":"todo|in_progress|done|blocked",
     "evidence":"string|null"}
  ],
  "risks_blockers":["string"],
  "open_questions":["string"],
  "next_steps":["string"]
}

Reglas:
- speakers: SOLO personas que hablan (no mencionadas). Sin apellidos inventados.
- summary_top_bullets: 5–10 bullets del resumen general.
- topics: identifica libremente los temas reales tratados. NO uses categorías fijas.
  Ej: "Mejoras en plataforma", "Auditoría de camiones", "Presupuesto Q2".
  Solo incluye topics que se discutieron efectivamente.
- action_items.area: describe el área real de la tarea (texto libre, ej: "Backend", "UX", "Ventas").
- action_items: solo tareas accionables (verbo + entregable).
- evidence: cita ≤12 palabras. null si no aplica.
- priority: SOLO low|medium|high. status: SOLO todo|in_progress|done|blocked.
- owner/due_date: null si no se menciona.
""".strip()

EXTRA_RULES = "No repitas texto literal. Devuelve SOLO JSON."

_VALID_PRIORITY = {"low", "medium", "high"}
_VALID_STATUS = {"todo", "in_progress", "done", "blocked"}
_REQUIRED_FIELDS = {
    "meeting_title", "speakers", "summary_top_bullets", "topics",
    "decisions", "action_items", "risks_blockers", "open_questions", "next_steps"
}


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _build_context_block(context: str) -> str:
    """Construye el bloque de contexto para el prompt."""
    ctx = context.strip() if context else ""
    if ctx:
        return f"\nCONTEXTO DE LA REUNIÓN:\n{ctx}\n"
    return (
        "\nINSTRUCCION: Detecta automaticamente el tipo de reunion "
        "(daily, seguimiento de proyecto, estrategica, tecnica, etc.) "
        "a partir de los primeros intercambios y participantes. "
        "Usa esa inferencia para guiar la extraccion de informacion.\n"
    )


def extract_json(text: str) -> str:
    """Extrae el primer objeto JSON {...} del texto."""
    if not text:
        return ""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        return m.group(1).strip()
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if end > start:
            return text[start:end + 1].strip()
    return ""


def validate_data(data: dict) -> dict:
    """Valida y corrige campos del JSON extraído."""
    defaults = {
        "meeting_title": "Reunión",
        "date": None,
        "speakers": [],
        "summary_top_bullets": [],
        "topics": [],
        "decisions": [],
        "action_items": [],
        "risks_blockers": [],
        "open_questions": [],
        "next_steps": [],
    }
    for field, default in defaults.items():
        if field not in data or data[field] is None:
            data[field] = default

    # Validar speakers
    speaker_names = set()
    for s in data.get("speakers", []):
        if not isinstance(s, dict):
            continue
        name = (s.get("name") or "").strip()
        if name:
            speaker_names.add(name.lower())

    # Corregir action_items
    for item in data.get("action_items", []):
        if item.get("priority") not in _VALID_PRIORITY:
            item["priority"] = "medium"
        if item.get("status") not in _VALID_STATUS:
            item["status"] = "todo"
        if not item.get("area"):
            item["area"] = "general"
        # Limpiar task sin verbo (probable ruido)
        task = (item.get("task") or "").strip()
        if len(task) < 5:
            item["task"] = task or "Tarea sin descripción"
        # Validar owner existe como speaker (advertencia, no corrección)
        owner = (item.get("owner") or "").strip()
        if owner and owner.lower() not in speaker_names:
            item.setdefault("_warnings", []).append("owner_not_speaker")

    # Validar decisions
    for d in data.get("decisions", []):
        if not isinstance(d, dict):
            continue
        owner = (d.get("owner") or "").strip()
        if owner and owner.lower() not in speaker_names:
            d.setdefault("_warnings", []).append("owner_not_speaker")

    # Eliminar topics vacíos
    data["topics"] = [
        t for t in data.get("topics", [])
        if isinstance(t, dict) and t.get("bullets")
    ]

    return data


def get_validation_warnings(data: dict) -> list[str]:
    """Extrae advertencias de validación del JSON procesado."""
    warnings = []
    for item in data.get("action_items", []):
        if "owner_not_speaker" in item.get("_warnings", []):
            warnings.append(
                f"Tarea '{item.get('task', '?')[:40]}' tiene owner "
                f"'{item.get('owner')}' que no es speaker"
            )
    for d in data.get("decisions", []):
        if "owner_not_speaker" in d.get("_warnings", []):
            warnings.append(
                f"Decisión '{d.get('decision', '?')[:40]}' tiene owner "
                f"'{d.get('owner')}' que no es speaker"
            )
    return warnings


def repair_json(client, model: str, key_manager, candidate: str) -> dict:
    """Llama al modelo para corregir JSON malformado. Consume 1 request extra."""
    fix_prompt = (
        f"Devuelve SOLO JSON válido. Corrige:\n\n"
        f"SCHEMA:\n{SCHEMA_HINT}\n\n"
        f"CONTENIDO:\n\"\"\"{candidate}\"\"\""
    )
    resp = call_with_key_rotation(
        client=client, model=model, key_manager=key_manager,
        fn_builder=lambda c: (lambda: c.models.generate_content(
            model=model, contents=fix_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.0
            )
        ))
    )
    fixed = (resp.text or "").strip()
    return json.loads(extract_json(fixed) or fixed)


def extract_new_tasks(
    client,
    model: str,
    key_manager,
    data: dict,
    existing_tasks: list[dict],
) -> list[dict]:
    """
    Usa 1 request a Gemini para detectar action items nuevos en el contenido
    de topics, decisions y next_steps que NO estén ya en existing_tasks.

    Diseñado para usarse después de editar una reunión en Notion y hacer pull.

    Returns:
        Lista de dicts de action_items nuevos (validados). Vacía si no hay ninguno.
    """
    # Construir texto de las secciones relevantes
    sections = []

    topics = data.get("topics", [])
    if topics:
        parts = []
        for t in topics:
            name = t.get("name", "")
            bullets = "\n".join(f"  - {b}" for b in (t.get("bullets") or []))
            if bullets:
                parts.append(f"### {name}\n{bullets}")
        if parts:
            sections.append("TEMAS TRATADOS:\n" + "\n\n".join(parts))

    decisions = data.get("decisions", [])
    if decisions:
        parts = []
        for d in decisions:
            line = f"- {d.get('decision', '')}"
            if d.get("owner"):
                line += f" (Owner: {d['owner']})"
            if d.get("due_date"):
                line += f" (Fecha: {d['due_date']})"
            parts.append(line)
        sections.append("DECISIONES:\n" + "\n".join(parts))

    next_steps = data.get("next_steps", [])
    if next_steps:
        sections.append("PROXIMOS PASOS:\n" + "\n".join(f"- {s}" for s in next_steps))

    if not sections:
        return []

    content_text = "\n\n".join(sections)
    active_tasks = [ai for ai in existing_tasks if not ai.get("notion_deleted")]
    existing_texts = "\n".join(
        f"- {ai.get('task', '')}" for ai in active_tasks if ai.get("task")
    ) or "(ninguna)"

    prompt = (
        "Eres un asistente de reuniones. Analiza el contenido e identifica "
        "UNICAMENTE action items accionables (verbo + responsable/entregable) "
        "que NO esten ya en la lista de tareas existentes.\n\n"
        f"CONTENIDO DE LA REUNION:\n{content_text}\n\n"
        f"TAREAS YA REGISTRADAS (NO repetir estas ni parafrasearlas):\n{existing_texts}\n\n"
        "Devuelve SOLO un JSON array. Si no hay tareas nuevas devuelve [].\n"
        "Formato exacto de cada elemento:\n"
        '{"task":"string","area":"string","owner":"string|null",'
        '"due_date":"string|null","priority":"low|medium|high","status":"todo"}'
    )

    resp = call_with_key_rotation(
        client=client, model=model, key_manager=key_manager,
        fn_builder=lambda c: (lambda: c.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.1,
            )
        ))
    )

    raw = (resp.text or "").strip()
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        return []

    try:
        new_tasks = json.loads(m.group())
    except Exception:
        return []

    if not isinstance(new_tasks, list):
        return []

    result = []
    for item in new_tasks:
        if not isinstance(item, dict):
            continue
        task_text = (item.get("task") or "").strip()
        if len(task_text) < 5:
            continue
        if item.get("priority") not in _VALID_PRIORITY:
            item["priority"] = "medium"
        if item.get("status") not in _VALID_STATUS:
            item["status"] = "todo"
        if not item.get("area"):
            item["area"] = "general"
        result.append(item)

    return result


def load_cached(out_path: Path) -> dict | None:
    """Devuelve el JSON cacheado si existe, o None si no."""
    if out_path.exists():
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def estimate_requests(
    text: str,
    *,
    max_chars_single_shot: int,
    chunk_chars: int,
) -> dict:
    """Estima cuántas llamadas generate_content se harán (sin contar repairs)."""
    if len(text) <= max_chars_single_shot:
        return {"mode": "single", "chunks": 1, "requests_generate": 1}
    chunks = chunk_text_smart(text, max_chars=chunk_chars)
    return {"mode": "map_reduce", "chunks": len(chunks), "requests_generate": len(chunks) + 1}


# ─────────────────────────────────────────────
# FUNCIÓN PRINCIPAL
# ─────────────────────────────────────────────

def extract_structured(
    client,
    model: str,
    key_manager,
    transcript_text: str,
    *,
    meeting_context: str = "",
    max_chars_single_shot: int = 45000,
    chunk_chars: int = 30000,
) -> dict:
    """
    Extrae información estructurada de una transcripción.

    Args:
        client: genai.Client.
        model: Nombre del modelo Gemini.
        key_manager: Instancia de KeyManager.
        transcript_text: Texto ya preprocesado.
        meeting_context: Contexto opcional de la reunión (tipo, equipo, agenda).
                         Se inyecta en el prompt para guiar la extracción.
                         Ej: "Reunión técnica de desarrollo backend."
        max_chars_single_shot: Umbral para activar map-reduce (default 45000).
        chunk_chars: Tamaño de cada chunk en modo map-reduce (default 30000).

    Returns:
        dict con JSON estructurado + campo "_meta".
    """
    if not isinstance(transcript_text, str):
        raise TypeError(f"Se esperaba str, recibió: {type(transcript_text)}")

    plan = estimate_requests(
        transcript_text,
        max_chars_single_shot=max_chars_single_shot,
        chunk_chars=chunk_chars,
    )

    context_block = _build_context_block(meeting_context)

    # ── MODO SINGLE-SHOT ──────────────────────────────────────────────────────
    if plan["mode"] == "single":
        prompt = (
            f"Eres un asistente personal de reuniones.{context_block}\n\n"
            f"{SCHEMA_HINT}\n\n{EXTRA_RULES}\n\n"
            f"TRANSCRIPCIÓN:\n\"\"\"{transcript_text}\"\"\""
        )

        resp = call_with_key_rotation(
            client=client, model=model, key_manager=key_manager,
            fn_builder=lambda c: (lambda: c.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.2
                )
            ))
        )

        raw = (resp.text or "").strip()
        candidate = extract_json(raw) or raw

        try:
            data = json.loads(candidate)
        except Exception:
            data = repair_json(client, model, key_manager, candidate)

        data = validate_data(data)
        data["_meta"] = plan
        return data

    # ── MODO MAP-REDUCE ───────────────────────────────────────────────────────
    chunks = chunk_text_smart(transcript_text, max_chars=chunk_chars)
    partials = []

    for i, chunk in enumerate(chunks, start=1):
        map_prompt = (
            f"Eres un asistente de reuniones. Idioma: español.{context_block}\n"
            f"Extrae SOLO lo relevante de este bloque (máx 400 palabras).\n"
            f"Identifica los temas reales tratados (no uses categorías fijas).\n"
            f"Incluye: decisiones, tareas, riesgos, preguntas abiertas.\n"
            f"No devuelvas JSON. Texto estructurado y conciso.\n\n"
            f"BLOQUE {i}/{len(chunks)}:\n\"\"\"{chunk}\"\"\""
        )

        r = call_with_key_rotation(
            client=client, model=model, key_manager=key_manager,
            fn_builder=lambda c, p=map_prompt: (lambda: c.models.generate_content(
                model=model, contents=p,
                config=types.GenerateContentConfig(temperature=0.2)
            ))
        )
        partials.append((r.text or "").strip())

    combined = "\n\n---\n\n".join(p for p in partials if p)

    reduce_prompt = (
        f"Eres un asistente de reuniones. Idioma: español.{context_block}\n"
        f"Con los resúmenes parciales, genera el JSON final.\n\n"
        f"{SCHEMA_HINT}\n\n{EXTRA_RULES}\n\n"
        f"RESÚMENES PARCIALES:\n\"\"\"{combined}\"\"\""
    )

    resp = call_with_key_rotation(
        client=client, model=model, key_manager=key_manager,
        fn_builder=lambda c: (lambda: c.models.generate_content(
            model=model, contents=reduce_prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.2
            )
        ))
    )

    raw = (resp.text or "").strip()
    candidate = extract_json(raw) or raw

    try:
        data = json.loads(candidate)
    except Exception:
        data = repair_json(client, model, key_manager, candidate)

    data = validate_data(data)
    data["_meta"] = plan
    return data

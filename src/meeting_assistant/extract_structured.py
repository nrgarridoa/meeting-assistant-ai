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
    """Construye el bloque de contexto para el prompt si se proporcionó."""
    ctx = context.strip() if context else ""
    if not ctx:
        return ""
    return f"\nCONTEXTO DE LA REUNIÓN:\n{ctx}\n"


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

    # Corregir action_items con valores inválidos
    for item in data.get("action_items", []):
        if item.get("priority") not in _VALID_PRIORITY:
            item["priority"] = "medium"
        if item.get("status") not in _VALID_STATUS:
            item["status"] = "todo"
        # Normalizar area vacía
        if not item.get("area"):
            item["area"] = "general"

    return data


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

# Meeting Assistant AI

Asistente personal de reuniones impulsado por Gemini API (Free Tier).
Convierte transcripciones `.docx` en JSON estructurado y minutas Markdown.

---

## Qué hace

- Carga transcripciones `.docx` o `.txt`
- Preprocesa el texto (elimina timestamps, fillers, ruido) para reducir tokens
- Extrae información estructurada por áreas: marketing, desarrollo, ventas, académico, otros
- Genera JSON con speakers, decisiones, tareas, riesgos y preguntas abiertas
- Exporta minuta completa en un solo archivo Markdown (optimizado para Notion)
- Maneja múltiples API Keys con rotación automática
- Retry automático para rate limits temporales

---

## Arquitectura

```
6_Meeting_Assistant/
├── .env
├── requirements.txt
├── notebooks/
│   └── pipeline.ipynb          ← Único punto de ejecución
├── src/
│   └── meeting_assistant/
│       ├── __init__.py
│       ├── gemini_client.py    ← Crea el cliente Gemini
│       ├── key_manager.py      ← Rotación de API Keys
│       ├── rate_limit.py       ← Retry + rotación por cuota
│       ├── preprocess.py       ← Limpieza agresiva de texto
│       ├── chunking.py         ← División inteligente en bloques
│       ├── io_transcripts.py   ← Lectura de .docx y .txt
│       ├── extract_structured.py ← Llamada a Gemini + caché
│       └── export_markdown.py  ← Generación de Markdown
├── transcriptions/
│   └── *.docx                  ← Archivos de entrada
└── outputs/
    ├── *_structured.json   ← datos crudos (caché)
    └── *.md                ← minuta para Notion
```

---

## Flujo de ejecución

```
.docx
  ↓  load_transcript()
Texto crudo
  ↓  preprocess_transcript()      ← -30 a 40% de caracteres
Texto limpio
  ↓  estimate_requests()
  ├─ ≤45k chars → single-shot (1 request)
  └─ >45k chars → map-reduce (N chunks + 1 reduce)
  ↓  extract_structured()
JSON validado
  ↓  to_markdown()
{stem}.md  (listo para Notion)
```

En caso de rate limit temporal (429): espera automática 30s → 60s → 90s.
En caso de cuota diaria agotada: rota a la siguiente API Key.

---

## Schema JSON de salida

```json
{
  "meeting_title": "string",
  "date": "string|null",
  "speakers": [{"name": "string", "evidence": "string|null"}],
  "summary_top_bullets": ["string"],
  "topics": [
    {"name": "string", "bullets": ["string"]}
  ],
  "decisions": [
    {"decision": "string", "owner": "string|null", "due_date": "string|null", "evidence": "string|null"}
  ],
  "action_items": [
    {
      "task": "string",
      "area": "string",
      "owner": "string|null",
      "due_date": "string|null",
      "priority": "low|medium|high",
      "status": "todo|in_progress|done|blocked",
      "evidence": "string|null"
    }
  ],
  "risks_blockers": ["string"],
  "open_questions": ["string"],
  "next_steps": ["string"],
  "_meta": {"mode": "single|map_reduce", "chunks": 1, "requests_generate": 1}
}
```

Reglas del schema:
- `speakers`: solo personas que hablan, no mencionadas. Sin apellidos inventados.
- `topics`: temas reales de la reunión, identificados libremente por el modelo. No hay categorías fijas.
- `action_items.area`: texto libre — el modelo escribe el área real (ej: "Backend", "UX", "Ventas").
- `priority`: solo `low`, `medium` o `high`.
- `status`: solo `todo`, `in_progress`, `done` o `blocked`.

---

## Configuración del .env

```env
# Múltiples keys (recomendado para rotar si una se agota)
GEMINI_KEYS=key1,key2,key3

# O una sola key
GEMINI_API_KEY=key1

# Modelo a usar
GEMINI_MODEL=gemini-2.5-flash
```

> Si las keys pertenecen al mismo proyecto Google Cloud, comparten cuota diaria.

---

## Instalación

```bash
# 1. Crear entorno virtual
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Linux/Mac

# 2. Instalar dependencias
pip install -r requirements.txt
```

---

## Cómo ejecutar

Abrir `notebooks/pipeline.ipynb` y ejecutar las celdas en orden:

1. **Celda 1** — Define rutas, el `MEETING_CONTEXT` opcional, conecta con la API y hace smoke test
2. **Celda 2** — Lista las transcripciones y su estado (procesado/pendiente)
3. **Celda 3** — Corre el pipeline completo (con caché automático)
4. **Celda 4** — Muestra resumen de todos los outputs generados

Para dar contexto a la reunión, edita `MEETING_CONTEXT` en la Celda 1:
```python
MEETING_CONTEXT = "Reunión técnica de desarrollo backend. Revisión de mejoras en la plataforma."
```

Para reprocesar un archivo ya procesado, elimina su `*_structured.json` de `outputs/`.

---

## Optimización para Free Tier

El proyecto está diseñado para minimizar el consumo de requests:

| Técnica | Efecto |
|---|---|
| Preprocesamiento agresivo | -30 a 40% de caracteres enviados |
| Umbral single-shot alto (45k) | La mayoría de reuniones usan 1 request |
| Caché de outputs | 0 requests en re-ejecuciones |
| Map-reduce solo si es necesario | Chunks grandes (30k) → menos bloques |
| Prompts compactos | Menos tokens de entrada por llamada |

Consumo estimado por reunión:
- Reunión típica de 1h: **1 request**
- Reunión muy larga (>45k chars post-procesado): **3–4 requests**

---

## Limitaciones (Free Tier Gemini)

- ~15–20 requests por día por proyecto (varía según modelo)
- `count_tokens` consume 1 request (está desactivado por defecto)
- Si todas las keys del mismo proyecto Google Cloud están agotadas, esperar 24h

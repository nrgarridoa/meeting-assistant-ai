# Meeting Assistant AI

Asistente personal de reuniones impulsado por Gemini API (Free Tier).
Pipeline completo: `.docx` → JSON estructurado → Markdown → PDF → Notion, con sincronizacion bidireccional.

![Pipeline Overview](docs/images/pipeline-overview.png)

---

## Que hace

- Carga transcripciones `.docx` o `.txt`
- Preprocesa el texto (elimina timestamps, fillers, ruido) para reducir tokens
- Detecta automaticamente el tipo de reunion (daily, tecnica, estrategica, etc.)
- Extrae informacion estructurada: speakers, decisiones, tareas, riesgos
- Exporta minuta completa en Markdown (optimizado para Notion)
- Genera reportes ejecutivos semanales/mensuales (breves, para gerencia)
- Exporta reportes a PDF profesional
- Sincronizacion bidireccional con Notion:
  - **Push**: minutas como paginas, tareas como entries en database
  - **Pull**: descarga cambios de status/prioridad/owner desde Notion
  - Tareas manuales agregadas en Notion se incluyen en reportes
- Seguimiento de action items entre periodos (carry-over, completadas, nuevas)
- Busqueda sobre reuniones procesadas (decisiones, tareas, temas, speakers)
- Dashboard de metricas (sin consumir requests)
- Deteccion fuzzy de speakers duplicados
- Maneja multiples API Keys con rotacion automatica
- CLI completo (`python -m meeting_assistant`)

---

## Arquitectura

```
6_Meeting_Assistant/
├── .env                          ← API keys y config (no commitear)
├── requirements.txt
├── docs/
│   └── images/                   ← Screenshots para README
├── notebooks/
│   ├── pipeline.ipynb            ← Procesar transcripciones (interactivo)
│   └── report.ipynb              ← Generar reportes (interactivo)
├── src/
│   └── meeting_assistant/
│       ├── __init__.py            ← Exports publicos
│       ├── __main__.py            ← CLI entry point
│       ├── gemini_client.py       ← Cliente Gemini
│       ├── key_manager.py         ← Rotacion de API Keys
│       ├── rate_limit.py          ← Retry + rotacion por cuota
│       ├── preprocess.py          ← Limpieza de texto
│       ├── chunking.py            ← Division en bloques
│       ├── io_transcripts.py      ← Lectura de .docx y .txt
│       ├── extract_structured.py  ← Extraccion + validacion + auto-contexto
│       ├── export_markdown.py     ← Markdown minutas individuales
│       ├── report.py              ← Reportes ejecutivos consolidados
│       ├── pdf_export.py          ← Exportacion a PDF (fpdf2)
│       ├── stats.py               ← Dashboard de metricas (0 requests)
│       ├── action_tracking.py     ← Seguimiento de tareas entre periodos
│       ├── search.py              ← Busqueda sobre reuniones
│       └── notion_sync.py         ← Sincronizacion bidireccional con Notion
├── transcriptions/                ← YYMMDD_tema.docx (input)
├── outputs/                       ← JSONs + MDs individuales (procesados)
└── reports/                       ← Reportes ejecutivos (JSON + MD + PDF)
```

---

## Instalacion

```bash
git clone https://github.com/tu-usuario/meeting-assistant.git
cd meeting-assistant

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

Crear archivo `.env` en la raiz (ver seccion Configuracion).

---

## Configuracion del .env

```env
# ── Gemini API ──
GEMINI_KEYS=AIzaSy...,AIzaSy...,AIzaSy...
GEMINI_MODEL=models/gemini-2.5-flash

# ── Notion (opcional) ──
NOTION_TOKEN=ntn_xxx
NOTION_MEETINGS_DB_ID=xxx    # Database/pagina de minutas
NOTION_REPORTS_DB_ID=xxx     # Database/pagina de reportes
NOTION_TASKS_DB_ID=xxx       # Database de action items
```

### Configurar Gemini
1. Ir a [Google AI Studio](https://aistudio.google.com/apikey)
2. Crear API key(s) — se recomiendan 2-3 para rotacion
3. Agregar al `.env` separadas por coma

### Configurar Notion
1. Crear integracion interna en https://www.notion.so/my-integrations
2. Crear 3 elementos en Notion:
   - **Meetings** (pagina) — donde se suben las minutas
   - **Reports** (pagina) — donde se suben los reportes
   - **Tasks** (database) — las columnas se crean automaticamente:

   | Columna | Tipo | Valores |
   |---------|------|---------|
   | Task | title | descripcion de la tarea |
   | Owner | rich_text | responsable |
   | Status | select | `todo`, `in_progress`, `done`, `blocked` |
   | Priority | select | `high`, `medium`, `low` |
   | Area | select | area funcional |
   | Project | select | proyecto (auto-detectado o manual) |
   | Meeting | rich_text | reunion de origen |
   | Date | date | fecha de la reunion |

3. Compartir las 3 paginas/databases con la integracion (Share > Invite)
4. Copiar los IDs y agregarlos al `.env`

![Notion Tasks DB](docs/images/notion-tasks-db.png)

---

## CLI (linea de comandos)

Ejecutar desde `src/`:
```bash
cd src
python -m meeting_assistant <comando>
```

### Comandos disponibles

```bash
# ── Procesamiento ──
python -m meeting_assistant process                          # Procesar transcripciones pendientes
python -m meeting_assistant process --context "Daily team"   # Con contexto manual

# ── Reportes ──
python -m meeting_assistant report --tipo semanal                     # Reporte semanal
python -m meeting_assistant report --tipo mensual --fecha 2026-03-01  # Mensual de marzo
python -m meeting_assistant report --tipo semanal --pdf               # Con PDF
python -m meeting_assistant report --tipo semanal --pdf --notion      # Con PDF + subir a Notion

# ── Metricas (0 requests Gemini) ──
python -m meeting_assistant stats                                     # Todas las reuniones
python -m meeting_assistant stats --fecha 2026-03-04 --tipo semanal   # Periodo especifico

# ── Busqueda ──
python -m meeting_assistant search "Chinalco"                         # Buscar en todo
python -m meeting_assistant search "SUNAT" --scope decisions          # Solo decisiones
python -m meeting_assistant search "Harold" --scope speakers          # Solo speakers

# ── Seguimiento de tareas ──
python -m meeting_assistant tracking --fecha 2026-03-04 --tipo semanal

# ── Notion: Push ──
python -m meeting_assistant notion --file outputs/260304_daily-team.md --title "Daily" --type minuta
python -m meeting_assistant notion-tasks                              # Subir todas las tareas
python -m meeting_assistant notion-tasks --fecha 2026-03-04           # Solo de una semana

# ── Notion: Pull (sincronizar cambios de vuelta) ──
python -m meeting_assistant notion-pull                               # Sync desde Notion
python -m meeting_assistant notion-pull --show-manual                 # Mostrar tareas manuales
```

---

## Flujo completo

```
.docx (transcripcion)
  │  load_transcript()
  ▼
Texto crudo
  │  preprocess_transcript()         ← -30 a 40% de caracteres
  ▼
Texto limpio
  │  auto-deteccion de contexto      ← infiere tipo de reunion
  │  estimate_requests()
  ├─ ≤45k chars → single-shot (1 request)
  └─ >45k chars → map-reduce (N chunks + 1 reduce)
  │  extract_structured()
  ▼
JSON validado
  │  to_markdown()
  ▼
Minuta.md ──────────────────────────────────────────→ Notion (pagina)
  │
  │  report (semanal/mensual)
  ▼
Reporte ejecutivo ──→ .md / .pdf ───────────────────→ Notion (pagina)
  │
  │  notion-tasks (push)
  ▼
Action items ──────────────────────────────────────→ Notion Tasks DB
                                                         │
                            notion-pull (sync) ←─────────┘
                                │
                                ▼
                    JSONs locales actualizados
                                │
                                ▼
                    Reportes reflejan cambios de Notion
```

![Flujo](docs/images/flujo-pipeline.png)

---

## Sincronizacion bidireccional con Notion

### Push (local → Notion)
```bash
python -m meeting_assistant notion-tasks          # Sube action items a DB
python -m meeting_assistant notion --file X.md    # Sube minuta como pagina
```

### Pull (Notion → local)
```bash
python -m meeting_assistant notion-pull           # Descarga cambios
python -m meeting_assistant report --tipo semanal # Regenerar con cambios
```

### Ciclo de trabajo
1. Procesas transcripciones → se generan JSONs y MDs
2. `notion-tasks` → sube tareas a Notion
3. En Notion: marcas tareas como `done`, cambias prioridad, agregas tareas manuales
4. `notion-pull` → sincroniza cambios de vuelta a los JSONs
5. `report` → el reporte refleja el estado actual de las tareas

### Deteccion automatica de proyectos
Al subir tareas, el sistema infiere el proyecto del nombre de archivo/titulo:

| Keyword en titulo | Proyecto asignado |
|-------------------|-------------------|
| chinalco | Chinalco |
| mmm | Plataforma MMM |
| hh4m | HH4M |
| english | English for Miners |
| fms | FMS |
| daily, codea | CODEa General |

Puedes editar el mapeo en `notion_sync.py` (`_infer_project`) o asignar proyecto manualmente en Notion.

---

## Reportes ejecutivos

Optimizados para gerencia: formato breve, bullets concisos, indicadores de estado.

| Formato | Uso |
|---------|-----|
| `.json` | Datos crudos, integraciones |
| `.md` | Control personal, Notion |
| `.pdf` | Enviar a gerencia |
| Notion | Pagina directa en tu workspace |

![Reporte PDF](docs/images/reporte-pdf.png)

Comando rapido:
```bash
python -m meeting_assistant report --tipo semanal --pdf --notion
```

---

## Imagenes para el README

Para agregar screenshots al repositorio:

1. Guardar capturas en `docs/images/`:
   ```
   docs/images/
   ├── pipeline-overview.png      ← Diagrama general (opcional)
   ├── notion-tasks-db.png        ← Captura de la DB de Tasks en Notion
   ├── flujo-pipeline.png         ← Diagrama del flujo (opcional)
   ├── reporte-pdf.png            ← Ejemplo de PDF generado
   ├── notion-minutas.png         ← Vista de minutas en Notion
   └── cli-output.png             ← Ejemplo de output del CLI
   ```

2. Referenciarlas en el README con rutas relativas:
   ```markdown
   ![Descripcion](docs/images/nombre-archivo.png)
   ```

3. Commitear las imagenes:
   ```bash
   git add docs/images/*.png
   git commit -m "Add README screenshots"
   ```

> Las imagenes se renderizan automaticamente en GitHub al hacer push.

---

## Script automatizado

Para generar reportes automaticamente cada viernes:

**Windows (Task Scheduler):**
```
Accion: Start a program
Programa: C:\ruta\a\.venv\Scripts\python.exe
Argumentos: -m meeting_assistant report --tipo semanal --pdf
Directorio: C:\ruta\a\6_Meeting_Assistant\src
Trigger: Semanal, viernes, 18:00
```

**Linux/Mac (cron):**
```bash
# Reporte semanal cada viernes a las 18:00
0 18 * * 5 cd /ruta/6_Meeting_Assistant/src && /ruta/.venv/bin/python -m meeting_assistant report --tipo semanal --pdf

# Reporte mensual el ultimo dia del mes
0 18 28-31 * * [ "$(date -d tomorrow +\%d)" = "01" ] && cd /ruta/src && .venv/bin/python -m meeting_assistant report --tipo mensual --pdf
```

---

## Optimizacion para Free Tier

| Tecnica | Efecto |
|---------|--------|
| Preprocesamiento agresivo | -30 a 40% de caracteres enviados |
| Umbral single-shot alto (45k) | La mayoria de reuniones usan 1 request |
| Cache de outputs | 0 requests en re-ejecuciones |
| Map-reduce solo si es necesario | Chunks grandes (30k) → menos bloques |
| Stats/search/tracking sin LLM | 0 requests para analisis |

**Consumo estimado:**
- Reunion tipica de 1h: **1 request**
- Reunion larga (>45k chars): **3-4 requests**
- Reporte semanal: **1 request**

---

## Dependencias principales

| Paquete | Version | Uso |
|---------|---------|-----|
| `google-genai` | 1.64.0 | Gemini API |
| `python-docx` | 1.2.0 | Lectura de .docx |
| `python-dotenv` | 1.2.1 | Variables de entorno |
| `fpdf2` | 2.8.7 | Generacion de PDF |
| `notion-client` | 3.0.0 | Notion API |
| `httpx` | 0.28.1 | HTTP client (Notion raw API) |

Python 3.12+

---

## Limitaciones (Free Tier Gemini)

- ~15-20 requests por dia por proyecto (varia segun modelo)
- `count_tokens` consume 1 request (esta desactivado por defecto)
- Si todas las keys del mismo proyecto Google Cloud estan agotadas, esperar 24h
- Notion API tiene limite de 3 requests/segundo (el codigo ya maneja batches)

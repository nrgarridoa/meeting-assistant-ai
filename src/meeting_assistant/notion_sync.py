"""
Sincronizacion con Notion API.

Sube minutas y reportes como paginas, action items como entries en database.

Requisitos:
  1. pip install notion-client
  2. Crear una integracion interna en https://www.notion.so/my-integrations
  3. Agregar al .env:
       NOTION_TOKEN=ntn_xxx
       NOTION_MEETINGS_DB_ID=xxx    (database de minutas)
       NOTION_REPORTS_DB_ID=xxx     (database de reportes)
       NOTION_TASKS_DB_ID=xxx       (database de action items)
  4. Compartir las 3 databases con la integracion (Share > Invite)

Database de minutas (Meetings) — propiedades:
  - Title (title): titulo de la reunion

Database de reportes (Reports) — propiedades:
  - Title (title): titulo del reporte

Database de action items (Tasks) — propiedades:
  - Task (title): descripcion de la tarea
  - Owner (rich_text): responsable
  - Status (select): todo / in_progress / done / blocked
  - Priority (select): high / medium / low
  - Area (select): area funcional
  - Meeting (rich_text): reunion de origen
  - Date (date): fecha de la reunion
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def _get_notion_client(env_path: str = ".env"):
    """Crea y retorna un cliente de Notion."""
    load_dotenv(env_path)
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError(
            "NOTION_TOKEN no encontrado en .env. "
            "Crea una integracion en https://www.notion.so/my-integrations"
        )
    from notion_client import Client
    return Client(auth=token)


# ─────────────────────────────────────────────
# NOTION BLOCKS → MARKDOWN
# ─────────────────────────────────────────────

def _get_rich_text(rich_text_arr: list) -> str:
    """Extrae plain_text de un array rich_text de Notion."""
    return "".join(rt.get("plain_text", "") for rt in rich_text_arr)


def _fetch_table_rows(client, table_block_id: str) -> list[dict]:
    """Obtiene todas las filas de un bloque de tipo tabla."""
    rows = []
    has_more = True
    start_cursor = None
    while has_more:
        kwargs = {"block_id": table_block_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        try:
            resp = client.blocks.children.list(**kwargs)
        except Exception:
            break
        rows.extend(resp.get("results", []))
        has_more = resp.get("has_more", False)
        start_cursor = resp.get("next_cursor")
    return rows


def _fetch_all_blocks(client, page_id: str) -> list[dict]:
    """Obtiene todos los bloques de una pagina, incluyendo filas de tablas."""
    blocks = []
    has_more = True
    start_cursor = None
    while has_more:
        kwargs = {"block_id": page_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        try:
            resp = client.blocks.children.list(**kwargs)
        except Exception:
            break
        for block in resp.get("results", []):
            if block.get("type") == "table":
                rows = _fetch_table_rows(client, block["id"])
                block.setdefault("table", {})["children"] = rows
            blocks.append(block)
        has_more = resp.get("has_more", False)
        start_cursor = resp.get("next_cursor")
    return blocks


def _blocks_to_markdown(blocks: list[dict]) -> str:
    """Convierte bloques de Notion de vuelta a Markdown."""
    lines = []
    for block in blocks:
        btype = block.get("type", "")

        if btype == "heading_1":
            text = _get_rich_text(block["heading_1"].get("rich_text", []))
            lines.append(f"# {text}")
        elif btype == "heading_2":
            text = _get_rich_text(block["heading_2"].get("rich_text", []))
            lines.append(f"## {text}")
        elif btype == "heading_3":
            text = _get_rich_text(block["heading_3"].get("rich_text", []))
            lines.append(f"### {text}")
        elif btype == "bulleted_list_item":
            text = _get_rich_text(block["bulleted_list_item"].get("rich_text", []))
            # Detectar sub-items (indented bullets para evidencia)
            indent = "  " if block.get("_indent") else ""
            lines.append(f"{indent}- {text}")
        elif btype == "paragraph":
            text = _get_rich_text(block["paragraph"].get("rich_text", []))
            lines.append(text)
        elif btype == "quote":
            text = _get_rich_text(block["quote"].get("rich_text", []))
            lines.append(f"> {text}")
        elif btype == "divider":
            lines.append("---")
        elif btype == "table":
            table = block.get("table", {})
            rows = table.get("children", [])
            for row_idx, row in enumerate(rows):
                cells = [
                    _get_rich_text(cell) if cell else ""
                    for cell in row.get("table_row", {}).get("cells", [])
                ]
                lines.append("| " + " | ".join(cells) + " |")
                if row_idx == 0:
                    lines.append("|" + "|".join(["---|"] * len(cells)))
        elif btype == "child_page":
            pass  # Ignorar subpaginas
    return "\n".join(lines)


def _get_parent_page_id(page_type: str, env_path: str = ".env") -> str:
    """Obtiene el ID de la pagina padre segun el tipo (minuta -> Meetings, reporte -> Reports)."""
    load_dotenv(env_path)
    if page_type == "reporte":
        page_id = os.getenv("NOTION_REPORTS_DB_ID")
        var_name = "NOTION_REPORTS_DB_ID"
    else:
        page_id = os.getenv("NOTION_MEETINGS_DB_ID")
        var_name = "NOTION_MEETINGS_DB_ID"
    if not page_id:
        raise ValueError(f"{var_name} no encontrado en .env.")
    return page_id


def _md_to_notion_blocks(md_text: str) -> list[dict]:
    """
    Convierte Markdown basico a bloques de Notion.
    Soporta: headers (#, ##, ###), bullets (-), blockquotes (>),
    tablas (|), separadores (---), texto normal.
    """
    blocks = []
    lines = md_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Separador
        if stripped.startswith("---"):
            blocks.append({"type": "divider", "divider": {}})
            i += 1
            continue

        # Headers
        if stripped.startswith("### "):
            blocks.append({
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": stripped[4:]}}]},
            })
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append({
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": stripped[3:]}}]},
            })
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append({
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": stripped[2:]}}]},
            })
            i += 1
            continue

        # Blockquote
        if stripped.startswith("> "):
            blocks.append({
                "type": "quote",
                "quote": {"rich_text": [{"type": "text", "text": {"content": stripped[2:]}}]},
            })
            i += 1
            continue

        # Bullet
        if stripped.startswith("- "):
            blocks.append({
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": stripped[2:]}}],
                },
            })
            i += 1
            continue

        # Tabla — agrupar lineas de tabla
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i].strip()
                # Saltar separador de tabla (|---|---|)
                if not all(c in "-| " for c in row):
                    cells = [c.strip() for c in row.strip("|").split("|")]
                    table_lines.append(cells)
                i += 1
            if table_lines:
                n_cols = max(len(r) for r in table_lines)
                table_block = {
                    "type": "table",
                    "table": {
                        "table_width": n_cols,
                        "has_column_header": True,
                        "has_row_header": False,
                        "children": [],
                    },
                }
                for row in table_lines:
                    # Asegurar que todas las filas tengan el mismo num de columnas
                    while len(row) < n_cols:
                        row.append("")
                    table_block["table"]["children"].append({
                        "type": "table_row",
                        "table_row": {
                            "cells": [
                                [{"type": "text", "text": {"content": cell}}]
                                for cell in row
                            ]
                        },
                    })
                blocks.append(table_block)
            continue

        # Linea vacia
        if not stripped:
            i += 1
            continue

        # Texto normal (bold/italic/plain)
        content = stripped
        # Limpiar markdown inline basico
        content = content.replace("**", "").replace("__", "")
        content = content.replace("_", "").replace("*", "")
        blocks.append({
            "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": content}}]},
        })
        i += 1

    return blocks


def upload_to_notion(
    md_text: str,
    title: str,
    date: str | None = None,
    page_type: str = "minuta",
    env_path: str = ".env",
) -> dict:
    """
    Sube un documento Markdown como pagina en Notion.

    Args:
        md_text: Contenido Markdown completo.
        title: Titulo de la pagina.
        date: Fecha en formato YYYY-MM-DD (opcional).
        page_type: "minuta" o "reporte".
        env_path: Ruta al .env con NOTION_TOKEN y NOTION_DB_ID.

    Returns:
        dict con {"url": str, "page_id": str}
    """
    client = _get_notion_client(env_path)
    parent_id = _get_parent_page_id(page_type, env_path)

    properties = {
        "title": {"title": [{"text": {"content": title}}]},
    }

    blocks = _md_to_notion_blocks(md_text)

    # Notion API limita a 100 bloques por request
    children = blocks[:100]

    page = client.pages.create(
        parent={"page_id": parent_id},
        properties=properties,
        children=children,
    )

    page_url = page.get("url", "")
    page_id = page["id"]

    # Si hay mas de 100 bloques, agregar en batches
    remaining = blocks[100:]
    while remaining:
        batch = remaining[:100]
        remaining = remaining[100:]
        client.blocks.children.append(block_id=page_id, children=batch)

    return {"url": page_url, "page_id": page_id}


# ─────────────────────────────────────────────
# ACTION ITEMS → Notion Database
# ─────────────────────────────────────────────

def _get_tasks_db_id(env_path: str = ".env") -> str:
    """Obtiene el ID de la database de action items."""
    load_dotenv(env_path)
    db_id = os.getenv("NOTION_TASKS_DB_ID")
    if not db_id:
        raise ValueError(
            "NOTION_TASKS_DB_ID no encontrado en .env. "
            "Crea una database en Notion con columnas: "
            "Task (title), Owner (rich_text), Status (select), "
            "Priority (select), Area (select), Meeting (rich_text), Date (date)"
        )
    return db_id


def _notion_headers(token: str) -> dict:
    """Headers para llamadas directas a la Notion API."""
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _ensure_tasks_db_schema(token: str, db_id: str):
    """Asegura que la database de Tasks tenga las columnas necesarias."""
    import httpx
    headers = _notion_headers(token)

    resp = httpx.get(f"https://api.notion.com/v1/databases/{db_id}", headers=headers, timeout=30)
    resp.raise_for_status()
    existing_props = set(resp.json().get("properties", {}).keys())

    needed = {}
    # Rename default title column (e.g., "Nombre") to "Task"
    if "Task" not in existing_props:
        # Find the title column name
        for k, v in resp.json().get("properties", {}).items():
            if v.get("type") == "title" and k != "Task":
                needed[k] = {"name": "Task"}
                break
        else:
            needed["Task"] = {"title": {}}

    if "Status" not in existing_props:
        needed["Status"] = {
            "select": {"options": [
                {"name": "todo", "color": "default"},
                {"name": "in_progress", "color": "blue"},
                {"name": "done", "color": "green"},
                {"name": "blocked", "color": "red"},
            ]}
        }
    if "Priority" not in existing_props:
        needed["Priority"] = {
            "select": {"options": [
                {"name": "high", "color": "red"},
                {"name": "medium", "color": "yellow"},
                {"name": "low", "color": "default"},
            ]}
        }
    if "Owner" not in existing_props:
        needed["Owner"] = {"rich_text": {}}
    if "Area" not in existing_props:
        needed["Area"] = {"select": {"options": []}}
    if "Project" not in existing_props:
        needed["Project"] = {"select": {"options": []}}
    if "Meeting" not in existing_props:
        needed["Meeting"] = {"rich_text": {}}
    if "Date" not in existing_props:
        needed["Date"] = {"date": {}}

    if needed:
        httpx.patch(
            f"https://api.notion.com/v1/databases/{db_id}",
            headers=headers, json={"properties": needed}, timeout=30,
        ).raise_for_status()


def upload_tasks_to_notion(
    meetings: list[dict],
    env_path: str = ".env",
    *,
    update_existing: bool = True,
    out_dir=None,
) -> dict:
    """
    Sube action items de reuniones como entries en una database de Notion.

    Si update_existing=True, busca tareas existentes por texto similar
    y actualiza su status en vez de duplicar.
    Salta tareas marcadas con notion_deleted=True.
    Si out_dir se provee, guarda notion_page_id en el JSON local al crear.

    Args:
        meetings: Lista de JSONs estructurados (con _source_file y _date).
        env_path: Ruta al .env.
        update_existing: Si True, actualiza tareas que ya existen en Notion.
        out_dir: Directorio de outputs para guardar notion_page_id en JSONs locales.

    Returns:
        dict con {created: int, updated: int, skipped: int, errors: list[str]}
    """
    import json
    from pathlib import Path

    client = _get_notion_client(env_path)
    tasks_db_id = _get_tasks_db_id(env_path)

    # Asegurar que la DB tenga las columnas necesarias
    load_dotenv(env_path)
    _ensure_tasks_db_schema(os.getenv("NOTION_TOKEN"), tasks_db_id)

    # Cargar tareas existentes en Notion para dedup
    existing = {}
    if update_existing:
        existing = _load_existing_tasks(client, tasks_db_id)

    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    for m in meetings:
        source = m.get("_source_file", "?")
        date = m["_date"].strftime("%Y-%m-%d") if m.get("_date") else None
        title = m.get("meeting_title", source)
        project = _infer_project(source, title)

        json_path = Path(out_dir) / f"{source}_structured.json" if out_dir and source and source != "?" else None
        json_modified = False

        for a in m.get("action_items", []):
            task_text = a.get("task", "").strip()
            if not task_text:
                continue

            # Saltar tareas eliminadas en Notion via notion-pull
            if a.get("notion_deleted"):
                result["skipped"] += 1
                continue

            try:
                # Check if task already exists
                existing_id = a.get("notion_page_id") or _find_existing_task(task_text, existing)

                if existing_id and update_existing:
                    # Update status only
                    _update_task_status(client, existing_id, a.get("status", "todo"))
                    result["updated"] += 1
                elif existing_id:
                    result["skipped"] += 1
                else:
                    # Create new entry
                    page_id = _create_task_entry(
                        client, tasks_db_id,
                        task=task_text,
                        owner=a.get("owner", ""),
                        status=a.get("status", "todo"),
                        priority=a.get("priority", "medium"),
                        area=a.get("area", ""),
                        project=project,
                        meeting=title,
                        date=date,
                    )
                    result["created"] += 1
                    # Guardar page_id en el action_item para detectar deletions futuras
                    a["notion_page_id"] = page_id
                    json_modified = True
            except Exception as e:
                result["errors"].append(f"{task_text[:50]}...: {e}")

        # Guardar JSON local si se agregaron notion_page_ids
        if json_modified and json_path and json_path.exists():
            try:
                # Recargar para no perder campos que no estan en memoria (_date serializado, etc)
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                # Actualizar notion_page_id en cada action_item por texto exacto
                notion_ids = {a.get("task", ""): a.get("notion_page_id") for a in m.get("action_items", []) if a.get("notion_page_id")}
                for ai in raw.get("action_items", []):
                    pid = notion_ids.get(ai.get("task", ""))
                    if pid:
                        ai["notion_page_id"] = pid
                json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass  # No critico — el page_id se puede recuperar en el proximo pull

    return result


def _load_existing_tasks(client, db_id: str) -> dict[str, str]:
    """
    Carga tareas existentes de la database de Notion.
    Returns: {task_text_lower: page_id}
    """
    import httpx

    tasks = {}
    has_more = True
    start_cursor = None

    # Use httpx directly since notion-client v3 removed databases.query
    headers = {
        "Authorization": f"Bearer {client.options.auth}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    url = f"https://api.notion.com/v1/databases/{db_id}/query"

    while has_more:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor

        try:
            resp_raw = httpx.post(url, headers=headers, json=body, timeout=30)
            resp_raw.raise_for_status()
            resp = resp_raw.json()
        except Exception:
            # Database might be empty or inaccessible — return empty
            return tasks

        for page in resp.get("results", []):
            # Find the title property (could be "title", "Task", "Name", etc.)
            for prop_val in page.get("properties", {}).values():
                if prop_val.get("type") == "title":
                    title_arr = prop_val.get("title", [])
                    if title_arr:
                        text = title_arr[0].get("plain_text", "").strip().lower()
                        if text:
                            tasks[text] = page["id"]
                    break

        has_more = resp.get("has_more", False)
        start_cursor = resp.get("next_cursor")

    return tasks


def _find_existing_task(task_text: str, existing: dict[str, str]) -> str | None:
    """Busca si la tarea ya existe (comparacion case-insensitive)."""
    normalized = task_text.strip().lower()
    if normalized in existing:
        return existing[normalized]
    # Buscar substring match para tareas muy similares
    for existing_text, page_id in existing.items():
        if normalized in existing_text or existing_text in normalized:
            return page_id
    return None


def _infer_project(source_file: str, meeting_title: str) -> str:
    """Infiere el proyecto del nombre de archivo o titulo de reunion."""
    text = f"{source_file} {meeting_title}".lower()
    # Mapeo de keywords a nombres de proyecto
    project_map = {
        "chinalco": "Chinalco",
        "mmm": "Plataforma MMM",
        "hh4m": "HH4M",
        "english": "English for Miners",
        "bootcamps": "Btcs Mining Tech",
        "fms": "FMS",
    }
    for keyword, project in project_map.items():
        if keyword in text:
            return project
    if "daily" in text or "codea" in text:
        return "CODEa General"
    return ""


def _create_task_entry(
    client, db_id: str, *,
    task: str, owner: str, status: str, priority: str,
    area: str, project: str, meeting: str, date: str | None,
):
    """Crea una nueva entry en la database de tasks."""
    properties = {
        "Task": {"title": [{"text": {"content": task}}]},
        "Status": {"select": {"name": status}},
        "Priority": {"select": {"name": priority}},
    }
    if owner:
        properties["Owner"] = {
            "rich_text": [{"text": {"content": owner}}]
        }
    if area:
        properties["Area"] = {"select": {"name": area}}
    if project:
        properties["Project"] = {"select": {"name": project}}
    if meeting:
        properties["Meeting"] = {
            "rich_text": [{"text": {"content": meeting}}]
        }
    if date:
        properties["Date"] = {"date": {"start": date}}

    page = client.pages.create(parent={"database_id": db_id}, properties=properties)
    return page["id"]


def _update_task_status(client, page_id: str, status: str):
    """Actualiza el status de una tarea existente."""
    client.pages.update(
        page_id=page_id,
        properties={"Status": {"select": {"name": status}}},
    )


# ─────────────────────────────────────────────
# NOTION PULL — Sync changes back to local JSONs
# ─────────────────────────────────────────────

def _extract_prop_text(prop: dict) -> str:
    """Extrae texto de una propiedad de Notion (title, rich_text, select)."""
    ptype = prop.get("type", "")
    if ptype == "title":
        arr = prop.get("title", [])
        return arr[0].get("plain_text", "").strip() if arr else ""
    if ptype == "rich_text":
        arr = prop.get("rich_text", [])
        return arr[0].get("plain_text", "").strip() if arr else ""
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if ptype == "date":
        d = prop.get("date")
        return d.get("start", "") if d else ""
    return ""


def pull_tasks_from_notion(
    env_path: str = ".env",
) -> list[dict]:
    """
    Lee todas las tareas de la database de Notion con propiedades completas.

    Returns:
        Lista de dicts con: task, owner, status, priority, area, meeting, date, page_id
    """
    import httpx

    load_dotenv(env_path)
    token = os.getenv("NOTION_TOKEN")
    if not token:
        raise ValueError("NOTION_TOKEN no encontrado en .env.")
    db_id = _get_tasks_db_id(env_path)

    headers = _notion_headers(token)
    url = f"https://api.notion.com/v1/databases/{db_id}/query"

    tasks = []
    has_more = True
    start_cursor = None

    while has_more:
        body = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor

        resp_raw = httpx.post(url, headers=headers, json=body, timeout=30)
        resp_raw.raise_for_status()
        resp = resp_raw.json()

        for page in resp.get("results", []):
            props = page.get("properties", {})
            task_text = _extract_prop_text(props.get("Task", {}))
            if not task_text:
                continue

            tasks.append({
                "task": task_text,
                "owner": _extract_prop_text(props.get("Owner", {})),
                "status": _extract_prop_text(props.get("Status", {})) or "todo",
                "priority": _extract_prop_text(props.get("Priority", {})) or "medium",
                "area": _extract_prop_text(props.get("Area", {})),
                "project": _extract_prop_text(props.get("Project", {})),
                "meeting": _extract_prop_text(props.get("Meeting", {})),
                "date": _extract_prop_text(props.get("Date", {})),
                "page_id": page["id"],
            })

        has_more = resp.get("has_more", False)
        start_cursor = resp.get("next_cursor")

    return tasks


def sync_notion_to_local(
    out_dir,
    env_path: str = ".env",
    solo_tareas: bool = False,
    solo_paginas: bool = False,
    refresh_tasks: bool = False,
) -> dict:
    """
    Sincroniza cambios de Notion de vuelta a los JSONs locales.

    FASE 1 — Contenido de meeting pages:
      Para cada JSON local con notion_meeting_page_id, lee el contenido
      de la pagina en Notion, reconstruye el MD y actualiza el JSON local
      (titulo, resumen, temas, decisiones, tareas, etc.) y el MD local.

    FASE 2 — Tasks Database:
      Lee todas las tareas de la Tasks DB y actualiza status/priority/owner/area
      en los JSONs locales. Detecta eliminaciones y las marca notion_deleted.

    Returns:
        dict con {pages_updated, updated, deleted, manual, unmatched, files_modified}
    """
    import json
    from pathlib import Path
    from difflib import SequenceMatcher
    from .export_markdown import parse_md_to_structured, to_markdown

    out_dir = Path(out_dir)
    client = _get_notion_client(env_path)

    # Cargar todos los JSONs locales
    local_files = {}  # {path: data}
    for p in sorted(out_dir.glob("*_structured.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            local_files[p] = data
        except Exception:
            continue

    result = {
        "pages_updated": 0,
        "updated": 0, "deleted": 0,
        "manual": 0, "unmatched": 0,
        "new_tasks_added": 0,
        "files_modified": set(),
    }
    phase1_modified = set()  # archivos actualizados desde contenido de Notion page

    # Lazy init del cliente AI (solo si --refresh-tasks)
    _ai_client = _ai_model = _ai_km = None
    if refresh_tasks and not solo_tareas:
        try:
            from .gemini_client import make_client
            _ai_client, _ai_model, _ai_km = make_client(env_path)
            print("  [--refresh-tasks] Cliente AI inicializado.")
        except Exception as e:
            print(f"  [warn] No se pudo inicializar cliente AI para refresh-tasks: {e}")

    # ── FASE 1: Pull contenido de meeting pages ───────────────────────────────
    if solo_tareas:
        print("  [--solo-tareas] Omitiendo sync de contenido de páginas.")
    for path, data in (local_files.items() if not solo_tareas else []):
        meeting_page_id = data.get("notion_meeting_page_id")
        if not meeting_page_id:
            continue

        try:
            blocks = _fetch_all_blocks(client, meeting_page_id)
            if not blocks:
                continue

            notion_md = _blocks_to_markdown(blocks)
            if not notion_md.strip():
                continue

            # Parsear el MD de Notion → estructura JSON actualizada
            updated_data = parse_md_to_structured(notion_md, existing_json=data)

            # Verificar si hubo cambios reales comparando campos clave
            changed = False
            for field in ("meeting_title", "summary_top_bullets", "topics",
                          "decisions", "action_items", "risks_blockers",
                          "open_questions", "next_steps", "speakers"):
                if updated_data.get(field) != data.get(field):
                    changed = True
                    break

            if changed:
                local_files[path] = updated_data
                result["pages_updated"] += 1
                result["files_modified"].add(path.name)
                phase1_modified.add(path)
                print(f"  [page] {path.name} actualizado desde Notion")

                # ── refresh-tasks: buscar tareas nuevas en el contenido editado ──
                if _ai_client:
                    try:
                        from .extract_structured import extract_new_tasks
                        new_tasks = extract_new_tasks(
                            _ai_client, _ai_model, _ai_km,
                            updated_data,
                            updated_data.get("action_items", []),
                        )
                        if new_tasks:
                            local_files[path]["action_items"] = (
                                local_files[path].get("action_items", []) + new_tasks
                            )
                            result["new_tasks_added"] += len(new_tasks)
                            print(f"    +{len(new_tasks)} tarea(s) nueva(s) detectada(s)")
                    except Exception as e:
                        print(f"  [warn] refresh-tasks fallo para {path.name}: {e}")

        except Exception as e:
            print(f"  [warn] No se pudo leer pagina Notion para {path.name}: {e}")
            continue

    # ── FASE 2: Sync Tasks Database ───────────────────────────────────────────
    if solo_paginas:
        print("  [--solo-paginas] Omitiendo sync de Tasks DB.")
        # Guardar cambios de fase 1 y salir
        for path, data in local_files.items():
            if path.name in result["files_modified"]:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                if path in phase1_modified:
                    md_path = path.parent / path.name.replace("_structured.json", ".md")
                    md_path.write_text(to_markdown(data), encoding="utf-8")
        result["files_modified"] = sorted(result["files_modified"])
        return result

    notion_tasks = pull_tasks_from_notion(env_path)
    if not notion_tasks:
        result["files_modified"] = sorted(result["files_modified"])
        return result

    manual_tasks = []
    active_page_ids = {nt["page_id"] for nt in notion_tasks if nt.get("page_id")}

    for nt in notion_tasks:
        if not nt["meeting"]:
            manual_tasks.append(nt)
            continue

        matched = False
        for path, data in local_files.items():
            for ai in data.get("action_items", []):
                local_text = ai.get("task", "").strip().lower()
                notion_text = nt["task"].strip().lower()

                page_id_match = ai.get("notion_page_id") and ai["notion_page_id"] == nt["page_id"]
                text_match = local_text == notion_text or (
                    len(local_text) > 10
                    and SequenceMatcher(None, local_text, notion_text).ratio() > 0.85
                )

                if page_id_match or text_match:
                    changed = False
                    for field in ("status", "priority", "owner", "area"):
                        notion_val = nt.get(field, "")
                        if notion_val and notion_val != ai.get(field, ""):
                            ai[field] = notion_val
                            changed = True
                    if not ai.get("notion_page_id") and nt.get("page_id"):
                        ai["notion_page_id"] = nt["page_id"]
                        changed = True
                    if ai.get("notion_deleted"):
                        ai.pop("notion_deleted")
                        changed = True
                    if changed:
                        result["updated"] += 1
                        result["files_modified"].add(path.name)
                    matched = True
                    break
            if matched:
                break

        if not matched:
            manual_tasks.append(nt)
            result["unmatched"] += 1

    # Detectar tareas eliminadas en Notion
    for path, data in local_files.items():
        for ai in data.get("action_items", []):
            pid = ai.get("notion_page_id")
            if pid and pid not in active_page_ids and not ai.get("notion_deleted"):
                ai["notion_deleted"] = True
                result["deleted"] += 1
                result["files_modified"].add(path.name)

    # Guardar todos los JSONs modificados (fase 1 + fase 2 ya aplicados en memoria)
    for path, data in local_files.items():
        if path.name in result["files_modified"]:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            # Regenerar MD solo para los archivos que cambiaron en fase 1
            if path in phase1_modified:
                md_path = path.parent / path.name.replace("_structured.json", ".md")
                md_path.write_text(to_markdown(data), encoding="utf-8")

    # Guardar tareas manuales
    if manual_tasks:
        manual_path = out_dir / "_notion_manual_tasks.json"
        manual_path.write_text(
            json.dumps(manual_tasks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result["manual"] = len(manual_tasks)

    result["files_modified"] = sorted(result["files_modified"])
    return result


def _filename_to_title(stem: str) -> str:
    """Retorna el stem del archivo tal cual, sin transformacion."""
    return stem


def _get_uploaded_meeting_pages(client, parent_page_id: str) -> dict[str, str]:
    """
    Lista las paginas ya subidas como hijos del parent page de Meetings.
    Retorna dict {title_lower: page_id} para comparacion y tracking.
    """
    pages = {}
    has_more = True
    start_cursor = None

    while has_more:
        kwargs = {"block_id": parent_page_id, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        try:
            resp = client.blocks.children.list(**kwargs)
        except Exception:
            break
        for block in resp.get("results", []):
            if block.get("type") == "child_page":
                title = block.get("child_page", {}).get("title", "")
                if title:
                    pages[title.lower()] = block["id"]
        has_more = resp.get("has_more", False)
        start_cursor = resp.get("next_cursor")

    return pages


def link_notion_pages_to_local(
    out_dir,
    env_path: str = ".env",
) -> dict:
    """
    Empareja paginas existentes en Notion con los JSONs locales y guarda
    notion_meeting_page_id en cada JSON que aun no lo tenga.

    Usa matching exacto por titulo (stem) y fuzzy como fallback (ratio > 0.70).
    No sube ni modifica nada en Notion.

    Returns:
        dict con {linked: int, already_linked: int, unmatched: list[str]}
    """
    import json
    from pathlib import Path
    from difflib import SequenceMatcher

    out_dir = Path(out_dir)
    client = _get_notion_client(env_path)
    parent_id = _get_parent_page_id("minuta", env_path)

    notion_pages = _get_uploaded_meeting_pages(client, parent_id)
    print(f"  Paginas en Notion: {len(notion_pages)}")

    result = {"linked": 0, "already_linked": 0, "unmatched": []}

    json_files = sorted(out_dir.glob("*_structured.json"))
    for json_path in json_files:
        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if raw.get("notion_meeting_page_id"):
            result["already_linked"] += 1
            continue

        stem = json_path.stem.replace("_structured", "")
        stem_lower = stem.lower()

        # Match exacto
        matched_id = notion_pages.get(stem_lower)

        # Fuzzy fallback
        if not matched_id:
            best_ratio = 0
            for notion_title_lower, page_id in notion_pages.items():
                ratio = SequenceMatcher(None, stem_lower, notion_title_lower).ratio()
                if ratio > best_ratio and ratio > 0.70:
                    best_ratio = ratio
                    matched_id = page_id

        if matched_id:
            raw["notion_meeting_page_id"] = matched_id
            json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [link] {json_path.name}")
            result["linked"] += 1
        else:
            result["unmatched"].append(stem)

    return result


def upload_pending_meetings(
    out_dir,
    env_path: str = ".env",
) -> dict:
    """
    Detecta MDs en out_dir que aun no estan en Notion y los sube.
    Guarda notion_meeting_page_id en el JSON correspondiente para habilitar pull futuro.

    Returns:
        dict con {uploaded: int, skipped: int, errors: list[str], pages: list}
    """
    import json
    import re as _re
    from pathlib import Path

    out_dir = Path(out_dir)
    client = _get_notion_client(env_path)
    parent_id = _get_parent_page_id("minuta", env_path)

    # Obtener paginas ya subidas {title_lower: page_id}
    uploaded_pages = _get_uploaded_meeting_pages(client, parent_id)

    # Listar MDs en outputs (excluir reportes y archivos internos)
    md_files = sorted(
        p for p in out_dir.glob("*.md")
        if not p.name.startswith("_") and not p.name.startswith("reporte")
    )

    result = {"uploaded": 0, "skipped": 0, "errors": [], "pages": []}

    for md_path in md_files:
        title = _filename_to_title(md_path.stem)
        json_path = out_dir / f"{md_path.stem}_structured.json"

        # Verificar si ya fue subido
        if title.lower() in uploaded_pages:
            existing_page_id = uploaded_pages[title.lower()]
            # Guardar page_id en JSON si aun no lo tiene
            if json_path.exists():
                try:
                    raw = json.loads(json_path.read_text(encoding="utf-8"))
                    if not raw.get("notion_meeting_page_id"):
                        raw["notion_meeting_page_id"] = existing_page_id
                        json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
            print(f"  [skip] {md_path.name} → ya en Notion")
            result["skipped"] += 1
            continue

        try:
            md_text = md_path.read_text(encoding="utf-8")
            date = None
            m = _re.match(r"^(\d{2})(\d{2})(\d{2})_", md_path.stem)
            if m:
                yy, mm, dd = m.group(1), m.group(2), m.group(3)
                date = f"20{yy}-{mm}-{dd}"

            page_info = upload_to_notion(md_text, title=title, date=date,
                                         page_type="minuta", env_path=env_path)
            url = page_info["url"]
            page_id = page_info["page_id"]

            # Guardar notion_meeting_page_id en el JSON local
            if json_path.exists():
                try:
                    raw = json.loads(json_path.read_text(encoding="utf-8"))
                    raw["notion_meeting_page_id"] = page_id
                    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass

            print(f"  [ok]   {md_path.name} → {url}")
            result["uploaded"] += 1
            result["pages"].append({"file": md_path.name, "title": title, "url": url, "page_id": page_id})
        except Exception as e:
            msg = f"{md_path.name}: {e}"
            print(f"  [err]  {msg}")
            result["errors"].append(msg)

    return result


def load_manual_tasks(out_dir) -> list[dict]:
    """
    Carga tareas manuales de Notion (las que no vienen de reuniones).
    Retorna lista de action_items en el mismo formato que extract_structured.

    Util para inyectar en reportes y stats.
    """
    import json
    from pathlib import Path

    manual_path = Path(out_dir) / "_notion_manual_tasks.json"
    if not manual_path.exists():
        return []

    try:
        raw = json.loads(manual_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    # Convertir al formato de action_items
    items = []
    for t in raw:
        items.append({
            "task": t.get("task", ""),
            "owner": t.get("owner", ""),
            "status": t.get("status", "todo"),
            "priority": t.get("priority", "medium"),
            "area": t.get("area", ""),
            "evidence": f"[Manual - Notion] {t.get('date', '')}",
        })
    return items

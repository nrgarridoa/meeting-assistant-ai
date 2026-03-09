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
) -> str:
    """
    Sube un documento Markdown como pagina en una database de Notion.

    Args:
        md_text: Contenido Markdown completo.
        title: Titulo de la pagina.
        date: Fecha en formato YYYY-MM-DD (opcional).
        page_type: "minuta" o "reporte".
        env_path: Ruta al .env con NOTION_TOKEN y NOTION_DB_ID.

    Returns:
        URL de la pagina creada en Notion.
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

    # Si hay mas de 100 bloques, agregar en batches
    remaining = blocks[100:]
    page_id = page["id"]
    while remaining:
        batch = remaining[:100]
        remaining = remaining[100:]
        client.blocks.children.append(block_id=page_id, children=batch)

    return page_url


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
) -> dict:
    """
    Sube action items de reuniones como entries en una database de Notion.

    Si update_existing=True, busca tareas existentes por texto similar
    y actualiza su status en vez de duplicar.

    Args:
        meetings: Lista de JSONs estructurados (con _source_file y _date).
        env_path: Ruta al .env.
        update_existing: Si True, actualiza tareas que ya existen en Notion.

    Returns:
        dict con {created: int, updated: int, errors: list[str]}
    """
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

        for a in m.get("action_items", []):
            task_text = a.get("task", "").strip()
            if not task_text:
                continue

            try:
                # Check if task already exists
                existing_id = _find_existing_task(task_text, existing)

                if existing_id and update_existing:
                    # Update status only
                    _update_task_status(client, existing_id, a.get("status", "todo"))
                    result["updated"] += 1
                elif existing_id:
                    result["skipped"] += 1
                else:
                    # Create new entry
                    _create_task_entry(
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
            except Exception as e:
                result["errors"].append(f"{task_text[:50]}...: {e}")

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

    client.pages.create(parent={"database_id": db_id}, properties=properties)


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
) -> dict:
    """
    Sincroniza cambios de Notion de vuelta a los JSONs locales.

    1. Lee todas las tareas de Notion con status/priority/owner actuales.
    2. Para cada tarea con Meeting asignado, busca el JSON local correspondiente
       y actualiza el action_item con los valores de Notion.
    3. Tareas sin Meeting (manuales) se guardan en un archivo separado
       (_notion_manual_tasks.json) para inclusion en reportes.

    Returns:
        dict con {updated: int, manual: int, unmatched: int, files_modified: list[str]}
    """
    import json
    from pathlib import Path
    from difflib import SequenceMatcher

    out_dir = Path(out_dir)
    notion_tasks = pull_tasks_from_notion(env_path)

    if not notion_tasks:
        return {"updated": 0, "manual": 0, "unmatched": 0, "files_modified": []}

    # Cargar todos los JSONs locales
    local_files = {}  # {path: data}
    for p in sorted(out_dir.glob("*_structured.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            local_files[p] = data
        except Exception:
            continue

    result = {"updated": 0, "manual": 0, "unmatched": 0, "files_modified": set()}
    manual_tasks = []

    for nt in notion_tasks:
        # Tareas manuales (sin meeting de origen)
        if not nt["meeting"]:
            manual_tasks.append(nt)
            continue

        # Buscar en JSONs locales
        matched = False
        for path, data in local_files.items():
            for ai in data.get("action_items", []):
                local_text = ai.get("task", "").strip().lower()
                notion_text = nt["task"].strip().lower()

                # Match exacto o por similitud alta
                if local_text == notion_text or (
                    len(local_text) > 10
                    and SequenceMatcher(None, local_text, notion_text).ratio() > 0.85
                ):
                    # Actualizar campos del action_item local
                    changed = False
                    for field in ("status", "priority", "owner", "area"):
                        notion_val = nt.get(field, "")
                        if notion_val and notion_val != ai.get(field, ""):
                            ai[field] = notion_val
                            changed = True

                    if changed:
                        result["updated"] += 1
                        result["files_modified"].add(path.name)
                    matched = True
                    break
            if matched:
                break

        if not matched:
            # Tiene meeting pero no se encontro el JSON — tratar como manual
            manual_tasks.append(nt)
            result["unmatched"] += 1

    # Guardar JSONs locales modificados
    for path, data in local_files.items():
        if path.name in result["files_modified"]:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

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

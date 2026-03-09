"""
CLI para Meeting Assistant.

Comandos principales:
  process       Procesar transcripciones .docx pendientes → JSON + MD
  notion-link   Enlazar JSONs locales con sus paginas ya existentes en Notion
  notion-push   Subir MDs nuevos a Notion (auto-detecta pendientes)
  notion-pull   Sync Notion → local (--solo-paginas | --solo-tareas)
  notion-tasks  Subir/actualizar tareas en Tasks DB de Notion
  report        Reporte ejecutivo semanal o mensual (--pdf --notion --email)
  stats         Dashboard de metricas KPI (--compare --pdf --project)
  tracking      Seguimiento de action items entre periodos
  search        Buscar en todas las reuniones procesadas
  template      Generar agenda pre-llenada para próxima reunión
  email         Enviar reporte por correo SMTP
  flows         Ver todos los flujos de trabajo con ejemplos detallados

Flujo rapido diario:
  process → notion-push → notion-pull --solo-paginas → notion-tasks → notion-pull --solo-tareas

Ver flujos completos:
  python -m meeting_assistant flows
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ── Rutas base (relativas al directorio del proyecto) ──
def _find_project_root() -> Path:
    """Busca la raiz del proyecto (donde esta .env)."""
    candidates = [Path.cwd(), Path(__file__).resolve().parent.parent.parent]
    for p in candidates:
        if (p / ".env").exists():
            return p
    return Path.cwd()


ROOT = _find_project_root()
ENV_PATH = str(ROOT / ".env")
TRANSCRIPTIONS_DIR = ROOT / "transcriptions"
OUT_DIR = ROOT / "outputs"
REPORTS_DIR = ROOT / "reports"


def cmd_process(args):
    """Procesa todas las transcripciones pendientes."""
    from .gemini_client import make_client
    from .io_transcripts import list_transcripts, load_transcript
    from .preprocess import preprocess_transcript
    from .extract_structured import extract_structured, estimate_requests, load_cached
    from .export_markdown import to_markdown

    OUT_DIR.mkdir(exist_ok=True)
    client, model, km = make_client(ENV_PATH)
    print(f"Modelo: {model}")

    transcripts = list_transcripts(TRANSCRIPTIONS_DIR)
    print(f"Transcripciones encontradas: {len(transcripts)}\n")

    for t_path in transcripts:
        stem = t_path.stem
        out_json = OUT_DIR / f"{stem}_structured.json"

        cached = load_cached(out_json)
        if cached:
            print(f"  [cache] {t_path.name}")
            continue

        print(f"  Procesando {t_path.name}...")
        raw = load_transcript(t_path)
        clean = preprocess_transcript(raw)
        plan = estimate_requests(clean, max_chars_single_shot=45000, chunk_chars=30000)
        print(f"    Modo: {plan['mode']} | Requests: {plan['requests_generate']}")

        data = extract_structured(
            client, model, km, clean,
            meeting_context=args.context or "",
        )

        out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path = OUT_DIR / f"{stem}.md"
        md_path.write_text(to_markdown(data), encoding="utf-8")
        print(f"    Guardado: {out_json.name} + {md_path.name}")

    print("\nProcesamiento completo.")


def cmd_report(args):
    """Genera reporte semanal o mensual."""
    from .gemini_client import make_client
    from .report import (
        load_all_meetings, filter_by_date_range,
        get_week_range, get_month_range,
        generate_report, report_to_markdown,
    )

    REPORTS_DIR.mkdir(exist_ok=True)
    client, model, km = make_client(ENV_PATH)

    ref = datetime.strptime(args.fecha, "%Y-%m-%d") if args.fecha else datetime.now()
    tipo = args.tipo

    if tipo == "semanal":
        date_from, date_to = get_week_range(ref)
        label = f"Semana {date_from.strftime('%d %b')} - {date_to.strftime('%d %b %Y')}"
    elif tipo == "mensual":
        date_from, date_to = get_month_range(ref)
        label = ref.strftime("%B %Y")
    else:
        print(f"Tipo invalido: {tipo}. Usa 'semanal' o 'mensual'.")
        sys.exit(1)

    all_meetings = load_all_meetings(OUT_DIR)
    current = filter_by_date_range(all_meetings, date_from, date_to)

    if not current:
        print(f"No hay reuniones para {label}.")
        sys.exit(0)

    # Periodo anterior
    if tipo == "semanal":
        prev_from = date_from - timedelta(days=7)
        prev_to = date_from - timedelta(seconds=1)
    else:
        prev_to = date_from - timedelta(seconds=1)
        prev_from, _ = get_month_range(prev_to)
    prev = filter_by_date_range(all_meetings, prev_from, prev_to)

    print(f"Generando reporte {tipo}: {label}")
    print(f"  Reuniones: {len(current)} | Contexto anterior: {'si' if prev else 'no'}")

    report_data = generate_report(client, model, km, current, label, prev or None)

    # Stats para secciones de datos reales en el MD
    from .stats import compute_stats
    stats_data = compute_stats(current)

    safe_label = label.replace(" ", "_").replace("/", "-")
    out_json = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.json"
    out_md = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.md"

    out_json.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_text = report_to_markdown(report_data, stats=stats_data)
    out_md.write_text(md_text, encoding="utf-8")
    print(f"  JSON: {out_json}")
    print(f"  MD:   {out_md}")

    out_pdf = None
    if args.pdf:
        from .pdf_export import report_to_pdf
        out_pdf = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.pdf"
        report_to_pdf(report_data, out_pdf, stats=stats_data)
        print(f"  PDF:  {out_pdf}")

    if args.notion:
        from .notion_sync import upload_to_notion
        page_info = upload_to_notion(md_text, title=report_data.get("report_title", label),
                                     date=date_from.strftime("%Y-%m-%d"),
                                     page_type="reporte", env_path=ENV_PATH)
        print(f"  Notion: {page_info['url']}")

    if args.email:
        from .email_report import send_report_email
        attachments = [out_pdf] if out_pdf else []
        subject = f"Reporte {tipo.capitalize()}: {label}"
        result = send_report_email(subject, md_text, attachments, env_path=ENV_PATH)
        print(f"  Email: {result}")


def cmd_stats(args):
    """Muestra metricas consolidadas."""
    from .report import load_all_meetings, filter_by_date_range, get_week_range, get_month_range
    from .stats import compute_stats, stats_to_text, compare_periods, comparison_to_text

    all_meetings = load_all_meetings(OUT_DIR)

    if args.fecha:
        ref = datetime.strptime(args.fecha, "%Y-%m-%d")
        tipo = args.tipo or "semanal"
        if tipo == "semanal":
            date_from, date_to = get_week_range(ref)
        else:
            date_from, date_to = get_month_range(ref)
        meetings = filter_by_date_range(all_meetings, date_from, date_to)
        period_label = f"{tipo}: {date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}"
        print(f"Stats ({period_label}):")
    else:
        meetings = all_meetings
        date_from = date_to = None
        tipo = args.tipo
        period_label = "todas las reuniones"
        print("Stats (todas las reuniones):")

    if not meetings:
        print("  Sin reuniones para el periodo.")
        return

    project = args.project or ""
    stats = compute_stats(meetings, project=project)
    print(stats_to_text(stats))

    # Comparativa entre periodos
    comparison = None
    if args.compare and date_from and date_to:
        tipo = tipo or "semanal"
        if tipo == "semanal":
            prev_from = date_from - timedelta(days=7)
            prev_to = date_from - timedelta(seconds=1)
        else:
            prev_to = date_from - timedelta(seconds=1)
            prev_from, _ = get_month_range(prev_to)
        prev_meetings = filter_by_date_range(all_meetings, prev_from, prev_to)
        if prev_meetings:
            comparison = compare_periods(meetings, prev_meetings, project=project)
            print(f"\n{comparison_to_text(comparison)}")
        else:
            print("\n  (Sin datos del periodo anterior para comparar)")

    # PDF de stats
    if args.pdf:
        from .pdf_export import stats_to_pdf
        REPORTS_DIR.mkdir(exist_ok=True)
        safe = period_label.replace(" ", "_").replace(":", "").replace("/", "-")
        if project:
            safe += f"_{project}"
        out_pdf = REPORTS_DIR / f"stats_{safe}.pdf"
        stats_to_pdf(stats, out_pdf, comparison=comparison)
        print(f"\n  PDF: {out_pdf}")


def cmd_search(args):
    """Busca en las reuniones procesadas."""
    from .report import load_all_meetings
    from .search import search_meetings, search_to_text

    all_meetings = load_all_meetings(OUT_DIR)
    results = search_meetings(all_meetings, args.query, scope=args.scope)
    print(search_to_text(results, args.query))


def cmd_tracking(args):
    """Muestra seguimiento de action items entre periodos."""
    from .report import load_all_meetings, filter_by_date_range, get_week_range, get_month_range
    from .action_tracking import track_actions, tracking_to_text
    from .stats import _filter_by_project

    all_meetings = load_all_meetings(OUT_DIR)
    ref = datetime.strptime(args.fecha, "%Y-%m-%d") if args.fecha else datetime.now()
    tipo = args.tipo or "semanal"

    if tipo == "semanal":
        date_from, date_to = get_week_range(ref)
        prev_from = date_from - timedelta(days=7)
        prev_to = date_from - timedelta(seconds=1)
    else:
        date_from, date_to = get_month_range(ref)
        prev_to = date_from - timedelta(seconds=1)
        prev_from, _ = get_month_range(prev_to)

    current = filter_by_date_range(all_meetings, date_from, date_to)
    prev = filter_by_date_range(all_meetings, prev_from, prev_to)

    # Filtro por proyecto
    if args.project:
        current = _filter_by_project(current, args.project)
        prev = _filter_by_project(prev, args.project)

    label = f"{tipo}: {date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}"
    if args.project:
        label += f" | Proyecto: {args.project}"
    print(f"Tracking ({label}):")

    if not current:
        print("  Sin reuniones en el periodo actual.")
        return

    tracking = track_actions(current, prev)
    print(tracking_to_text(tracking))


def cmd_notion(args):
    """Sube un archivo MD a Notion."""
    from .notion_sync import upload_to_notion

    md_path = Path(args.file)
    if not md_path.exists():
        print(f"Archivo no encontrado: {md_path}")
        sys.exit(1)

    md_text = md_path.read_text(encoding="utf-8")
    page_info = upload_to_notion(
        md_text, title=args.title,
        date=args.date, page_type=args.type,
        env_path=ENV_PATH,
    )
    print(f"Subido a Notion: {page_info['url']}")


def cmd_notion_pull(args):
    """Descarga cambios de Notion y actualiza JSONs locales."""
    from .notion_sync import sync_notion_to_local, load_manual_tasks

    print("Sincronizando tareas desde Notion...")
    result = sync_notion_to_local(
        OUT_DIR, env_path=ENV_PATH,
        solo_tareas=args.solo_tareas,
        solo_paginas=args.solo_paginas,
        refresh_tasks=args.refresh_tasks,
    )

    if result.get("pages_updated"):
        print(f"  Paginas sync:  {result['pages_updated']} (contenido + MD + JSON actualizados)")
    if result.get("new_tasks_added"):
        print(f"  Tareas nuevas: {result['new_tasks_added']} detectadas desde contenido editado (pendiente notion-tasks)")
    print(f"  Tareas sync:   {result['updated']}")
    if result.get("deleted"):
        print(f"  Eliminadas:    {result['deleted']} (marcadas notion_deleted en JSON local)")
    print(f"  Manuales:      {result['manual']}")
    if result["unmatched"]:
        print(f"  Sin match:     {result['unmatched']}")
    if result["files_modified"]:
        print(f"  Archivos mod:  {', '.join(result['files_modified'])}")

    manual = load_manual_tasks(OUT_DIR)
    if manual:
        print(f"\n  {len(manual)} tareas manuales disponibles para reportes.")
        if args.show_manual:
            for t in manual:
                status = t.get("status", "todo")
                print(f"    [{status}] {t.get('task', '?')[:60]}")

    print("\nSync completo. Regenera reportes para reflejar cambios:")
    print("  python -m meeting_assistant report --tipo semanal")


def cmd_notion_link(args):
    """Empareja paginas existentes en Notion con JSONs locales (guarda notion_meeting_page_id)."""
    from .notion_sync import link_notion_pages_to_local

    print("Enlazando paginas de Notion con JSONs locales...")
    result = link_notion_pages_to_local(OUT_DIR, env_path=ENV_PATH)

    print(f"  Enlazados:      {result['linked']}")
    print(f"  Ya enlazados:   {result['already_linked']}")
    if result["unmatched"]:
        print(f"  Sin match ({len(result['unmatched'])}): {', '.join(result['unmatched'])}")
        print("  (Esos archivos no tienen pagina en Notion aun. Usa notion-push para subirlos.)")
    else:
        print("  Todos los archivos enlazados correctamente.")
    print("\nAhora puedes usar notion-pull para sincronizar cambios.")


def cmd_notion_push(args):
    """Sube a Notion todos los MDs de outputs que aun no estan alli."""
    from .notion_sync import upload_pending_meetings

    print("Detectando minutas pendientes de subir a Notion...")
    result = upload_pending_meetings(OUT_DIR, env_path=ENV_PATH)

    print(f"\n  Subidas:  {result['uploaded']}")
    print(f"  Omitidas: {result['skipped']} (ya estaban en Notion)")
    if result["errors"]:
        print(f"  Errores:  {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    - {e}")


def cmd_notion_tasks(args):
    """Sube action items como entries en database de Notion."""
    from .report import load_all_meetings, filter_by_date_range, get_week_range, get_month_range
    from .notion_sync import upload_tasks_to_notion

    all_meetings = load_all_meetings(OUT_DIR)

    if args.fecha:
        ref = datetime.strptime(args.fecha, "%Y-%m-%d")
        tipo = args.tipo or "semanal"
        if tipo == "semanal":
            date_from, date_to = get_week_range(ref)
        else:
            date_from, date_to = get_month_range(ref)
        meetings = filter_by_date_range(all_meetings, date_from, date_to)
        label = f"{date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}"
    else:
        meetings = all_meetings
        label = "todas"

    if not meetings:
        print(f"Sin reuniones para el periodo ({label}).")
        sys.exit(0)

    # --reset: limpia notion_page_id y notion_deleted de los JSONs locales
    # Usar ANTES de re-subir todo tras haber borrado la BD en Notion
    if args.reset:
        reset_count = 0
        for json_path in sorted(OUT_DIR.glob("*_structured.json")):
            try:
                raw = json.loads(json_path.read_text(encoding="utf-8"))
                changed = False
                for ai in raw.get("action_items", []):
                    if "notion_page_id" in ai or "notion_deleted" in ai:
                        ai.pop("notion_page_id", None)
                        ai.pop("notion_deleted", None)
                        changed = True
                        reset_count += 1
                if changed:
                    json_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                continue
        print(f"  Reset: {reset_count} IDs limpiados de JSONs locales.")
        # Recargar meetings con los JSONs actualizados
        all_meetings = load_all_meetings(OUT_DIR)
        meetings = all_meetings if not args.fecha else filter_by_date_range(all_meetings, date_from, date_to)

    total_tasks = sum(len(m.get("action_items", [])) for m in meetings)
    print(f"Subiendo {total_tasks} tareas de {len(meetings)} reuniones ({label})...")

    result = upload_tasks_to_notion(
        meetings, env_path=ENV_PATH,
        update_existing=not args.no_update,
        out_dir=OUT_DIR,
    )

    print(f"  Creadas:      {result['created']}")
    print(f"  Actualizadas: {result['updated']}")
    if result.get("skipped"):
        print(f"  Omitidas:     {result['skipped']}")
    if result["errors"]:
        print(f"  Errores:      {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")


def cmd_template(args):
    """Genera template/agenda para la siguiente reunion."""
    from .report import load_all_meetings, filter_by_date_range, get_week_range, get_month_range
    from .meeting_template import generate_template
    from .stats import _filter_by_project

    all_meetings = load_all_meetings(OUT_DIR)

    # Usar reuniones recientes (ultima semana por defecto)
    ref = datetime.strptime(args.fecha, "%Y-%m-%d") if args.fecha else datetime.now()
    date_from, date_to = get_week_range(ref)
    meetings = filter_by_date_range(all_meetings, date_from, date_to)

    # Si no hay de esta semana, usar todas
    if not meetings:
        meetings = all_meetings

    # Filtro por proyecto
    if args.project:
        meetings = _filter_by_project(meetings, args.project)

    meeting_type = args.tipo
    if args.project and meeting_type == "daily":
        meeting_type = args.project  # Usar nombre de proyecto como tipo

    template = generate_template(meetings, meeting_type=meeting_type, ref_date=ref)

    # Guardar o imprimir
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(template, encoding="utf-8")
        print(f"Template guardado: {out_path}")
    else:
        print(template)


def cmd_email(args):
    """Envia un reporte por correo electronico."""
    from .email_report import send_report_email

    md_path = Path(args.file)
    if not md_path.exists():
        print(f"Archivo no encontrado: {md_path}")
        sys.exit(1)

    md_text = md_path.read_text(encoding="utf-8")
    subject = args.subject or f"Meeting Assistant — {md_path.stem}"

    attachments = []
    if args.attach:
        for a in args.attach:
            p = Path(a)
            if p.exists():
                attachments.append(p)
            else:
                print(f"  Adjunto no encontrado: {a}")

    result = send_report_email(subject, md_text, attachments, env_path=ENV_PATH)
    print(result)


FLOWS_TEXT = """
===============================================================
  MEETING ASSISTANT -- FLUJOS DE TRABAJO
===============================================================

-- FLUJO DIARIO (despues de cada reunion) ---------------------
  1. Coloca el .docx en transcriptions/
  2. process           Genera JSON + MD en outputs/
  3. notion-push       Sube MDs nuevos a Notion (auto-detecta pendientes)
  4. [Edita en Notion] Corrige titulo, resumen, temas, decisiones
  5. notion-pull --solo-paginas
                       Baja cambios de Notion, actualiza MD + JSON local
     OPCION: --refresh-tasks  Si editaste temas/decisiones y pueden haber
                              surgido tareas nuevas, las detecta con IA
                              (1 request Gemini por pagina modificada)
  6. notion-tasks      Sube tareas a la Tasks DB de Notion
                       (incluye las nuevas detectadas por --refresh-tasks)
  7. [Edita Tasks DB]  Cambia estado, owner, prioridad en Notion
  8. notion-pull --solo-tareas
                       Sincroniza cambios de Tasks DB al JSON local

  Comandos rapidos (sin refresh-tasks):
    python -m meeting_assistant process
    python -m meeting_assistant notion-push
    python -m meeting_assistant notion-pull --solo-paginas
    python -m meeting_assistant notion-tasks
    python -m meeting_assistant notion-pull --solo-tareas

  Con deteccion de tareas nuevas (paso 5):
    python -m meeting_assistant notion-pull --solo-paginas --refresh-tasks

-- FLUJO DE REPORTE SEMANAL (viernes) -------------------------
  1. notion-pull       Asegura que todos los datos esten al dia
  2. stats             Dashboard de KPIs + comparativa semana anterior
  3. tracking          Ver estado de tareas pendientes vs semana anterior
  4. report            Genera reporte ejecutivo MD + PDF (+ Notion + email)

  El reporte incluye automaticamente (sin consumir requests Gemini):
  - Estado por Proyecto: tabla con total/hecho/en-curso/bloqueado/pendiente
  - Tareas Bloqueadas: lista con owner y proyecto (para escalar)
  - Alertas de Vencimiento: top 10 tareas vencidas o estancadas

  Comandos:
    python -m meeting_assistant notion-pull
    python -m meeting_assistant stats --fecha 2026-03-06 --tipo semanal --compare --pdf
    python -m meeting_assistant tracking --fecha 2026-03-06
    python -m meeting_assistant report --tipo semanal --fecha 2026-03-06 --pdf --notion --email

-- FLUJO DE REPORTE MENSUAL (fin de mes) ----------------------
  Comandos:
    python -m meeting_assistant notion-pull
    python -m meeting_assistant stats --fecha 2026-03-31 --tipo mensual --compare --pdf
    python -m meeting_assistant report --tipo mensual --fecha 2026-03-31 --pdf --email

-- FLUJO POR PROYECTO -----------------------------------------
  Stats y tracking filtrados por proyecto especifico:

    python -m meeting_assistant stats --project Chinalco --compare --pdf
    python -m meeting_assistant tracking --project Chinalco
    python -m meeting_assistant template --tipo daily --project Chinalco

  Proyectos: Chinalco, MMM, HH4M, FMS, CODEa General, English for Miners
             (keywords parciales funcionan: "china", "hh4", "fms", etc.)

-- FLUJO DE BUSQUEDA ------------------------------------------
    python -m meeting_assistant search "Chinalco"
    python -m meeting_assistant search "presupuesto" --scope decisions
    python -m meeting_assistant search "Juan"         --scope speakers
    python -m meeting_assistant search "API"          --scope tasks

  Scopes: all | decisions | tasks | topics | speakers

-- FLUJO DE AGENDA / TEMPLATE ---------------------------------
    python -m meeting_assistant template --tipo daily
    python -m meeting_assistant template --tipo semanal --project Chinalco -o agenda.md

-- FLUJO DE EMAIL ---------------------------------------------
  (Requiere SMTP configurado en .env: SMTP_USER, SMTP_PASSWORD)

    python -m meeting_assistant email --file reports/reporte_semanal_X.md
    python -m meeting_assistant email --file reports/reporte_semanal_X.md \
        --attach reports/reporte_semanal_X.pdf --subject "Reporte Semana 10"

-- NOTION -- REFERENCIA RAPIDA --------------------------------
  notion-link                 Enlaza JSONs locales con paginas ya existentes en Notion (fuzzy)
  notion-push                 Sube MDs nuevos de outputs/ (auto-detecta)
  notion-pull                 Sync completo: paginas + Tasks DB
  notion-pull --solo-paginas           Solo contenido de reuniones (no tareas)
  notion-pull --solo-tareas            Solo Tasks DB (no contenido de paginas)
  notion-pull --refresh-tasks          Detecta tareas nuevas en contenido editado (IA)
  notion-pull --solo-paginas --refresh-tasks  Combo recomendado post-edicion
  notion-pull --show-manual            Muestra tareas manuales de Notion sin match
  notion-tasks                Sube/actualiza tareas en Tasks DB
  notion-tasks --no-update    Solo crea nuevas, no actualiza existentes
  notion --file X.md --title "T" --type minuta
                              Sube un MD especifico a Notion (manual)

===============================================================
  Ayuda de un comando: python -m meeting_assistant <comando> --help
===============================================================
"""


def cmd_flows(_args):
    """Muestra todos los flujos de trabajo disponibles."""
    print(FLOWS_TEXT)


def main():
    parser = argparse.ArgumentParser(
        prog="meeting_assistant",
        description="Meeting Assistant AI — CLI",
        epilog=(
            "Flujos rapidos:\n"
            "  Diario:  process > notion-push > notion-pull --solo-paginas > notion-tasks > notion-pull --solo-tareas\n"
            "  Semanal: notion-pull > stats > tracking > report  (los viernes)\n"
            "  Mensual: notion-pull > stats --tipo mensual > report --tipo mensual\n"
            "\n"
            "Ver flujos detallados con ejemplos: python -m meeting_assistant flows"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # process
    p_proc = sub.add_parser("process", help="Procesar transcripciones pendientes")
    p_proc.add_argument("--context", "-c", default="", help="Contexto de la reunion (opcional)")

    # report
    p_rep = sub.add_parser("report", help="Generar reporte ejecutivo")
    p_rep.add_argument("--tipo", "-t", default="semanal", choices=["semanal", "mensual"])
    p_rep.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_rep.add_argument("--pdf", action="store_true", help="Tambien generar PDF")
    p_rep.add_argument("--notion", action="store_true", help="Subir a Notion")
    p_rep.add_argument("--email", action="store_true", help="Enviar por correo")

    # stats
    p_stats = sub.add_parser("stats", help="Dashboard de metricas")
    p_stats.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_stats.add_argument("--tipo", "-t", default=None, choices=["semanal", "mensual"])
    p_stats.add_argument("--project", "-p", default=None, help="Filtrar por proyecto")
    p_stats.add_argument("--pdf", action="store_true", help="Exportar stats a PDF")
    p_stats.add_argument("--compare", action="store_true", help="Comparar con periodo anterior")

    # search
    p_search = sub.add_parser("search", help="Buscar en reuniones")
    p_search.add_argument("query", help="Texto a buscar")
    p_search.add_argument("--scope", "-s", default="all",
                          choices=["all", "decisions", "tasks", "topics", "speakers"])

    # tracking
    p_track = sub.add_parser("tracking", help="Seguimiento de action items")
    p_track.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_track.add_argument("--tipo", "-t", default="semanal", choices=["semanal", "mensual"])
    p_track.add_argument("--project", "-p", default=None, help="Filtrar por proyecto")

    # notion
    p_notion = sub.add_parser("notion", help="Subir archivo MD a Notion")
    p_notion.add_argument("--file", required=True, help="Ruta al archivo .md")
    p_notion.add_argument("--title", required=True, help="Titulo de la pagina")
    p_notion.add_argument("--date", default=None, help="Fecha YYYY-MM-DD")
    p_notion.add_argument("--type", default="minuta", choices=["minuta", "reporte"])

    # notion-link
    sub.add_parser("notion-link", help="Enlazar JSONs locales con sus paginas existentes en Notion")

    # notion-push
    sub.add_parser("notion-push", help="Subir a Notion todos los MDs pendientes de outputs/")

    # notion-pull
    p_npull = sub.add_parser("notion-pull", help="Descargar cambios de Notion a JSONs locales")
    p_npull.add_argument("--show-manual", action="store_true",
                         help="Mostrar lista de tareas manuales")
    p_npull.add_argument("--solo-tareas", action="store_true",
                         help="Solo sincroniza Tasks DB (omite contenido de pages)")
    p_npull.add_argument("--solo-paginas", action="store_true",
                         help="Solo sincroniza contenido de meeting pages (omite Tasks DB)")
    p_npull.add_argument("--refresh-tasks", action="store_true",
                         help="Detecta tareas nuevas en el contenido editado (usa 1 request Gemini por pagina)")

    # notion-tasks
    p_ntasks = sub.add_parser("notion-tasks", help="Subir action items a database de Notion")
    p_ntasks.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_ntasks.add_argument("--tipo", "-t", default=None, choices=["semanal", "mensual"])
    p_ntasks.add_argument("--no-update", action="store_true",
                          help="No actualizar tareas existentes (solo crear nuevas)")
    p_ntasks.add_argument("--reset", action="store_true",
                          help="Limpia notion_page_id locales y re-sube todo como nuevo (usar tras borrar la BD en Notion)")

    # template
    p_tmpl = sub.add_parser("template", help="Generar agenda/template para reunion")
    p_tmpl.add_argument("--tipo", "-t", default="daily", choices=["daily", "semanal"],
                        help="Tipo de reunion")
    p_tmpl.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_tmpl.add_argument("--project", "-p", default=None, help="Filtrar por proyecto")
    p_tmpl.add_argument("--output", "-o", default=None, help="Guardar en archivo (default: stdout)")

    # email
    p_email = sub.add_parser("email", help="Enviar reporte por correo")
    p_email.add_argument("--file", required=True, help="Archivo .md a enviar")
    p_email.add_argument("--subject", "-s", default=None, help="Asunto del correo")
    p_email.add_argument("--attach", "-a", nargs="*", help="Archivos adjuntos (PDFs, etc.)")

    # flows
    sub.add_parser("flows", help="Ver flujos de trabajo detallados con ejemplos")

    args = parser.parse_args()

    commands = {
        "process": cmd_process,
        "report": cmd_report,
        "stats": cmd_stats,
        "search": cmd_search,
        "tracking": cmd_tracking,
        "notion": cmd_notion,
        "notion-link": cmd_notion_link,
        "notion-push": cmd_notion_push,
        "notion-pull": cmd_notion_pull,
        "notion-tasks": cmd_notion_tasks,
        "template": cmd_template,
        "email": cmd_email,
        "flows": cmd_flows,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

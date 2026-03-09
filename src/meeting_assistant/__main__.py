"""
CLI para Meeting Assistant.

Uso:
  python -m meeting_assistant process [--context "..."]
  python -m meeting_assistant report --tipo semanal [--fecha 2026-03-04] [--pdf]
  python -m meeting_assistant stats [--fecha 2026-03-04] [--tipo semanal]
  python -m meeting_assistant search "Chinalco" [--scope decisions]
  python -m meeting_assistant tracking [--fecha 2026-03-04] [--tipo semanal]
  python -m meeting_assistant notion --file outputs/260304_daily-team.md --title "Daily" --type minuta
  python -m meeting_assistant notion-pull [--show-manual]
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

    safe_label = label.replace(" ", "_").replace("/", "-")
    out_json = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.json"
    out_md = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.md"

    out_json.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(report_to_markdown(report_data), encoding="utf-8")
    print(f"  JSON: {out_json}")
    print(f"  MD:   {out_md}")

    if args.pdf:
        from .pdf_export import report_to_pdf
        out_pdf = REPORTS_DIR / f"reporte_{tipo}_{safe_label}.pdf"
        report_to_pdf(report_data, out_pdf)
        print(f"  PDF:  {out_pdf}")

    if args.notion:
        from .notion_sync import upload_to_notion
        md_text = report_to_markdown(report_data)
        url = upload_to_notion(md_text, title=report_data.get("report_title", label),
                               date=date_from.strftime("%Y-%m-%d"),
                               page_type="reporte", env_path=ENV_PATH)
        print(f"  Notion: {url}")


def cmd_stats(args):
    """Muestra metricas consolidadas."""
    from .report import load_all_meetings, filter_by_date_range, get_week_range, get_month_range
    from .stats import compute_stats, stats_to_text

    all_meetings = load_all_meetings(OUT_DIR)

    if args.fecha:
        ref = datetime.strptime(args.fecha, "%Y-%m-%d")
        tipo = args.tipo or "semanal"
        if tipo == "semanal":
            date_from, date_to = get_week_range(ref)
        else:
            date_from, date_to = get_month_range(ref)
        meetings = filter_by_date_range(all_meetings, date_from, date_to)
        print(f"Stats ({tipo}: {date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}):")
    else:
        meetings = all_meetings
        print("Stats (todas las reuniones):")

    if not meetings:
        print("  Sin reuniones para el periodo.")
        return

    stats = compute_stats(meetings)
    print(stats_to_text(stats))


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

    print(f"Tracking ({tipo}: {date_from.strftime('%Y-%m-%d')} a {date_to.strftime('%Y-%m-%d')}):")

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
    url = upload_to_notion(
        md_text, title=args.title,
        date=args.date, page_type=args.type,
        env_path=ENV_PATH,
    )
    print(f"Subido a Notion: {url}")


def cmd_notion_pull(args):
    """Descarga cambios de Notion y actualiza JSONs locales."""
    from .notion_sync import sync_notion_to_local, load_manual_tasks

    print("Sincronizando tareas desde Notion...")
    result = sync_notion_to_local(OUT_DIR, env_path=ENV_PATH)

    print(f"  Actualizadas:  {result['updated']}")
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

    total_tasks = sum(len(m.get("action_items", [])) for m in meetings)
    print(f"Subiendo {total_tasks} tareas de {len(meetings)} reuniones ({label})...")

    result = upload_tasks_to_notion(
        meetings, env_path=ENV_PATH,
        update_existing=not args.no_update,
    )

    print(f"  Creadas:      {result['created']}")
    print(f"  Actualizadas: {result['updated']}")
    if result.get("skipped"):
        print(f"  Omitidas:     {result['skipped']}")
    if result["errors"]:
        print(f"  Errores:      {len(result['errors'])}")
        for e in result["errors"][:5]:
            print(f"    - {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="meeting_assistant",
        description="Meeting Assistant AI — CLI",
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

    # stats
    p_stats = sub.add_parser("stats", help="Dashboard de metricas")
    p_stats.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_stats.add_argument("--tipo", "-t", default=None, choices=["semanal", "mensual"])

    # search
    p_search = sub.add_parser("search", help="Buscar en reuniones")
    p_search.add_argument("query", help="Texto a buscar")
    p_search.add_argument("--scope", "-s", default="all",
                          choices=["all", "decisions", "tasks", "topics", "speakers"])

    # tracking
    p_track = sub.add_parser("tracking", help="Seguimiento de action items")
    p_track.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_track.add_argument("--tipo", "-t", default="semanal", choices=["semanal", "mensual"])

    # notion
    p_notion = sub.add_parser("notion", help="Subir archivo MD a Notion")
    p_notion.add_argument("--file", required=True, help="Ruta al archivo .md")
    p_notion.add_argument("--title", required=True, help="Titulo de la pagina")
    p_notion.add_argument("--date", default=None, help="Fecha YYYY-MM-DD")
    p_notion.add_argument("--type", default="minuta", choices=["minuta", "reporte"])

    # notion-pull
    p_npull = sub.add_parser("notion-pull", help="Descargar cambios de Notion a JSONs locales")
    p_npull.add_argument("--show-manual", action="store_true",
                         help="Mostrar lista de tareas manuales")

    # notion-tasks
    p_ntasks = sub.add_parser("notion-tasks", help="Subir action items a database de Notion")
    p_ntasks.add_argument("--fecha", "-f", default=None, help="Fecha referencia YYYY-MM-DD")
    p_ntasks.add_argument("--tipo", "-t", default=None, choices=["semanal", "mensual"])
    p_ntasks.add_argument("--no-update", action="store_true",
                          help="No actualizar tareas existentes (solo crear nuevas)")

    args = parser.parse_args()

    commands = {
        "process": cmd_process,
        "report": cmd_report,
        "stats": cmd_stats,
        "search": cmd_search,
        "tracking": cmd_tracking,
        "notion": cmd_notion,
        "notion-pull": cmd_notion_pull,
        "notion-tasks": cmd_notion_tasks,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()

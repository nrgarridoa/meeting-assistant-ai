"""
Busqueda sobre reuniones procesadas — sin LLM, puro filtro local.
"""

import re
from pathlib import Path


def search_meetings(
    meetings: list[dict],
    query: str,
    *,
    scope: str = "all",
) -> list[dict]:
    """
    Busca en las reuniones procesadas.

    Args:
        meetings: Lista de JSONs estructurados (con _source_file y _date).
        query: Texto a buscar (case-insensitive).
        scope: Donde buscar — "all", "decisions", "tasks", "topics", "speakers".

    Returns:
        Lista de resultados con {source, date, section, match}.
    """
    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for m in meetings:
        source = m.get("_source_file", "?")
        date = m["_date"].strftime("%Y-%m-%d") if m.get("_date") else "?"
        title = m.get("meeting_title", "?")

        if scope in ("all", "topics"):
            for t in m.get("topics", []):
                topic_name = t.get("name", "")
                if pattern.search(topic_name):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "topic", "match": topic_name,
                    })
                for b in t.get("bullets", []):
                    if pattern.search(b):
                        results.append({
                            "source": source, "date": date, "title": title,
                            "section": f"topic/{topic_name}", "match": b,
                        })

        if scope in ("all", "decisions"):
            for d in m.get("decisions", []):
                text = d.get("decision", "")
                if pattern.search(text):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "decision", "match": text,
                        "owner": d.get("owner"),
                    })

        if scope in ("all", "tasks"):
            for a in m.get("action_items", []):
                text = a.get("task", "")
                if pattern.search(text):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "task",
                        "match": text,
                        "owner": a.get("owner"),
                        "status": a.get("status"),
                        "priority": a.get("priority"),
                    })

        if scope in ("all", "speakers"):
            for s in m.get("speakers", []):
                name = s.get("name", "")
                if pattern.search(name):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "speaker", "match": name,
                    })

        if scope == "all":
            for b in m.get("summary_top_bullets", []):
                if pattern.search(b):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "summary", "match": b,
                    })
            for r in m.get("risks_blockers", []):
                if pattern.search(r):
                    results.append({
                        "source": source, "date": date, "title": title,
                        "section": "risk", "match": r,
                    })

    return results


def search_to_text(results: list[dict], query: str) -> str:
    """Formatea resultados de busqueda como texto."""
    if not results:
        return f'  Sin resultados para "{query}"'

    lines = [f'  {len(results)} resultados para "{query}":\n']
    for r in results:
        prefix = f"  [{r['date']}] [{r['section']}]"
        lines.append(f"{prefix} {r['match']}")
        extras = []
        if r.get("owner"):
            extras.append(f"owner: {r['owner']}")
        if r.get("status"):
            extras.append(f"status: {r['status']}")
        if extras:
            lines.append(f"    ({', '.join(extras)})")

    return "\n".join(lines)

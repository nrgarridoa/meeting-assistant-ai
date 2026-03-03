import re

# ─────────────────────────────────────────────
# Palabras y frases que consumen tokens sin aportar información
# ─────────────────────────────────────────────

_FILLER_WORDS = {
    "mmm", "mm", "mhm", "eh", "ah", "ajá", "aja",
    "sí", "si", "ya", "ok", "okay", "bueno", "este",
    "o sea", "osea", "pucha", "claro",
}

_META_PHRASES = [
    r"¿\s*me\s+escuchas?\s*\?",
    r"¿\s*se\s+escucha\s*\?",
    r"¿\s*me\s+ven\s*\?",
    r"¿\s*hay\s+sonido\s*\?",
    r"voy\s+a\s+compartir\s+(?:la\s+)?pantalla",
    r"ya\s+comparto\s+(?:la\s+)?pantalla",
    r"estoy\s+compartiendo",
    r"¿\s*pueden\s+ver\s*\?",
    r"¿\s*se\s+ve\s*\?",
]
_META_RE = re.compile(
    r"(?i)(" + "|".join(_META_PHRASES) + r")",
)


def remove_timestamps(text: str) -> str:
    """Quita timestamps standalone (línea entera) y al inicio de línea."""
    # Línea completa que es solo timestamp: "0:03" o "1:23:45"
    text = re.sub(r"(?m)^\s*\d{1,2}:\d{2}(?::\d{2})?\s*$", "", text)
    # Timestamp al inicio de línea seguido de texto: "0:03 Hola..."
    text = re.sub(r"(?m)^\s*\d{1,2}:\d{2}(?::\d{2})?\s+", "", text)
    return text


def remove_filler_lines(text: str) -> str:
    """
    Elimina líneas que son SOLO fillers o frases meta (no aportan contenido).
    Ejemplos: "mmm", "ok ok", "sí, sí", "¿me escuchas?"
    """
    result = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        # Normalizar: minúsculas, quitar puntuación para comparar
        normalized = re.sub(r"[,\.;:\?¿!¡]", "", stripped.lower()).strip()
        # Separar tokens
        tokens = [t.strip() for t in re.split(r"[\s,]+", normalized) if t.strip()]

        if not tokens:
            result.append("")
            continue

        # Si todos los tokens son fillers, descartar la línea
        if all(t in _FILLER_WORDS for t in tokens):
            continue

        # Si la línea es solo una frase meta, descartar
        if _META_RE.search(stripped):
            # Solo descartar si la línea es predominantemente meta (< 8 palabras)
            if len(tokens) < 8:
                continue

        result.append(line)
    return "\n".join(result)


def collapse_repeated_words(text: str) -> str:
    """
    Colapsa repeticiones consecutivas del mismo token.
    "sí, sí, sí" → "sí"   |   "mmm mmm mmm" → "mmm"
    """
    # Repeticiones de palabras separadas por coma/espacio
    text = re.sub(r"(?i)\b(\w+)\b(?:[,\s]+\1\b){2,}", r"\1", text)
    return text


def merge_short_lines(text: str) -> str:
    """
    Fusiona líneas muy cortas (< 4 palabras) con la línea anterior,
    ya que suelen ser fragmentos sueltos del transcriptor automático.
    No fusiona si la línea anterior termina en punto o si es la primera línea.
    """
    lines = text.splitlines()
    if not lines:
        return text

    result = [lines[0]]
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            result.append("")
            continue

        word_count = len(stripped.split())
        prev = result[-1].rstrip() if result else ""

        if word_count < 4 and prev and not prev.endswith((".", "!", "?")):
            result[-1] = prev + " " + stripped
        else:
            result.append(line)
    return "\n".join(result)


def normalize_spaces(text: str) -> str:
    """Normaliza saltos de línea y espacios múltiples."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def preprocess_transcript(text: str, verbose: bool = False) -> str:
    """
    Pipeline completo de preprocesamiento.
    Objetivo: reducir ruido 30-40% antes de enviar a la API.

    Pasos:
    1. Eliminar timestamps
    2. Eliminar líneas de solo fillers/frases meta
    3. Colapsar repeticiones consecutivas
    4. Fusionar líneas muy cortas con la anterior
    5. Normalizar espacios

    Args:
        text: Transcripción cruda.
        verbose: Si True, imprime estadísticas de reducción.
    """
    original_len = len(text)

    text = remove_timestamps(text)
    text = remove_filler_lines(text)
    text = collapse_repeated_words(text)
    text = merge_short_lines(text)
    text = normalize_spaces(text)

    if verbose:
        final_len = len(text)
        reduction = (1 - final_len / original_len) * 100 if original_len else 0
        print(f"  Preprocesamiento: {original_len:,} → {final_len:,} chars  ({reduction:.1f}% reducción)")

    return text

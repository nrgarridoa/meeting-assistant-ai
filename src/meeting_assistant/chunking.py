from typing import List


def chunk_text_smart(
    text: str,
    max_chars: int = 30000,
    overlap_chars: int = 200,
) -> List[str]:
    """
    Divide el texto en chunks respetando límites naturales.

    Estrategia:
    1. Divide en párrafos (líneas en blanco).
    2. Acumula párrafos en un chunk hasta llegar a max_chars.
    3. Si un párrafo individual supera max_chars, lo divide por oraciones.
    4. Agrega overlap: copia los últimos overlap_chars del chunk anterior
       al inicio del siguiente para no perder contexto entre bloques.

    Args:
        text: Texto preprocesado.
        max_chars: Tamaño máximo por chunk (recomendado: 30000).
        overlap_chars: Chars de contexto compartido entre chunks.

    Returns:
        Lista de strings. Si el texto cabe en un solo chunk, retorna [text].
    """
    text = text.strip()
    if len(text) <= max_chars:
        return [text]

    # Dividir en párrafos (uno o más saltos de línea)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: List[str] = []
    current_parts: List[str] = []
    current_len = 0

    def flush(parts: List[str]) -> str:
        return "\n\n".join(parts)

    for para in paragraphs:
        # Si el párrafo por sí solo supera max_chars, dividir por oraciones
        if len(para) > max_chars:
            sentences = _split_sentences(para)
            for sent in sentences:
                if current_len + len(sent) + 2 > max_chars and current_parts:
                    chunk_text = flush(current_parts)
                    chunks.append(chunk_text)
                    # Overlap: últimos overlap_chars del chunk actual
                    overlap = chunk_text[-overlap_chars:] if overlap_chars else ""
                    current_parts = [overlap, sent] if overlap else [sent]
                    current_len = len(overlap) + len(sent)
                else:
                    current_parts.append(sent)
                    current_len += len(sent) + 2
        else:
            if current_len + len(para) + 2 > max_chars and current_parts:
                chunk_text = flush(current_parts)
                chunks.append(chunk_text)
                overlap = chunk_text[-overlap_chars:] if overlap_chars else ""
                current_parts = [overlap, para] if overlap else [para]
                current_len = len(overlap) + len(para)
            else:
                current_parts.append(para)
                current_len += len(para) + 2

    if current_parts:
        chunks.append(flush(current_parts))

    return chunks if chunks else [text]


def _split_sentences(text: str) -> List[str]:
    """Divide un texto en oraciones por '. ', '! ', '? '."""
    import re
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]

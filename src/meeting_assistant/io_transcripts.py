from pathlib import Path
from docx import Document

SUPPORTED = {".txt", ".docx"}

def read_docx(path: Path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())

def load_transcript(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".txt":
        return path.read_text(encoding="utf-8", errors="ignore")
    if ext == ".docx":
        return read_docx(path)
    raise ValueError(f"Formato no soportado: {ext}")

def list_transcripts(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED]
"""
Envio de reportes por correo electronico via SMTP.

Soporta Gmail (gratuito con App Password) y Outlook/Hotmail.

Configuracion en .env:
    SMTP_HOST=smtp.gmail.com        # o smtp.office365.com
    SMTP_PORT=587
    SMTP_USER=tucorreo@gmail.com
    SMTP_PASSWORD=xxxx xxxx xxxx xxxx   # App Password de Google (no la password normal)
    SMTP_TO=destinatario@empresa.com    # separar multiples con coma

Para Gmail:
    1. Activar 2FA en https://myaccount.google.com/security
    2. Crear App Password en https://myaccount.google.com/apppasswords
    3. Usar esa password de 16 chars en SMTP_PASSWORD
"""

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from dotenv import load_dotenv


def _get_smtp_config(env_path: str = ".env") -> dict:
    """Lee configuracion SMTP del .env."""
    load_dotenv(env_path)
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    to_addrs = os.getenv("SMTP_TO", "")

    if not user or not password:
        raise ValueError(
            "SMTP_USER y SMTP_PASSWORD no encontrados en .env.\n"
            "Para Gmail: crea un App Password en https://myaccount.google.com/apppasswords"
        )
    if not to_addrs:
        raise ValueError("SMTP_TO no encontrado en .env (destinatario del reporte).")

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "to": [addr.strip() for addr in to_addrs.split(",") if addr.strip()],
    }


def send_report_email(
    subject: str,
    body_md: str,
    attachments: list[Path] | None = None,
    env_path: str = ".env",
) -> str:
    """
    Envia un reporte por correo electronico.

    Args:
        subject: Asunto del correo.
        body_md: Contenido en Markdown (se envia como texto plano).
        attachments: Lista de archivos a adjuntar (PDFs, etc.).
        env_path: Ruta al .env.

    Returns:
        Mensaje de confirmacion.
    """
    config = _get_smtp_config(env_path)

    msg = MIMEMultipart()
    msg["From"] = config["user"]
    msg["To"] = ", ".join(config["to"])
    msg["Subject"] = subject

    # Convertir MD basico a HTML simple para mejor legibilidad
    html_body = _md_to_simple_html(body_md)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # Adjuntar archivos
    if attachments:
        for file_path in attachments:
            file_path = Path(file_path)
            if not file_path.exists():
                continue
            part = MIMEBase("application", "octet-stream")
            part.set_payload(file_path.read_bytes())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={file_path.name}",
            )
            msg.attach(part)

    # Enviar
    with smtplib.SMTP(config["host"], config["port"], timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config["user"], config["password"])
        server.sendmail(config["user"], config["to"], msg.as_string())

    to_str = ", ".join(config["to"])
    return f"Correo enviado a {to_str}"


def _md_to_simple_html(md_text: str) -> str:
    """Convierte Markdown basico a HTML para email."""
    import re

    lines = md_text.split("\n")
    html_lines = []
    html_lines.append("<div style='font-family: Calibri, Arial, sans-serif; font-size: 14px; color: #333;'>")

    for line in lines:
        stripped = line.strip()

        if stripped.startswith("### "):
            html_lines.append(f"<h3 style='color:#1a1a64;margin:16px 0 4px;'>{stripped[4:]}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2 style='color:#1a1a64;margin:20px 0 6px;'>{stripped[3:]}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1 style='color:#1a1a64;margin:0 0 8px;'>{stripped[2:]}</h1>")
        elif stripped.startswith("---"):
            html_lines.append("<hr style='border:none;border-top:1px solid #ddd;margin:12px 0;'>")
        elif stripped.startswith("- "):
            content = stripped[2:]
            # Bold
            content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", content)
            html_lines.append(f"<div style='margin:2px 0 2px 20px;'>&#8226; {content}</div>")
        elif stripped.startswith("|"):
            # Skip table formatting for email — just show as text
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(c.replace("-", "").strip() == "" for c in cells):
                row = " | ".join(cells)
                html_lines.append(f"<div style='font-family:monospace;font-size:12px;margin:1px 0;'>{row}</div>")
        elif not stripped:
            html_lines.append("<br>")
        else:
            content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", stripped)
            html_lines.append(f"<p style='margin:4px 0;'>{content}</p>")

    html_lines.append("</div>")
    return "\n".join(html_lines)

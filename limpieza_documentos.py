"""
limpieza_documentos.py — Eliminación de archivos huérfanos en static/documentos/.

Los pacientes suben orden médica y autorización (fotos o PDFs) que se guardan
en `static/documentos/`. Cada intento genera un archivo; muchos quedan
huérfanos (sin cita asociada) o pertenecen a citas ya cerradas
(canceladas/completadas/inasistidas) y ocupan disco sin aportar valor.

Este módulo hace la limpieza con dos reglas simples:

  · SE CONSERVAN los archivos referenciados por citas en estado:
        'pendiente'  (esperando confirmación del hospital — REQUISITO)
        'agendada'   (cita futura ya confirmada)
  · SE ELIMINAN el resto:
        · huérfanos (nombre no referenciado por ninguna cita)
        · referenciados por citas 'cancelada', 'completada', 'inasistida'

El módulo expone:
  · `limpiar_documentos(session)` → dict con reporte
  · `estado_documentos(session)`  → dict con estadísticas (sin borrar nada)
"""
from __future__ import annotations
import os
from datetime import datetime
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

# Carpeta física donde viven los archivos. Los campos `doc_orden` y
# `doc_autorizacion` de `citas` guardan la ruta relativa "documentos/xxxxx".
_DIR_DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "static", "documentos")

# Extensiones que consideramos "documentos" (todo lo demás — .gitkeep, README,
# etc. — se ignora y no se toca).
_EXT_DOC = (".jpg", ".jpeg", ".png", ".pdf", ".webp")


def _iter_archivos_docs() -> Iterable[str]:
    """Nombres de archivo (sin ruta) en la carpeta de documentos."""
    if not os.path.isdir(_DIR_DOCS):
        return
    for nombre in os.listdir(_DIR_DOCS):
        if nombre.lower().endswith(_EXT_DOC):
            yield nombre


def _referenciados_activos(db: Session) -> set[str]:
    """
    Nombres de archivo (basename) referenciados por citas en estado 'pendiente'
    o 'agendada'. Estos NUNCA se eliminan.
    """
    filas = db.execute(text("""
        SELECT doc_orden, doc_autorizacion
        FROM citas
        WHERE estado IN ('pendiente', 'agendada')
    """)).all()
    referenciados: set[str] = set()
    for r in filas:
        for ruta in (r.doc_orden, r.doc_autorizacion):
            if ruta:
                referenciados.add(os.path.basename(ruta))
    return referenciados


def estado_documentos(db: Session) -> dict:
    """
    Estadísticas SIN borrar nada — útil para mostrar en el panel antes de
    que el personal decida ejecutar la limpieza.
    """
    archivos = list(_iter_archivos_docs())
    proteg  = _referenciados_activos(db)
    total = len(archivos)
    protegidos = sum(1 for n in archivos if n in proteg)
    huerfanos = total - protegidos

    bytes_total = 0
    bytes_borrable = 0
    for n in archivos:
        try:
            size = os.path.getsize(os.path.join(_DIR_DOCS, n))
        except OSError:
            continue
        bytes_total += size
        if n not in proteg:
            bytes_borrable += size

    return {
        "total": total,
        "protegidos": protegidos,        # de citas pendientes/agendadas
        "borrable": huerfanos,           # se borrarían si limpiamos ahora
        "bytes_total": bytes_total,
        "bytes_borrable": bytes_borrable,
    }


def limpiar_documentos(db: Session) -> dict:
    """
    Elimina los archivos que NO están referenciados por citas activas
    (pendiente/agendada). Retorna reporte con conteo y bytes liberados.

    Actualiza `configuracion.limpieza_docs_ultima` con la fecha/hora ISO
    para que el panel muestre cuándo se hizo la última limpieza.
    """
    proteg = _referenciados_activos(db)
    borrados = 0
    bytes_liberados = 0
    errores: list[str] = []

    for nombre in _iter_archivos_docs():
        if nombre in proteg:
            continue
        ruta = os.path.join(_DIR_DOCS, nombre)
        try:
            size = os.path.getsize(ruta)
            os.remove(ruta)
            borrados += 1
            bytes_liberados += size
        except OSError as e:
            errores.append(f"{nombre}: {e}")

    # Registrar la ejecución en configuracion
    ahora_iso = datetime.now().isoformat(timespec="seconds")
    db.execute(text("""
        INSERT INTO configuracion (clave, valor, updated_at)
        VALUES ('limpieza_docs_ultima', :v, CURRENT_TIMESTAMP)
        ON CONFLICT (clave) DO UPDATE
        SET valor = EXCLUDED.valor, updated_at = CURRENT_TIMESTAMP
    """), {"v": ahora_iso})
    db.commit()

    return {
        "borrados": borrados,
        "bytes_liberados": bytes_liberados,
        "protegidos": len(proteg),
        "errores": errores,
        "ejecutado_en": ahora_iso,
    }

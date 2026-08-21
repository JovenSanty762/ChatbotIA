"""
probar_ocr.py — Prueba el OCR de documentos SIN pasar por WhatsApp.

Lee las imágenes/PDF que le indiques (o todos los de static/documentos/), los
analiza con el proveedor configurado en .env (OCR_PROVIDER = gemini | ollama) y
muestra los datos extraídos y el tiempo que tardó. Sirve para verificar que un
OCR local (Ollama) lee bien TUS documentos antes de dejarlo en producción.

Uso:
    python probar_ocr.py                      # analiza todos los de static/documentos/
    python probar_ocr.py ruta/al/archivo.jpg  # analiza uno o varios archivos

El tipo (orden/autorización) se deduce del nombre del archivo; si no, se asume orden.
"""
import sys
import glob
import time

from ocr_processor import ProcesadorOCR
from bot_config import get_settings


def _mime(path: str) -> str:
    return "application/pdf" if path.lower().endswith(".pdf") else "image/jpeg"


def _tipo(path: str) -> str:
    return "autorizacion" if "autoriz" in path.lower() else "orden"


def main() -> None:
    s = get_settings()
    modelo = s.OLLAMA_MODEL if s.OCR_PROVIDER.lower() == "ollama" else s.GEMINI_MODEL
    print(f"🔎 Proveedor OCR: {s.OCR_PROVIDER}  |  modelo: {modelo}\n")

    archivos = sys.argv[1:] or sorted(
        glob.glob("static/documentos/*.jpg")
        + glob.glob("static/documentos/*.jpeg")
        + glob.glob("static/documentos/*.png")
        + glob.glob("static/documentos/*.pdf")
    )
    if not archivos:
        print("No hay archivos para analizar. Pasa una ruta o pon documentos en static/documentos/.")
        return

    ocr = ProcesadorOCR()
    for path in archivos:
        tipo, mime = _tipo(path), _mime(path)
        try:
            with open(path, "rb") as f:
                datos_bytes = f.read()
        except OSError as e:
            print(f"❌ No pude abrir {path}: {e}")
            continue

        t0 = time.time()
        try:
            raw = ocr._vision(datos_bytes, ocr._PROMPTS_DATOS[tipo], 500, mime, formato_json=True)
            datos = ocr._parse_json(raw)
        except Exception as e:
            print(f"❌ Error analizando {path}: {e}\n")
            continue
        dt = time.time() - t0

        print(f"📄 {path}   [{tipo} · {mime.split('/')[-1]}]   ⏱️ {dt:.1f}s")
        if datos:
            for k, v in datos.items():
                print(f"     {k}: {v}")
        else:
            print(f"     (no se pudo interpretar el texto)  →  respuesta: {raw[:200]!r}")
        print()


if __name__ == "__main__":
    main()

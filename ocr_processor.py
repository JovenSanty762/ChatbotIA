"""
Procesador de imágenes para el ChatBot de Citas Médicas.
Usa la API de IA configurada (Claude/Gemini/Groq) para extraer texto de imágenes.
Caso de uso principal: leer número de cédula desde foto del documento.
"""
import re
import os
import json
import base64
import requests
from typing import Optional

from bot_config import get_settings

settings = get_settings()

_PROMPT_CEDULA = (
    "Analiza esta imagen de un documento de identidad colombiano. "
    "Extrae únicamente el número de cédula (entre 8 y 10 dígitos). "
    "Responde SOLO con el número, sin puntos, espacios ni texto adicional. "
    "Si no encuentras un número de cédula válido, responde exactamente: NO_ENCONTRADO"
)


class ProcesadorOCR:

    def descargar_imagen_whatsapp(self, image_id: str) -> Optional[bytes]:
        """Descarga la imagen desde los servidores de WhatsApp usando el image_id."""
        try:
            meta_url = f"https://graph.facebook.com/v18.0/{image_id}"
            headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
            meta = requests.get(meta_url, headers=headers, timeout=10)
            meta.raise_for_status()
            download_url = meta.json().get("url")
            if not download_url:
                return None
            img_resp = requests.get(download_url, headers=headers, timeout=15)
            img_resp.raise_for_status()
            return img_resp.content
        except Exception as e:
            print(f"⚠️ Error descargando imagen de WhatsApp: {e}")
            return None

    def _extraer_con_claude(self, image_bytes: bytes) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        image_b64 = base64.b64encode(image_bytes).decode()
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": _PROMPT_CEDULA},
                ],
            }],
        )
        return response.content[0].text.strip()

    def _gemini_call(self, image_bytes: bytes, prompt: str, mime_type: str = "image/jpeg",
                     reintentos: int = 2) -> str:
        """
        Llama a Gemini (visión) con reintento automático si se alcanza el límite de
        peticiones por minuto (error 429 / RESOURCE_EXHAUSTED), para que una ráfaga
        de documentos no deje ninguno sin leer durante las pruebas.
        """
        import time
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=settings.GEMINI_AUTH_TOKEN)
        contents = [types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt]
        ultimo = None
        for i in range(reintentos + 1):
            try:
                resp = client.models.generate_content(model=settings.GEMINI_MODEL, contents=contents)
                return (resp.text or "").strip()
            except Exception as e:
                ultimo = e
                msg = str(e).lower()
                es_reintentable = (
                    "429" in msg or "resource_exhausted" in msg or "rate limit" in msg
                    or "quota" in msg or "503" in msg or "unavailable" in msg
                    or "high demand" in msg or "overloaded" in msg
                )
                if es_reintentable and i < reintentos:
                    espera = 3 * (i + 1)
                    print(f"⏳ Límite de OCR alcanzado; reintentando en {espera}s…")
                    time.sleep(espera)
                else:
                    raise
        raise ultimo

    def _extraer_con_gemini(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
        return self._gemini_call(image_bytes, _PROMPT_CEDULA, mime_type)

    def extraer_cedula_con_ia(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[str]:
        """Envía la imagen/PDF al proveedor de OCR configurado y extrae la cédula."""
        try:
            # Para PDF: analizar solo la primera página.
            if mime_type == "application/pdf":
                image_bytes = self._primera_pagina_pdf(image_bytes)
            # Enruta según OCR_PROVIDER (gemini/ollama/claude).
            resultado = self._vision(image_bytes, _PROMPT_CEDULA, max_tokens=50, mime_type=mime_type)

            print(f"🔍 Respuesta OCR para cédula: {repr(resultado)}")

            if not resultado or "NO_ENCONTRADO" in resultado.upper():
                return None

            # Quitar separadores (1.085.913.237) y buscar 8–10 dígitos consecutivos.
            limpio = re.sub(r"[\s\.,\-]", "", resultado)
            m = re.search(r"\d{8,10}", limpio)
            return m.group(0) if m else None

        except Exception as e:
            print(f"⚠️ Error extrayendo cédula con OCR: {e}")
            return None

    def procesar_imagen_cedula(self, image_id: str, mime_type: str = "image/jpeg") -> tuple[bool, Optional[str]]:
        """
        Descarga el archivo (foto o PDF) y extrae la cédula usando visión de IA.
        Retorna (éxito, número_cedula).
        """
        image_bytes = self.descargar_imagen_whatsapp(image_id)
        if not image_bytes:
            return False, None

        cedula = self.extraer_cedula_con_ia(image_bytes, mime_type)
        return True, cedula

    # ── Verificación de documentos (orden médica / autorización) ──────────────

    def _vision(self, image_bytes: bytes, prompt: str, max_tokens: int = 20,
                mime_type: str = "image/jpeg", formato_json: bool = False) -> str:
        """
        Envía la imagen/PDF + prompt al proveedor de OCR configurado (OCR_PROVIDER)
        y devuelve el texto. `formato_json=True` pide salida JSON estricta (solo Ollama).
        """
        provider = (settings.OCR_PROVIDER or "gemini").lower()
        if provider == "ollama":
            return self._extraer_con_ollama(image_bytes, prompt, mime_type, formato_json)
        if provider == "claude":
            return self._extraer_con_claude_prompt(image_bytes, prompt, max_tokens, mime_type)
        # Gemini (nube) — soporta imagen y PDF nativamente
        return self._extraer_con_gemini_prompt(image_bytes, prompt, max_tokens, mime_type)

    # ── OCR LOCAL con Ollama (sin límites, 100% offline) ──────────────────────

    @staticmethod
    def _pdf_a_imagen(pdf_bytes: bytes) -> bytes:
        """Rasteriza la PRIMERA página de un PDF a PNG (para modelos de visión que
        solo aceptan imágenes, como los de Ollama). Requiere PyMuPDF (fitz)."""
        import pymupdf  # PyMuPDF
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            pix = doc.load_page(0).get_pixmap(dpi=200)
            return pix.tobytes("png")
        finally:
            doc.close()

    def _extraer_con_ollama(self, image_bytes: bytes, prompt: str,
                            mime_type: str = "image/jpeg", formato_json: bool = False) -> str:
        """Envía la imagen a un modelo de visión local vía la API de Ollama."""
        # Ollama recibe IMÁGENES; si llega un PDF se rasteriza su primera página.
        if mime_type == "application/pdf":
            image_bytes = self._pdf_a_imagen(image_bytes)
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "images": [b64],
            "stream": False,
            "options": {"temperature": 0},
        }
        if formato_json:
            payload["format"] = "json"   # fuerza salida JSON válida
        url = settings.OLLAMA_HOST.rstrip("/") + "/api/generate"
        resp = requests.post(url, json=payload, timeout=settings.OLLAMA_TIMEOUT)
        resp.raise_for_status()
        return (resp.json().get("response") or "").strip()

    def _extraer_con_claude_prompt(self, image_bytes: bytes, prompt: str, max_tokens: int = 20, mime_type: str = "image/jpeg") -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        b64 = base64.b64encode(image_bytes).decode()
        # Claude: los PDF van en un bloque 'document'; las imágenes en un bloque 'image'.
        if mime_type == "application/pdf":
            media = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        else:
            media = {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}}
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": [media, {"type": "text", "text": prompt}]}],
        )
        return response.content[0].text.strip()

    def _extraer_con_gemini_prompt(self, image_bytes: bytes, prompt: str, max_tokens: int = 20, mime_type: str = "image/jpeg") -> str:
        return self._gemini_call(image_bytes, prompt, mime_type)

    _PROMPTS_DOC = {
        "orden": (
            "Observa esta imagen. ¿Es una ORDEN MÉDICA o remisión (documento clínico con "
            "indicación de una consulta, examen o procedimiento, normalmente con membrete de "
            "una institución de salud, datos del paciente y del médico que la emite)? "
            "Responde ÚNICAMENTE con 'SI' o 'NO'."
        ),
        "autorizacion": (
            "Observa esta imagen. ¿Es una AUTORIZACIÓN de servicios de salud emitida por una "
            "EPS o entidad de salud (documento que autoriza una consulta o procedimiento, con "
            "número de autorización, datos del afiliado y de la entidad)? "
            "Responde ÚNICAMENTE con 'SI' o 'NO'."
        ),
    }

    def _es_documento(self, image_bytes: bytes, tipo: str) -> bool:
        """True si la IA reconoce que la imagen corresponde al documento esperado."""
        prompt = self._PROMPTS_DOC.get(tipo, self._PROMPTS_DOC["orden"])
        try:
            resp = (self._vision(image_bytes, prompt) or "").strip().upper()
            print(f"🔍 Verificación documento ({tipo}): {resp!r}")
            # Rechaza solo si la IA dice claramente NO; acepta en cualquier otro caso.
            return not resp.startswith("NO")
        except Exception as e:
            # Fallo técnico → aceptar para no bloquear al usuario por un error de IA.
            print(f"⚠️ Error verificando documento con IA: {e}")
            return True

    def verificar_documento(self, image_id: str, tipo: str, ruta_guardado: str) -> tuple[bool, bool]:
        """
        Descarga la imagen, la guarda en `ruta_guardado` y verifica con IA si es
        el documento esperado (tipo = 'orden' | 'autorizacion').
        Retorna (descargada_ok, es_valido).
        """
        image_bytes = self.descargar_imagen_whatsapp(image_id)
        if not image_bytes:
            return False, False
        try:
            os.makedirs(os.path.dirname(ruta_guardado), exist_ok=True)
            with open(ruta_guardado, "wb") as f:
                f.write(image_bytes)
        except Exception as e:
            print(f"⚠️ Error guardando documento: {e}")
        return True, self._es_documento(image_bytes, tipo)

    # ── Extracción estructurada de datos del documento (para comparar) ────────

    _PROMPTS_DATOS = {
        "orden": (
            "Analiza este documento de salud colombiano. PRIMERO identifica QUÉ TIPO de documento "
            "es mirando su TÍTULO/encabezado y palabras clave: una ORDEN MÉDICA o REMISIÓN dice "
            "'ORDEN MEDICA', 'ORDEN MÉDICA' o 'REMISIÓN'; una AUTORIZACIÓN dice 'AUTORIZACIÓN'. "
            "Luego extrae los datos del paciente. Una orden puede listar VARIOS procedimientos, "
            "cada uno con su código CUPS (código numérico del procedimiento). "
            "Responde ÚNICAMENTE con un JSON válido, sin texto adicional ni bloques de código "
            "markdown, con esta estructura exacta:\n"
            '{"tipo_documento": "orden_medica" si es orden/remisión, "autorizacion" si es una '
            'autorización, o "otro"; '
            '"titulo": "<título o encabezado principal tal como aparece en el documento>", '
            '"nombre_paciente": "<nombre completo del paciente o null>", '
            '"cedula": "<número de documento del paciente, solo dígitos, o null>", '
            '"procedimiento": "<especialidad, examen o procedimiento indicado, o null>", '
            '"numero_orden": "<número/consecutivo de la orden médica (No. de orden), o null>", '
            '"codigo_procedimiento": "<código CUPS del procedimiento indicado, solo el código, o null>", '
            '"codigos_procedimiento": ["<lista con TODOS los códigos CUPS que aparezcan en la orden>"], '
            '"tipo_cita": "primera_vez" si la orden indica primera vez / consulta inicial / valoración; '
            '"control" si indica control / seguimiento / revisión; o null si no lo dice}'
        ),
        "autorizacion": (
            "Analiza este documento de salud colombiano. PRIMERO identifica QUÉ TIPO de documento "
            "es mirando su TÍTULO/encabezado y palabras clave: una AUTORIZACIÓN dice 'AUTORIZACIÓN'; "
            "una ORDEN MÉDICA o REMISIÓN dice 'ORDEN MEDICA', 'ORDEN MÉDICA' o 'REMISIÓN'. "
            "Luego extrae los datos. Responde ÚNICAMENTE con un JSON válido, sin texto adicional "
            "ni bloques de código markdown, con esta estructura exacta:\n"
            '{"tipo_documento": "autorizacion" si es una autorización, "orden_medica" si es '
            'orden/remisión, o "otro"; '
            '"titulo": "<título o encabezado principal tal como aparece en el documento>", '
            '"nombre_paciente": "<nombre completo del afiliado o null>", '
            '"cedula": "<número de documento del afiliado, solo dígitos, o null>", '
            '"procedimiento": "<servicio, especialidad o procedimiento autorizado, o null>", '
            '"prestador": "<nombre de la IPS/prestador del servicio, o null>", '
            '"eps": "<nombre de la EPS que emite la autorización, o null>", '
            '"fecha": "<fecha de expedición en formato YYYY-MM-DD, o null>"}'
        ),
    }

    @staticmethod
    def _primera_pagina_pdf(pdf_bytes: bytes) -> bytes:
        """
        Devuelve un PDF con SOLO la primera página, para limitar el análisis OCR a
        una sola página (menor costo/latencia). Si falla, devuelve el PDF original.
        """
        try:
            from pypdf import PdfReader, PdfWriter
            from io import BytesIO
            reader = PdfReader(BytesIO(pdf_bytes))
            if len(reader.pages) <= 1:
                return pdf_bytes
            writer = PdfWriter()
            writer.add_page(reader.pages[0])
            out = BytesIO()
            writer.write(out)
            print(f"📄 PDF de {len(reader.pages)} páginas recortado a la primera para OCR.")
            return out.getvalue()
        except Exception as e:
            print(f"⚠️ No se pudo recortar el PDF a la primera página: {e}")
            return pdf_bytes

    @staticmethod
    def _parse_json(texto: str) -> dict:
        """Extrae el primer objeto JSON del texto, tolerando fences de markdown."""
        if not texto:
            return {}
        t = texto.strip()
        t = re.sub(r"^```(?:json)?", "", t).strip()
        t = re.sub(r"```$", "", t).strip()
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if m:
            t = m.group(0)
        try:
            return json.loads(t)
        except Exception:
            return {}

    def extraer_datos_documento(self, image_id: str, tipo: str, ruta_guardado: str,
                                mime_type: str = "image/jpeg",
                                contexto_especialidad: str = None) -> tuple[bool, dict]:
        """
        Descarga el archivo (foto o PDF), lo guarda y extrae con OCR/IA los datos
        del documento como diccionario para poder compararlos.
        `contexto_especialidad` (solo orden): si la orden lista varios procedimientos,
        indica de cuál especialidad/servicio tomar el `codigo_procedimiento`.
        Retorna (descargada_ok, datos). `datos` viene vacío si no se pudo interpretar.
        """
        image_bytes = self.descargar_imagen_whatsapp(image_id)
        if not image_bytes:
            return False, {}
        try:
            os.makedirs(os.path.dirname(ruta_guardado), exist_ok=True)
            with open(ruta_guardado, "wb") as f:
                f.write(image_bytes)
        except Exception as e:
            print(f"⚠️ Error guardando documento: {e}")

        # Para PDF: analizar solo la primera página.
        bytes_ia = self._primera_pagina_pdf(image_bytes) if mime_type == "application/pdf" else image_bytes

        prompt = self._PROMPTS_DATOS.get(tipo, self._PROMPTS_DATOS["orden"])
        # Si la orden trae varios códigos CUPS, orienta cuál corresponde al servicio
        # que el paciente está agendando (para la clave única de agendamiento).
        if tipo == "orden" and contexto_especialidad:
            prompt += (
                f"\nEl paciente está agendando el servicio/especialidad: "
                f"'{contexto_especialidad}'. Si la orden lista VARIOS procedimientos, "
                f"'codigo_procedimiento' debe ser el código CUPS que corresponda a ESE servicio."
            )
        try:
            raw = self._vision(bytes_ia, prompt, max_tokens=500, mime_type=mime_type, formato_json=True)
            datos = self._parse_json(raw)
            print(f"🔍 Datos extraídos ({tipo}): {datos}")
            return True, datos
        except Exception as e:
            print(f"⚠️ Error extrayendo datos del documento: {e}")
            return True, {}

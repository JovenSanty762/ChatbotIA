"""
Procesador de IA para el ChatBot de Citas Médicas
Soporta múltiples proveedores: Claude (Anthropic), Google Gemini, Groq (Llama).
El proveedor activo se configura con AI_PROVIDER en .env
"""

import json
from datetime import date
from typing import Optional

from bot_config import get_settings

settings = get_settings()

# ──────────────────────────────────────────────────────────────
# Prompt del sistema (igual para todos los proveedores)
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente médico especializado en extraer información de solicitudes de citas.

Tu única tarea es analizar el mensaje del usuario y devolver un JSON con los datos de la cita.

REGLAS ESTRICTAS:
- Responde SIEMPRE con JSON válido, sin texto adicional, sin bloques de código markdown.
- Solo usa especialidades del listado proporcionado (compara por similitud de nombre).
- Solo usa fechas del listado de fechas disponibles.
- Para fechas relativas ("mañana", "lunes", "próxima semana") usa la fecha de hoy como referencia.
- "mañana" a secas se refiere al DÍA siguiente (fecha_sugerida), NO a la jornada.
- La jornada solo es "manana" cuando el usuario dice "por la mañana", "en la mañana",
  "en horas de la mañana" o similar; es "tarde" cuando dice "por la tarde", "en la tarde".
- Si el usuario menciona hora, conviértela a formato HH:MM (24h). Si dice "10am" → "10:00", "3pm" → "15:00".
  Además, si hay hora pero no jornada explícita, deduce la jornada: hora < 12:00 → "manana", hora >= 12:00 → "tarde".
- nombre_medico: extrae el nombre del médico si el usuario lo menciona ("con el doctor Pérez",
  "con la Dra. Laura", "que me atienda Gómez"). Devuelve solo el nombre/apellido, sin "Dr." ni "Dra.".
- Si un dato no está en el mensaje, devuelve null para ese campo.
- id_especialidad debe ser el número entero del listado, no el nombre.

ESTRUCTURA DE RESPUESTA:
{
  "es_solicitud_cita": true o false,
  "id_especialidad": <entero o null>,
  "nombre_especialidad": "<texto o null>",
  "fecha_sugerida": "<YYYY-MM-DD o null>",
  "hora_preferida": "<HH:MM o null>",
  "jornada": "<manana|tarde o null>",
  "nombre_medico": "<texto o null>",
  "confianza": "<alta|media|baja>",
  "info_faltante": ["especialidad", "fecha"]
}"""


def _construir_prompt_usuario(
    mensaje: str,
    especialidades: list,
    fechas_disponibles: list,
    hoy: date,
) -> str:
    esp_texto = "\n".join(f"  ID {e['id']}: {e['nombre']}" for e in especialidades)
    fechas_texto = ", ".join(f["fecha"] for f in fechas_disponibles[:15])
    return (
        f"Fecha de hoy: {hoy.isoformat()}\n\n"
        f"Especialidades disponibles:\n{esp_texto}\n\n"
        f"Fechas disponibles (YYYY-MM-DD): {fechas_texto}\n\n"
        f"Mensaje del usuario: \"{mensaje}\""
    )


# ──────────────────────────────────────────────────────────────
# Backend: Claude
# ──────────────────────────────────────────────────────────────
def _analizar_con_claude(prompt_usuario: str) -> dict:
    import anthropic
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY no configurada en .env")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt_usuario}],
    )
    return json.loads(response.content[0].text.strip())


# ──────────────────────────────────────────────────────────────
# Backend: Google Gemini
# ──────────────────────────────────────────────────────────────
def _analizar_con_gemini(prompt_usuario: str) -> dict:
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise ImportError("Instala google-genai: pip install google-genai")

    api_key = settings.GEMINI_AUTH_TOKEN
    if not api_key:
        raise ValueError("GEMINI_AUTH_TOKEN no configurada en .env")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=[prompt_usuario],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    return json.loads((response.text or "").strip())


# ──────────────────────────────────────────────────────────────
# Backend: Groq (Llama)
# ──────────────────────────────────────────────────────────────
def _analizar_con_groq(prompt_usuario: str) -> dict:
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("Instala groq: pip install groq")

    api_key = settings.GROQ_AUTH_TOKEN
    if not api_key:
        raise ValueError("GROQ_AUTH_TOKEN no configurada en .env")

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_usuario},
        ],
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content.strip())


# ──────────────────────────────────────────────────────────────
# Clase pública (interfaz única para bot_handler.py)
# ──────────────────────────────────────────────────────────────
class ProcesadorIA:

    def analizar_solicitud_cita(
        self,
        mensaje: str,
        especialidades: list,
        fechas_disponibles: list,
        hoy: Optional[date] = None,
    ) -> dict:
        if hoy is None:
            hoy = date.today()

        prompt_usuario = _construir_prompt_usuario(mensaje, especialidades, fechas_disponibles, hoy)
        proveedor = settings.AI_PROVIDER.lower()

        print(f"🤖 IA activa: {proveedor.upper()} | Procesando solicitud...")

        if proveedor == "gemini":
            return _analizar_con_gemini(prompt_usuario)
        elif proveedor == "groq":
            return _analizar_con_groq(prompt_usuario)
        else:
            return _analizar_con_claude(prompt_usuario)

    def generar_resumen_extraccion(self, resultado: dict) -> str:
        partes = []
        if resultado.get("nombre_especialidad"):
            partes.append(f"🏥 Especialidad: *{resultado['nombre_especialidad']}*")
        if resultado.get("fecha_sugerida"):
            partes.append(f"📅 Fecha: *{resultado['fecha_sugerida']}*")
        if resultado.get("jornada"):
            jornada_txt = "Mañana" if resultado["jornada"] == "manana" else "Tarde"
            partes.append(f"🌗 Jornada: *{jornada_txt}*")
        if resultado.get("hora_preferida"):
            partes.append(f"🕐 Hora preferida: *{resultado['hora_preferida']}*")
        if resultado.get("nombre_medico"):
            partes.append(f"👨‍⚕️ Médico: *{resultado['nombre_medico']}*")
        return "\n".join(partes) if partes else ""

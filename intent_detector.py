"""
Intent Detector + Slot Filling para el ChatBot de Citas Médicas.

Alineado 1:1 con el flujo real de `EstadoFlujo` (ver bot_handler.py). A partir
del TEXTO LIBRE que el paciente escribe al agendar, extrae toda la información
posible y devuelve `hasta_que_paso_puede_avanzar()`: el estado más avanzado
del flujo al que el bot puede saltar sin volver a preguntar.

Reglas de avance — TOPE en ESPERAR_DOC_ORDEN:

    Paso                       Requisitos
    ────────────────────────── ────────────────────────────────────────────
    1. MENU_PRINCIPAL          intención == "agendar_cita"
    2. SELECCIONAR_ESPECIALIDAD ↑ (con eso ya se muestra la lista)
    3. SELECCIONAR_TIPO_CITA   + especialidad detectada
    4. ESPERAR_DOC_ORDEN       + tipo_cita → *tope máximo alcanzable*

El flujo NUNCA salta directamente a médico/fecha/hora aunque el paciente los
haya escrito en el mensaje, porque el hospital exige recibir primero la orden
médica (y, según la EPS, la autorización). Todo dato "adicional" que el
paciente escriba (nombre del médico, fecha, hora, turno) queda listado en
`slots_pospuestos` para que el handler los guarde como temporales `_ia` y los
aplique automáticamente en cuanto reciba los documentos:

    ESPERAR_DOC_ORDEN → [documentos cargados] → aplicar slots_pospuestos →
    saltar directo al paso más avanzado posible (médico/fecha/hora/confirmar).

Uso rápido:

    detector = IntentDetector()
    an = detector.analizar_texto("cita con la Dra. Erazo de oftalmología
                                  el viernes a las 10 de la mañana")
    an.intent                # 'agendar_cita'
    an.slots['especialidad'] # 'Oftalmologia'
    an.slots['medico']       # 'erazo'
    an.slots['fecha']        # '2026-08-28'
    an.slots['hora']         # '10:00'
    an.hasta_paso            # 'esperar_doc_orden'  (tope)
    an.faltantes             # ['tipo_cita', 'documentos']
    an.slots_pospuestos      # ['medico', 'fecha', 'hora']  ← guardar como _ia

Implementación pura en Python — sin dependencias externas. No reemplaza al
`ai_processor` (Groq/Gemini/Claude): corre ANTES como filtro barato para saber
si vale la pena invocar al LLM y cuánto contexto pasarle.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple


# ============================================================================
# Constantes del flujo (deben coincidir con EstadoFlujo de bot_handler.py)
# ============================================================================

class PasoFlujo:
    """Etiquetas de los pasos del agendamiento, en orden."""
    MENU_PRINCIPAL          = "menu_principal"
    SELECCIONAR_ESPECIALIDAD = "seleccionar_especialidad"
    SELECCIONAR_TIPO_CITA   = "seleccionar_tipo_cita"
    ESPERAR_DOC_ORDEN       = "esperar_doc_orden"
    SELECCIONAR_MEDICO      = "seleccionar_medico"
    SELECCIONAR_FECHA       = "seleccionar_fecha"
    SELECCIONAR_HORA        = "seleccionar_hora"
    CONFIRMAR_CITA          = "confirmar_cita"


# Orden explícito de los pasos: define hasta dónde puede avanzar la IA.
_ORDEN_PASOS: List[str] = [
    PasoFlujo.MENU_PRINCIPAL,
    PasoFlujo.SELECCIONAR_ESPECIALIDAD,
    PasoFlujo.SELECCIONAR_TIPO_CITA,
    PasoFlujo.ESPERAR_DOC_ORDEN,
    PasoFlujo.SELECCIONAR_MEDICO,
    PasoFlujo.SELECCIONAR_FECHA,
    PasoFlujo.SELECCIONAR_HORA,
    PasoFlujo.CONFIRMAR_CITA,
]


# ============================================================================
# Diccionarios de detección
# ============================================================================

# Sinónimos y variantes → nombre canónico exacto de la tabla `especialidades`
# de sql_db.sql. Todo en minúsculas y sin tildes (la comparación normaliza).
_ESPECIALIDADES_MAP: Dict[str, List[str]] = {
    "Anestesiologia": ["anestesia", "anestesiologia", "anestesiologo", "anestesista"],
    "Cardiologia": ["cardio", "cardiologia", "cardiologo", "corazon"],
    "Cardiologia Pediatrica": ["cardio pediatrica", "cardiologia pediatrica",
                                "cardiologo pediatra", "cardio infantil"],
    "Cirugia General": ["cirugia general", "cirujano general", "cirugia"],
    "Cirugia Maxilofacial": ["maxilofacial", "cirugia maxilofacial"],
    "Cirugia Vascular": ["cirugia vascular", "vascular", "venas", "arterias"],
    "Dermatologia": ["dermatologia", "dermatologo", "piel", "acne"],
    "Dolor y Cuidados Paliativos": ["dolor", "cuidados paliativos", "paliativos"],
    "Gastroenterologia": ["gastro", "gastroenterologia", "gastroenterologo",
                          "estomago", "digestivo", "colon"],
    "Ginecologia y Obstetricia": ["gineco", "ginecologia", "ginecologo",
                                   "obstetricia", "obstetra", "embarazo",
                                   "control prenatal"],
    "Medicina Interna": ["medicina interna", "internista"],
    "Nefrologia": ["nefrologia", "nefrologo", "rinon", "riñon", "renal"],
    "Neurocirugia": ["neurocirugia", "neurocirujano", "cirugia de cerebro",
                     "cirugia neurologica"],
    "Nutricion": ["nutricion", "nutricionista", "dietista", "dieta"],
    "Oftalmologia": ["oftalmologia", "oftalmologo", "ojos", "vista", "ocular"],
    "Ortopedia y Traumatologia": ["ortopedia", "ortopedista", "traumatologia",
                                   "traumatologo", "trauma", "hueso", "fractura",
                                   "rodilla", "columna"],
    "Otorrinolaringologia": ["otorrino", "otorrinolaringologia", "oido", "oído",
                             "nariz", "garganta", "orl"],
    "Pediatria": ["pediatra", "pediatria", "pediatrico", "niño", "nina",
                  "niños", "infantil"],
    "Pediatria Canguro": ["canguro", "madre canguro", "pediatria canguro",
                          "programa canguro"],
    "Perinatologia": ["perinatologia", "perinatologo", "alto riesgo obstetrico",
                      "embarazo alto riesgo"],
    "Psicologia": ["psicologia", "psicologo", "salud mental", "ansiedad",
                   "depresion", "terapia psicologica"],
    "Reumatologia": ["reumatologia", "reumatologo", "artritis", "articulaciones"],
    "Urologia": ["urologia", "urologo", "prostata", "urinario"],
    "Procedimientos": ["procedimiento", "procedimientos"],
}

# Sinónimos por intención (agendar/ver/cancelar/saludo/ayuda).
_INTENTS: Dict[str, List[str]] = {
    "agendar_cita": [
        "agendar", "agenda", "quiero cita", "quiero una cita",
        "necesito cita", "necesito una cita", "reservar", "reserva",
        "programar", "programa una cita", "pedir cita", "solicitar cita",
        "sacar cita", "conseguir cita", "consultar con", "ver doctor",
        "ver medico", "turno", "cita medica", "cita con",
    ],
    "ver_citas": [
        "mis citas", "ver citas", "ver mis citas", "que citas tengo",
        "que cita tengo", "citas agendadas", "proximas citas", "proxima cita",
        "tengo cita", "consultar citas", "mostrar citas",
    ],
    "cancelar_cita": [
        "cancelar cita", "cancelar mi cita", "anular cita", "eliminar cita",
        "borrar cita", "quiero cancelar", "no puedo asistir", "no podre ir",
    ],
    "saludo": [
        "hola", "buenos dias", "buenas tardes", "buenas noches", "buenas",
        "hey", "buen dia", "saludos",
    ],
    "ayuda": [
        "ayuda", "help", "que puedes hacer", "opciones", "menu",
        "como funciona",
    ],
}

# Tipo de cita: primera vez vs. control/seguimiento.
_KW_PRIMERA_VEZ = ("primera vez", "primera consulta", "primera cita", "nueva",
                    "por primera vez", "consulta inicial")
_KW_CONTROL = ("control", "seguimiento", "revision", "chequeo",
                "post operatorio", "postoperatorio", "post-quirurgico",
                "postquirurgico", "resultado", "resultados")

# Turno / jornada.
_KW_MANANA = ("mañana temprano", "en la mañana", "por la mañana",
               "en la manana", "por la manana", "temprano",
               "matutino", "am", "a.m.", "medio dia", "medio día", "mediodia")
_KW_TARDE = ("en la tarde", "por la tarde", "tarde", "vespertino",
              "pm", "p.m.", "despues del mediodia")

# EPS: mismo listado que en sql_db.sql (sección 5.2).
_EPS_LIST = [
    "nueva eps", "sanitas", "sura", "salud total", "coosalud", "emssanar",
    "cajacopi", "famisanar", "compensar", "mutual ser", "asmet salud",
    "particular",
]

# Días de la semana en español y sus equivalentes ISO (1=lunes … 7=domingo).
_DIAS_SEMANA = {
    "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4,
    "viernes": 5, "sabado": 6, "domingo": 7,
}

# Meses en español.
_MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}


# ============================================================================
# Modelo del resultado
# ============================================================================

@dataclass
class Analisis:
    """
    Resultado completo del análisis del texto libre del paciente.

    Attributes:
        intent:            Intención detectada ('agendar_cita', 'ver_citas', ...).
        slots:             Diccionario con todos los datos extraídos.
        hasta_paso:        Último paso al que el bot puede saltar SOLO con este
                           texto. Tope máximo = `ESPERAR_DOC_ORDEN`, porque los
                           documentos no se pueden resolver con texto.
        faltantes:         Datos que el bot todavía debe preguntar para llegar
                           al tope (`tipo_cita`, `documentos`, …).
        slots_pospuestos:  Slots que YA se extrajeron pero cuyo paso queda más
                           adelante de `ESPERAR_DOC_ORDEN` (medico/fecha/hora/
                           turno). El handler debe guardarlos como temporales
                           `_ia` y aplicarlos automáticamente en cuanto reciba
                           la orden médica y la autorización.
        confianza:         0.0-1.0 · cuán fiable es el mapeo (más matches → +).
    """
    intent: str = "desconocido"
    slots: Dict = field(default_factory=dict)
    hasta_paso: str = PasoFlujo.MENU_PRINCIPAL
    faltantes: List[str] = field(default_factory=list)
    slots_pospuestos: List[str] = field(default_factory=list)
    confianza: float = 0.0

    def as_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "slots": self.slots,
            "hasta_paso": self.hasta_paso,
            "faltantes": self.faltantes,
            "slots_pospuestos": self.slots_pospuestos,
            "confianza": round(self.confianza, 2),
        }


# ============================================================================
# Detector principal
# ============================================================================

class IntentDetector:
    """
    Detector de intenciones + slot-filling alineado con el flujo del hospital.

    Método principal: `analizar_texto(texto)` → objeto `Analisis`.

    Compat: `analizar_mensaje(texto)` sigue devolviendo `(intent, slots)` para
    no romper `bot_handler.procesar_agendamiento_inteligente()`.
    """

    # ---- Compatibilidad hacia atrás -----------------------------------------
    #
    # Estas dos listas se conservan porque estaban expuestas como atributos
    # públicos en la versión anterior. Los tests / scripts que las usen siguen
    # funcionando, pero internamente ya no se consultan.
    def __init__(self):
        self.intents_keywords: Dict[str, List[str]] = _INTENTS
        self.especialidades_keywords: List[str] = [
            kw for kws in _ESPECIALIDADES_MAP.values() for kw in kws
        ]

    # ─────────────────────────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────────────────────────

    def analizar_texto(self, texto: str, hoy: Optional[date] = None) -> Analisis:
        """
        Analiza el texto libre del paciente y devuelve toda la información
        estructurada + hasta qué paso del flujo se puede avanzar.
        """
        if not texto or not texto.strip():
            return Analisis()

        hoy = hoy or date.today()
        norm = self._normalizar(texto)

        an = Analisis()
        an.intent = self._detectar_intent(norm)
        an.slots = self._extraer_slots(texto, norm, hoy)
        (an.hasta_paso, an.faltantes,
         an.slots_pospuestos) = self._calcular_avance(an.intent, an.slots)
        an.confianza = self._puntuar_confianza(an.intent, an.slots)
        return an

    # ── Compat con la versión anterior ───────────────────────────────────────
    def detectar_intent(self, texto: str) -> str:
        """(Compat) Devuelve solo la intención."""
        return self._detectar_intent(self._normalizar(texto))

    def extraer_slots(self, texto: str) -> Dict:
        """(Compat) Devuelve solo el diccionario de slots."""
        return self._extraer_slots(texto, self._normalizar(texto), date.today())

    def analizar_mensaje(self, texto: str) -> Tuple[str, Dict]:
        """
        (Compat) Devuelve `(intent, slots)`.

        Mantiene la firma antigua para que `bot_handler.py` siga funcionando sin
        cambios; los slots incluyen ahora TODOS los campos nuevos, así que el
        handler puede leerlos si quiere avanzar directo al paso más lejano.
        """
        an = self.analizar_texto(texto)
        return an.intent, an.slots

    # ─────────────────────────────────────────────────────────────────────────
    # Detección
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalizar(texto: str) -> str:
        """Minúsculas + sin tildes + colapso de espacios."""
        t = unicodedata.normalize("NFKD", texto or "")
        t = "".join(c for c in t if not unicodedata.combining(c))
        return re.sub(r"\s+", " ", t.lower().strip())

    def _detectar_intent(self, norm: str) -> str:
        """
        Prioridad: cancelar > ver > agendar > saludo > ayuda > desconocido.
        Un mensaje como "hola quiero una cita" debe ser 'agendar_cita', no
        'saludo'. El orden aquí garantiza esa preferencia.
        """
        for intent in ("cancelar_cita", "ver_citas", "agendar_cita",
                       "ayuda", "saludo"):
            if any(kw in norm for kw in _INTENTS[intent]):
                return intent
        # Heurística extra: si menciona una especialidad, casi seguro quiere cita.
        for variantes in _ESPECIALIDADES_MAP.values():
            if any(v in norm for v in variantes):
                return "agendar_cita"
        return "desconocido"

    def _extraer_slots(self, original: str, norm: str, hoy: date) -> Dict:
        """Extrae TODAS las entidades del mensaje."""
        slots: Dict = {}

        esp = self._detectar_especialidad(norm)
        if esp:
            slots["especialidad"] = esp

        tipo = self._detectar_tipo_cita(norm)
        if tipo:
            slots["tipo_cita"] = tipo

        medico = self._detectar_medico(original, norm)
        if medico:
            slots["medico"] = medico

        eps = self._detectar_eps(norm)
        if eps:
            slots["eps"] = eps

        fecha_iso, fecha_rel = self._detectar_fecha(norm, hoy)
        if fecha_iso:
            slots["fecha"] = fecha_iso
        if fecha_rel:
            slots["fecha_relativa"] = fecha_rel

        turno = self._detectar_turno(norm)
        if turno:
            slots["turno"] = turno

        hora = self._detectar_hora(norm)
        if hora:
            slots["hora"] = hora

        return slots

    # -- especialidad ---------------------------------------------------------
    @staticmethod
    def _detectar_especialidad(norm: str) -> Optional[str]:
        """
        Busca el nombre canónico. Estrategia: la coincidencia MÁS LARGA gana
        (así "cardiologia pediatrica" pesa más que "cardiologia").
        """
        mejor: Tuple[int, Optional[str]] = (0, None)
        for canon, variantes in _ESPECIALIDADES_MAP.items():
            for v in variantes:
                if v in norm and len(v) > mejor[0]:
                    mejor = (len(v), canon)
        return mejor[1]

    # -- tipo de cita ---------------------------------------------------------
    @staticmethod
    def _detectar_tipo_cita(norm: str) -> Optional[str]:
        if any(k in norm for k in _KW_PRIMERA_VEZ):
            return "primera_vez"
        if any(k in norm for k in _KW_CONTROL):
            return "control"
        return None

    # -- médico ---------------------------------------------------------------
    @staticmethod
    def _detectar_medico(original: str, norm: str) -> Optional[str]:
        """
        Detecta el nombre del médico en varias formas:
            · "Dr. Medina" / "Dra. Erazo"     → 'medina', 'erazo'
            · "doctor Rueda"                   → 'rueda'
            · "con el doctor Robert Paredes"   → 'robert paredes'
            · "medico Yonathan Rueda"          → 'yonathan rueda'
        Devuelve el token/tokens en minúsculas, sin tildes.
        """
        # Patrón 1: Dr./Dra. + una o dos palabras
        m = re.search(
            r"\b(?:dr|dra|doctor|doctora|medico|medica)\.?\s+"
            r"([a-zñ]+(?:\s+[a-zñ]+)?)",
            norm,
        )
        if m:
            candidato = m.group(1).strip()
            # Filtrar palabras que no son nombre (preposiciones/artículos)
            stop = {"de", "del", "la", "el", "con", "para", "que", "en", "y"}
            tokens = [t for t in candidato.split() if t not in stop and len(t) > 2]
            if tokens:
                return " ".join(tokens[:2])
        return None

    # -- EPS ------------------------------------------------------------------
    @staticmethod
    def _detectar_eps(norm: str) -> Optional[str]:
        for eps in _EPS_LIST:
            if eps in norm:
                return eps.title()
        return None

    # -- fecha ----------------------------------------------------------------
    def _detectar_fecha(
        self, norm: str, hoy: date
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Devuelve (fecha ISO 'YYYY-MM-DD', etiqueta relativa) — o (None, None).
        Reconoce:
            · "hoy", "mañana", "pasado mañana"
            · "próximo lunes", "el viernes", "este sabado"
            · "15/09", "15-09-2026", "15 de septiembre"
        """
        # 1) Relativos simples
        if re.search(r"\bhoy\b", norm):
            return hoy.isoformat(), "hoy"
        if re.search(r"\bpasado ?mañana\b|\bpasado manana\b", norm):
            return (hoy + timedelta(days=2)).isoformat(), "pasado_manana"
        if re.search(r"\bmañana\b|\bmanana\b", norm) \
                and not re.search(r"(en la|por la|de la|esta)\s+manana", norm):
            return (hoy + timedelta(days=1)).isoformat(), "manana"

        # 2) "próximo/este + día de la semana"
        m = re.search(r"\b(proximo|proxima|este|esta|el|la)\s+"
                       r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b",
                       norm)
        if m:
            dia_nombre = m.group(2)
            dia_iso = _DIAS_SEMANA[dia_nombre]
            delta = (dia_iso - hoy.isoweekday()) % 7
            if delta == 0:
                delta = 7  # "próximo lunes" en lunes = el siguiente
            return (hoy + timedelta(days=delta)).isoformat(), dia_nombre

        # 3) "el 15 de septiembre" / "15 de septiembre [de 2026]"
        m = re.search(r"\b(\d{1,2})\s+de\s+(" + "|".join(_MESES) + r")"
                       r"(?:\s+de\s+(\d{4}))?\b", norm)
        if m:
            d = int(m.group(1))
            mo = _MESES[m.group(2)]
            y = int(m.group(3)) if m.group(3) else hoy.year
            try:
                f = date(y, mo, d)
                if f < hoy:  # si ya pasó este año, asumir el siguiente
                    f = date(y + 1, mo, d)
                return f.isoformat(), None
            except ValueError:
                pass

        # 4) DD/MM[/YYYY] o DD-MM[-YYYY]
        m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", norm)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            y_raw = m.group(3)
            if y_raw:
                y = int(y_raw)
                if y < 100:
                    y += 2000
            else:
                y = hoy.year
            try:
                f = date(y, mo, d)
                if f < hoy and not y_raw:
                    f = date(y + 1, mo, d)
                return f.isoformat(), None
            except ValueError:
                pass

        # 5) Sin fecha exacta, pero sí una señal difusa ("esta semana", "pronto")
        if re.search(r"\besta semana\b|\bproxima semana\b|\bproxima\b|\bpronto\b",
                     norm):
            return None, "pronto"

        return None, None

    # -- turno / hora ---------------------------------------------------------
    @staticmethod
    def _detectar_turno(norm: str) -> Optional[str]:
        if any(k in norm for k in _KW_MANANA):
            return "manana"
        if any(k in norm for k in _KW_TARDE):
            return "tarde"
        return None

    @staticmethod
    def _detectar_hora(norm: str) -> Optional[str]:
        """
        Devuelve la hora en formato HH:MM (24h). Reconoce:
            · "10:30", "10:30 am", "3:15 pm"
            · "las 10", "10 de la mañana", "3 de la tarde", "10am"
        """
        # 1) HH:MM opcional AM/PM
        m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b", norm)
        if m:
            h, mnt = int(m.group(1)), int(m.group(2))
            suf = (m.group(3) or "").replace(".", "")
            if suf == "pm" and h < 12:
                h += 12
            elif suf == "am" and h == 12:
                h = 0
            if 0 <= h <= 23 and 0 <= mnt <= 59:
                return f"{h:02d}:{mnt:02d}"

        # 2) "10 de la mañana", "3 de la tarde"
        m = re.search(r"\b(\d{1,2})\s+de la (manana|tarde|noche)\b", norm)
        if m:
            h = int(m.group(1))
            franja = m.group(2)
            if franja in ("tarde", "noche") and h < 12:
                h += 12
            if 0 <= h <= 23:
                return f"{h:02d}:00"

        # 3) "10am", "3 pm", "a las 10 am"
        m = re.search(r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)\b", norm)
        if m:
            h = int(m.group(1))
            suf = m.group(2).replace(".", "")
            if suf == "pm" and h < 12:
                h += 12
            elif suf == "am" and h == 12:
                h = 0
            if 0 <= h <= 23:
                return f"{h:02d}:00"

        # 4) "a las 10" — asumir mañana si es <=11, tarde si es 1-7
        m = re.search(r"\b(?:a las|las)\s+(\d{1,2})\b(?!\s*[/-])", norm)
        if m:
            h = int(m.group(1))
            if 1 <= h <= 7:
                h += 12  # "a las 3" en contexto de cita → 15:00
            if 0 <= h <= 23:
                return f"{h:02d}:00"

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Cálculo de avance
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _calcular_avance(
        intent: str, slots: Dict
    ) -> Tuple[str, List[str], List[str]]:
        """
        Regla progresiva TOPADA en `ESPERAR_DOC_ORDEN`.

        Devuelve `(paso_maximo, faltantes, slots_pospuestos)`:
          · paso_maximo       último paso al que el bot puede llegar con solo
                              este texto (nunca pasa de ESPERAR_DOC_ORDEN).
          · faltantes         datos que el bot TODAVÍA debe preguntar para
                              llegar al tope: `tipo_cita`, `documentos`, etc.
          · slots_pospuestos  slots que YA se extrajeron y cuyo paso viene
                              DESPUÉS de los documentos (medico/fecha/hora/
                              turno). El handler los guarda como temporales
                              `_ia` y los aplica en `continuar_tras_documentos`.

        Motivo del tope: el hospital exige que el paciente envíe primero la
        orden médica (y, según la EPS, la autorización). Aunque el paciente
        escriba "cita con la Dra. Erazo el viernes a las 10", el bot debe
        primero recibir la foto/PDF; los otros datos se reservan.
        """
        # Si no es intención de cita, la IA no avanza el flujo.
        if intent != "agendar_cita":
            return PasoFlujo.MENU_PRINCIPAL, [], []

        # ── Slots pospuestos: los que sirven para pasos POSTERIORES a los
        #    documentos. Se guardan sin importar hasta dónde llegue el flujo,
        #    para que el handler pueda saltar pasos cuando llegue la orden.
        pospuestos: List[str] = [
            k for k in ("medico", "fecha", "hora", "turno") if slots.get(k)
        ]

        # ── Avance hasta el tope (ESPERAR_DOC_ORDEN) ────────────────────────
        faltantes: List[str] = []
        paso = PasoFlujo.SELECCIONAR_ESPECIALIDAD

        if not slots.get("especialidad"):
            faltantes.extend(["especialidad", "tipo_cita", "documentos"])
            return paso, faltantes, pospuestos

        paso = PasoFlujo.SELECCIONAR_TIPO_CITA
        if not slots.get("tipo_cita"):
            faltantes.append("tipo_cita")

        # Los documentos NUNCA se resuelven con texto → siempre faltan.
        faltantes.append("documentos")

        # Con tipo_cita explícito el bot puede saltar el menú "primera vez /
        # control" y ya pedir directamente la orden médica.
        if slots.get("tipo_cita"):
            paso = PasoFlujo.ESPERAR_DOC_ORDEN

        return paso, faltantes, pospuestos

    # ─────────────────────────────────────────────────────────────────────────
    # Confianza
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _puntuar_confianza(intent: str, slots: Dict) -> float:
        """
        0.0 (nada útil) a 1.0 (todo lo necesario). Pesos:
            intent válido        0.30
            especialidad         0.25
            tipo_cita            0.10
            medico               0.10
            fecha (exacta+rel)   0.15
            hora                 0.10
        """
        if intent == "desconocido":
            return 0.0
        score = 0.3
        if slots.get("especialidad"):     score += 0.25
        if slots.get("tipo_cita"):        score += 0.10
        if slots.get("medico"):           score += 0.10
        if slots.get("fecha"):            score += 0.15
        elif slots.get("fecha_relativa"): score += 0.05
        if slots.get("hora"):             score += 0.10
        return min(score, 1.0)


# ============================================================================
# Demo / self-test
# ============================================================================

if __name__ == "__main__":
    detector = IntentDetector()

    ejemplos = [
        # (texto, comentario)
        ("hola",
         "Solo saludo — no avanza."),
        ("quiero una cita",
         "Solo intención — llega a pedir especialidad."),
        ("cita con cardiologia",
         "Especialidad → siguiente paso: tipo de cita."),
        ("necesito una cita de control con oftalmologia",
         "+ tipo control → puede pedir documentos."),
        ("cita primera vez con ortopedia con el Dr. Paredes",
         "+ medico → puede saltar a fecha."),
        ("cita de control con ginecologia con la Dra. Hernandez el 15 de septiembre",
         "+ fecha → puede saltar a hora."),
        ("cita primera vez con cardiologia con Dr. Medina el proximo viernes a las 10 de la mañana",
         "TODO detectado → confirmar (falta documentos)."),
        ("mis citas",
         "Otra intención."),
        ("cancelar mi cita del viernes",
         "Cancelar."),
        ("necesito psicologia esta semana en la tarde",
         "Especialidad + fecha difusa + turno."),
    ]

    for texto, nota in ejemplos:
        an = detector.analizar_texto(texto)
        print(f"\n------- {nota}")
        print(f"Texto:        {texto}")
        print(f"Intent:       {an.intent}")
        print(f"Slots:        {an.slots}")
        print(f"Hasta paso:   {an.hasta_paso}")
        print(f"Faltantes:    {an.faltantes}")
        print(f"Pospuestos:   {an.slots_pospuestos}")
        print(f"Confianza:    {an.confianza:.2f}")

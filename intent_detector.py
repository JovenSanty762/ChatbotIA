"""
Intent Detector + Slot Filling para ChatBot de Citas Médicas
Implementación pura en Python — sin dependencias de modelos externos.
"""

import re
from typing import Dict, Tuple


class IntentDetector:
    """
    Detector de intenciones y extractor de entidades para agendamiento de citas.
    Usa solo regex y coincidencia de palabras clave; no requiere spaCy ni modelos.
    """

    def __init__(self):
        self.intents_keywords = {
            "agendar_cita": [
                "agendar", "cita", "quiero cita", "necesito cita", "reservar",
                "programar", "pedir cita", "ver doctor", "consultar", "turno",
                "appointment", "médico", "medico", "especialista",
            ],
            "ver_citas": [
                "mis citas", "ver citas", "qué citas tengo", "citas agendadas",
                "mis próximas citas", "proximas citas", "tengo cita",
            ],
            "cancelar_cita": [
                "cancelar", "anular", "eliminar cita", "cancelar mi cita",
                "quiero cancelar", "borrar cita",
            ],
            "saludo": [
                "hola", "buenos días", "buenas tardes", "buenas noches",
                "buenas", "hey", "buen dia", "buen día",
            ],
        }

        self.especialidades_keywords = [
            "cardiologo", "cardiólogo", "cardiologia", "cardiología",
            "medico general", "médico general", "medicina general",
            "pediatra", "pediatria", "pediatría",
            "ginecologo", "ginecólogo", "ginecologia", "ginecología",
            "odontologo", "odontólogo", "odontologia", "odontología",
            "dermatologo", "dermatólogo", "dermatologia", "dermatología",
            "neurologo", "neurólogo", "neurologia", "neurología",
            "ortopedista", "ortopedia", "traumatologia", "traumatología",
            "oftalmologo", "oftalmólogo", "oftalmologia", "oftalmología",
            "psicologia", "psicología", "psicologo", "psicólogo",
            "nutricion", "nutrición", "nutricionista",
            "urologia", "urología", "urologo", "urólogo",
            "diabetes", "control", "chequeo", "consulta general",
        ]

    def detectar_intent(self, texto: str) -> str:
        """Detecta la intención principal del mensaje."""
        texto_lower = texto.lower().strip()
        for intent, keywords in self.intents_keywords.items():
            if any(kw in texto_lower for kw in keywords):
                return intent
        return "desconocido"

    def extraer_slots(self, texto: str) -> Dict:
        """Extrae entidades relevantes: especialidad, fecha relativa, horario y médico."""
        slots = {}
        texto_lower = texto.lower()

        # 1. Especialidad médica
        for esp in self.especialidades_keywords:
            if esp in texto_lower:
                slots["especialidad"] = esp
                break

        # 2. Fecha relativa
        if re.search(r"mañana|pasado mañana|esta semana|próxima semana|proxima semana", texto_lower):
            slots["fecha_relativa"] = "pronto"

        # 3. Horario preferido
        if re.search(r"en la mañana|por la mañana|temprano", texto_lower):
            slots["horario"] = "mañana"
        elif re.search(r"tarde|por la tarde|en la tarde", texto_lower):
            slots["horario"] = "tarde"

        # 4. Nombre de médico (Dr. / Dra.)
        medico_match = re.search(
            r"dr\.?\s+([a-záéíóúñ]+)|dra\.?\s+([a-záéíóúñ]+)", texto_lower
        )
        if medico_match:
            slots["medico"] = medico_match.group(1) or medico_match.group(2)

        return slots

    def analizar_mensaje(self, texto: str) -> Tuple[str, Dict]:
        """Analiza el mensaje y devuelve (intención, slots)."""
        return self.detectar_intent(texto), self.extraer_slots(texto)


# ==================== EJEMPLO DE USO ====================
if __name__ == "__main__":
    detector = IntentDetector()

    ejemplos = [
        "Quiero una cita con el cardiólogo para mañana en la tarde",
        "Ver mis citas agendadas",
        "Cancelar mi cita del viernes",
        "Necesito consulta de diabetes esta semana",
        "Hola, ¿cómo estás?",
    ]

    for texto in ejemplos:
        intent, slots = detector.analizar_mensaje(texto)
        print(f"Texto:  {texto}")
        print(f"Intent: {intent}")
        print(f"Slots:  {slots}")
        print("-" * 60)

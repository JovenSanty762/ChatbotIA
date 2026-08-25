"""
Manejador de Mensajes WhatsApp con BOTONES INTERACTIVOS
ChatBot de Agendamiento de Citas Médicas
"""
import logging

from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from bot_models import Paciente, Especialidad, Medico, Cita, SesionWhatsApp, FechaDisponible, Eps, MetricaAgendamiento, SlotDisponible
from datetime import datetime, date, timedelta, time
from typing import Dict, List, Optional, Tuple
from intent_detector import IntentDetector
import cups_referencia
import json
import re
import requests
from bot_config import get_settings

settings = get_settings()


class EstadoFlujo:
    """Estados del flujo conversacional"""
    INICIO = "inicio"
    VERIFICACION_CEDULA = "verificacion_cedula"
    REGISTRO_NOMBRES = "registro_nombres"
    REGISTRO_APELLIDOS = "registro_apellidos"
    REGISTRO_CELULAR = "registro_celular"
    REGISTRO_CORREO = "registro_correo"
    REGISTRO_EPS = "registro_eps"
    REGISTRO_EPS_MANUAL = "registro_eps_manual"
    CONFIRMAR_REGISTRO = "confirmar_registro"
    CONFIRMAR_IDENTIDAD = "confirmar_identidad"
    MENU_PRINCIPAL = "menu_principal"
    MENU_CITAS = "menu_citas"
    SELECCIONAR_ESPECIALIDAD = "seleccionar_especialidad"
    SELECCIONAR_TIPO_CITA = "seleccionar_tipo_cita"
    ESPERAR_DOC_ORDEN = "esperar_doc_orden"
    ESPERAR_DOC_AUTORIZACION = "esperar_doc_autorizacion"
    SELECCIONAR_FECHA = "seleccionar_fecha"
    SELECCIONAR_MEDICO = "seleccionar_medico"
    SELECCIONAR_TURNO = "seleccionar_turno"
    SELECCIONAR_HORA = "seleccionar_hora"
    CONFIRMAR_CITA = "confirmar_cita"
    VER_CITAS = "ver_citas"
    SELECCIONAR_CITA_CANCELAR = "seleccionar_cita_cancelar"
    MOSTRAR_ESPECIALIDAD = "mostrar_especialidad"
    MOSTRAR_IMAGEN = "mostrar_imagen"
    MOSTRAR_REHAB = "mostrar_rehab"
    MOSTRAR_LAB = "mostrar_lab"
    SELECCIONAR_MODO_AGENDAMIENTO = "seleccionar_modo_agendamiento"
    SATISFACCION = "satisfaccion"
    ENCUESTA_CALIFICAR = "encuesta_calificar"
    ENCUESTA_ESTRELLAS = "encuesta_estrellas"
    SELECCIONAR_PROCEDIMIENTO_ORL = "seleccionar_procedimiento_orl"
    SIN_MEDICO_DISPONIBLE = "sin_medico_disponible"
    MENU_FIN = "menu_fin"



class WhatsAppButtonsAPI:
    """API de WhatsApp para enviar mensajes con botones"""
    
    @staticmethod
    def enviar_mensaje_texto(telefono: str, mensaje: str) -> bool:
        """Envía mensaje de texto simple"""
        url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": mensaje}
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=20)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Error enviando mensaje: {e}")
            return False
    
    @staticmethod
    def enviar_botones(telefono: str, mensaje: str, botones: List[Dict]) -> bool:
        """
        Envía mensaje con botones interactivos (máximo 3 botones)
        
        Args:
            telefono: Número del destinatario
            mensaje: Texto del mensaje
            botones: Lista de diccionarios [{"id": "1", "title": "Opción 1"}, ...]
        """
        url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        
        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        
        # WhatsApp permite máximo 3 botones
        botones_limitados = botones[:3]
        
        data = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": mensaje},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": btn["id"],
                                "title": btn["title"][:20]  # Máximo 20 caracteres
                            }
                        }
                        for btn in botones_limitados
                    ]
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=20)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Error enviando botones: {e}")
            return False
    
    @staticmethod
    def enviar_lista(telefono: str, mensaje: str, titulo_boton: str, secciones: List[Dict]) -> bool:
        """
        Envía mensaje con lista interactiva (hasta 10 opciones por sección)
        
        Args:
            telefono: Número del destinatario
            mensaje: Texto del mensaje
            titulo_boton: Texto del botón que abre la lista
            secciones: Lista de secciones con opciones
                [{"title": "Sección 1", "rows": [{"id": "1", "title": "Opción", "description": "Desc"}]}]
        """
        url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"

        headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }

        # WhatsApp exige límites de longitud; si se exceden, la API responde 400.
        # Recortamos defensivamente: sección ≤24, título de fila ≤24, descripción ≤72.
        secciones_ok = []
        for sec in secciones:
            filas = []
            for row in sec.get("rows", []):
                fila = {"id": str(row.get("id", ""))[:200], "title": str(row.get("title", ""))[:24]}
                if row.get("description"):
                    fila["description"] = str(row["description"])[:72]
                filas.append(fila)
            secciones_ok.append({"title": str(sec.get("title", ""))[:24], "rows": filas})

        data = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": mensaje[:1024]},
                "action": {
                    "button": titulo_boton[:20],
                    "sections": secciones_ok
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=20)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"Error enviando lista: {e}")
            return False


class ChatBotHandler:
    """Manejador principal del ChatBot con botones"""

    # Cantidad de horarios mostrados por página (selección por número de texto)
    HORARIOS_POR_PAGINA = 8

    def __init__(self, db: Session):
        self.db = db
        self.api = WhatsAppButtonsAPI()
    
    def procesar_mensaje(self, telefono: str, mensaje: str = None, button_id: str = None) -> None:
        """
        Procesa mensajes con verificación de identidad obligatoria.
        Ningún usuario puede acceder al menú ni a funciones sin haber
        verificado su cédula primero.
        """
        sesion = self.obtener_sesion(telefono)
        sesion.ultimo_mensaje = datetime.now()
        self.db.commit()

        # Marca de apertura del chat para medir el tiempo de agendamiento.
        # Se fija si falta (así se recupera si datos_temp se limpió en algún paso).
        if not self.obtener_dato_temporal(sesion, 'inicio_ts'):
            self.guardar_dato_temporal(sesion, 'inicio_ts', datetime.now().isoformat())

        estado = sesion.estado_flujo
        print(f"📊 [ESTADO] Tel: {telefono} | Estado: {estado} | Msg: {repr(mensaje)} | Btn: {button_id}")

        # ── Estados permitidos ANTES de identificarse ─────────────────────
        ESTADOS_PREVIOS_A_VERIFICACION = {
            EstadoFlujo.INICIO,
            EstadoFlujo.VERIFICACION_CEDULA,
            EstadoFlujo.CONFIRMAR_IDENTIDAD,
            EstadoFlujo.REGISTRO_NOMBRES,
            EstadoFlujo.REGISTRO_CELULAR,
            EstadoFlujo.REGISTRO_CORREO,
            EstadoFlujo.REGISTRO_EPS,
            EstadoFlujo.REGISTRO_EPS_MANUAL,
            EstadoFlujo.CONFIRMAR_REGISTRO,
        }

        # ── GUARDIA OBLIGATORIA ───────────────────────────────────────────
        # Si el usuario no está identificado (sin id_paciente) y su estado
        # actual no pertenece al flujo de verificación, lo forzamos al inicio.
        if not sesion.id_paciente and estado not in ESTADOS_PREVIOS_A_VERIFICACION:
            self.estado_inicio(telefono, sesion)
            return

        # ── FLUJO DE VERIFICACIÓN / REGISTRO ─────────────────────────────
        if estado == EstadoFlujo.INICIO:
            self.estado_inicio(telefono, sesion)
            return

        if estado == EstadoFlujo.VERIFICACION_CEDULA:
            self.estado_verificacion_cedula(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.REGISTRO_NOMBRES:
            self.estado_registro_nombres(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.REGISTRO_CELULAR:
            self.estado_registro_celular(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.REGISTRO_CORREO:
            self.estado_registro_correo(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.REGISTRO_EPS:
            self.estado_registro_eps(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.REGISTRO_EPS_MANUAL:
            self.estado_registro_eps_manual(telefono, sesion, mensaje)
            return

        if estado == EstadoFlujo.CONFIRMAR_REGISTRO:
            self.estado_confirmar_registro(telefono, sesion, button_id)
            return

        if estado == EstadoFlujo.CONFIRMAR_IDENTIDAD:
            self.estado_confirmar_identidad(telefono, sesion, button_id)
            return

        # ── A PARTIR DE AQUÍ: identidad verificada garantizada ───────────

        # ── Palabra clave "cancelar" → menú de fin (volver / terminar) ──────
        if mensaje and mensaje.strip().lower() == "cancelar" and not button_id:
            if estado not in {EstadoFlujo.INICIO, EstadoFlujo.MENU_PRINCIPAL, EstadoFlujo.MENU_FIN}:
                self.mostrar_menu_fin(
                    telefono, sesion,
                    mensaje_intro="↩️ Solicitud cancelada."
                )
                return

        # Texto libre → procesar con IA antes del flujo de botones.
        # (No cuando se espera una foto de documento: en esos estados el texto
        #  no debe reinterpretarse como una nueva solicitud.)
        _estados_esperando_foto = {EstadoFlujo.ESPERAR_DOC_ORDEN, EstadoFlujo.ESPERAR_DOC_AUTORIZACION}
        if mensaje and len(mensaje.strip()) > 3 and not button_id and estado not in _estados_esperando_foto:
            try:
                detector = IntentDetector()
                intent, slots = detector.analizar_mensaje(mensaje)
                print(f"🤖 IA → Intent: {intent} | Slots: {slots}")

                if intent == "agendar_cita":
                    self.procesar_agendamiento_inteligente(telefono, sesion, mensaje, slots)
                    return
                elif intent == "ver_citas":
                    self.mostrar_citas_agendadas(telefono, sesion)
                    return
                elif intent == "cancelar_cita":
                    self.iniciar_cancelacion(telefono, sesion)
                    return
            except Exception as e:
                print(f"⚠️ Error en IA: {e}")

        # ── Flujo tradicional de botones ──────────────────────────────────
        if estado == EstadoFlujo.MENU_PRINCIPAL:
            self.estado_menu_principal(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SELECCIONAR_ESPECIALIDAD:
            self.estado_seleccionar_especialidad(telefono, sesion, button_id, mensaje)
        elif estado == EstadoFlujo.SELECCIONAR_TIPO_CITA:
            self.estado_tipo_cita(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SELECCIONAR_PROCEDIMIENTO_ORL:
            self.estado_procedimiento_orl(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SIN_MEDICO_DISPONIBLE:
            self.estado_sin_medico_disponible(telefono, sesion, button_id)
        elif estado in (EstadoFlujo.ESPERAR_DOC_ORDEN, EstadoFlujo.ESPERAR_DOC_AUTORIZACION):
            # Opción de continuar sin autorización (solo si la EPS lo permite).
            if (estado == EstadoFlujo.ESPERAR_DOC_AUTORIZACION and button_id == "auth_omitir"
                    and self._eps_autorizacion_opcional(sesion)):
                self.guardar_dato_temporal(sesion, 'autorizacion_omitida', True)
                self.api.enviar_mensaje_texto(telefono, "➡️ De acuerdo, continuamos *sin autorización*.")
                self.iniciar_precita(telefono, sesion)
            else:
                # Se espera una FOTO o PDF; si envían texto se les recuerda.
                self.api.enviar_mensaje_texto(
                    telefono, "📎 Por favor envía una *foto* o un *PDF* del documento solicitado."
                )
        elif estado in (EstadoFlujo.SELECCIONAR_MODO_AGENDAMIENTO,
                        EstadoFlujo.SELECCIONAR_TURNO):
            # Estados de un flujo anterior (elegir modo/jornada). Ya no existen:
            # se redirige al nuevo flujo — elegir médico como primer paso.
            self.mostrar_medicos_especialidad(telefono, sesion)
        elif estado == EstadoFlujo.MENU_CITAS:
            self.estado_menu_citas(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SELECCIONAR_FECHA:
            self.estado_seleccionar_fecha(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SELECCIONAR_MEDICO:
            self.estado_seleccionar_medico_especialidad(telefono, sesion, button_id)
        elif estado == EstadoFlujo.SELECCIONAR_HORA:
            self.estado_seleccionar_hora(telefono, sesion, button_id, mensaje)
        elif estado == EstadoFlujo.CONFIRMAR_CITA:
            self.estado_confirmar_cita(telefono, sesion, button_id)
        elif estado == EstadoFlujo.VER_CITAS:
            # Estado legado — redirige al menú
            self.mostrar_menu_principal(telefono, sesion)
        elif estado == EstadoFlujo.SELECCIONAR_CITA_CANCELAR:
            self.estado_seleccionar_cita_cancelar(telefono, sesion, button_id, mensaje)
        elif estado == EstadoFlujo.SATISFACCION:
            self.estado_satisfaccion(telefono, sesion, button_id)
        elif estado == EstadoFlujo.ENCUESTA_CALIFICAR:
            # Estado antiguo (paso "¿deseas calificar?" ya eliminado); si una
            # sesión abierta se quedó ahí, saltamos directo a las estrellas.
            self.mostrar_estrellas(telefono, sesion)
        elif estado == EstadoFlujo.ENCUESTA_ESTRELLAS:
            self.estado_encuesta_estrellas(telefono, sesion, button_id)
        elif estado == EstadoFlujo.MENU_FIN:
            self.estado_menu_fin(telefono, sesion, button_id)
        else:
            # Cualquier estado desconocido con sesión verificada → menú
            self.mostrar_menu_principal(telefono, sesion)
        
    def obtener_sesion(self, telefono: str) -> SesionWhatsApp:
        """Obtiene o crea sesión y verifica timeout de inactividad"""
        sesion = self.db.query(SesionWhatsApp).filter(
            SesionWhatsApp.telefono == telefono,
            SesionWhatsApp.activo == True
        ).first()

        if not sesion:
            sesion = SesionWhatsApp(
                telefono=telefono,
                estado_flujo=EstadoFlujo.INICIO,
                datos_temp="{}",
                activo=True
            )
            self.db.add(sesion)
            self.db.commit()
            self.db.refresh(sesion)

        # Verificar timeout de inactividad
        if sesion.ultimo_mensaje:
            minutos_inactivo = (datetime.now() - sesion.ultimo_mensaje).total_seconds() / 60

            if minutos_inactivo > settings.SESSION_TIMEOUT_MINUTES:
                print(f"⏰ Sesión de {telefono} expirada por inactividad ({minutos_inactivo:.1f} min)")
                self.resetear_sesion(sesion, f"inactividad ({minutos_inactivo:.1f} minutos)")

        # Evitar reset innecesario durante registro
        if sesion.estado_flujo in [EstadoFlujo.REGISTRO_NOMBRES, 
                                   EstadoFlujo.REGISTRO_CELULAR, 
                                   EstadoFlujo.REGISTRO_CORREO]:
            return sesion

        return sesion
    
    def resetear_sesion(self, sesion: SesionWhatsApp, motivo: str = "manual") -> None:
        """Resetea una sola sesión"""
        sesion.estado_flujo = EstadoFlujo.INICIO
        sesion.datos_temp = "{}"
        sesion.id_paciente = None
        self.db.commit()
        print(f"🔄 Sesión de {sesion.telefono} reseteada por: {motivo}")

    def expirar_sesion_inactiva(self, sesion: SesionWhatsApp) -> None:
        """Notifica al usuario y resetea su sesión por inactividad."""
        # Solo notificar si el usuario ya se había identificado (estaba en medio de algo)
        if sesion.id_paciente and sesion.estado_flujo != EstadoFlujo.INICIO:
            self.api.enviar_mensaje_texto(
                sesion.telefono,
                f"⏰ Tu sesión ha expirado por inactividad ({settings.SESSION_TIMEOUT_MINUTES} minutos).\n\n"
                f"Cuando quieras continuar, escríbenos y te pediremos tu cédula nuevamente.\n\n"
                f"🏥 {settings.HOSPITAL_NOMBRE}"
            )
        self.resetear_sesion(sesion, f"inactividad > {settings.SESSION_TIMEOUT_MINUTES} min")
    
    
    def guardar_dato_temporal(self, sesion: SesionWhatsApp, clave: str, valor) -> None:
        """Guarda dato en datos_temp de la sesión"""
        datos = json.loads(sesion.datos_temp or "{}")
        datos[clave] = valor
        sesion.datos_temp = json.dumps(datos)
        self.db.commit()
    
    def obtener_dato_temporal(self, sesion: SesionWhatsApp, clave: str):
        """Obtiene dato de datos_temp"""
        datos = json.loads(sesion.datos_temp or "{}")
        return datos.get(clave)
    
    def resetear_todas_las_sesiones(self) -> None:
        """Resetea TODAS las sesiones activas al reiniciar el bot"""
        try:
            sesiones_activas = self.db.query(SesionWhatsApp).filter(
                SesionWhatsApp.activo == True
            ).all()
            
            count = 0
            for sesion in sesiones_activas:
                sesion.estado_flujo = EstadoFlujo.INICIO
                sesion.datos_temp = "{}"
                sesion.id_paciente = None
                # Opcional: sesion.activo = False  # Si quieres cerrar las sesiones anteriores
                count += 1
            
            self.db.commit()
            print(f"🔄 [RESET GLOBAL] Se han reiniciado {count} sesiones activas al iniciar el bot.")
            logging.info(f"Reset global de sesiones al iniciar bot: {count} sesiones afectadas")
            
        except Exception as e:
            print(f"❌ Error al resetear todas las sesiones: {e}")
            logging.error(f"Error reset global sesiones: {e}")
    
    # ======================================== ESTADOS DE FLUJO ==================================================

    # ── Helpers de teléfono ──────────────────────────────────────────────────

    @staticmethod
    def _normalizar_telefono(telefono: str) -> str:
        """
        Normaliza un número de teléfono para comparación:
        quita todo lo que no sea dígito y devuelve los últimos 10 dígitos
        (número local sin código de país). Cubre formatos como:
          573001234567 → 3001234567
          +57 300 123 4567 → 3001234567
          3001234567 → 3001234567
        """
        digitos = ''.join(c for c in telefono if c.isdigit())
        return digitos[-10:] if len(digitos) >= 10 else digitos

    def _buscar_paciente_por_telefono(self, telefono_local: str) -> Optional[Paciente]:
        """
        Busca un paciente cuyo campo `celular` coincida con los últimos
        10 dígitos del número de WhatsApp que inicia el chat.
        La comparación normaliza ambos lados para cubrir distintos formatos
        de almacenamiento (con/sin prefijo, con/sin espacios).
        Retorna el primer Paciente que coincida, o None.
        """
        pacientes = self.db.query(Paciente).filter(
            Paciente.celular.isnot(None)
        ).all()
        for p in pacientes:
            cel_digitos = ''.join(c for c in p.celular if c.isdigit())
            cel_local = cel_digitos[-10:] if len(cel_digitos) >= 10 else cel_digitos
            if cel_local == telefono_local:
                return p
        return None

    def estado_inicio(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Estado inicial.
        1) Normaliza el número de WhatsApp y lo busca en la BD por celular.
        2) Si hay coincidencia → muestra los datos del paciente y pide confirmación.
        3) Si no hay coincidencia → saludo + solicitud de cédula (flujo original).
        """
        telefono_local = self._normalizar_telefono(telefono)
        paciente_encontrado = self._buscar_paciente_por_telefono(telefono_local)

        aviso_ley = (
            f"📋 _Al continuar, aceptas el tratamiento de tus datos personales "
            f"conforme a la *Ley 1581 de 2012* de Protección de Datos Personales "
            f"de la República de Colombia. Tu información será usada exclusivamente "
            f"para gestionar tus citas médicas._"
        )

        if paciente_encontrado:
            # ── Paciente identificado por número de teléfono ──────────────────
            sesion.id_paciente = paciente_encontrado.id_paciente
            self.db.commit()
            print(f"📱 [AUTO-ID] Tel {telefono} → Paciente #{paciente_encontrado.id_paciente} "
                  f"({paciente_encontrado.nombres} {paciente_encontrado.apellidos})")

            mensaje = (
                f"🏥 *Bienvenido a {settings.HOSPITAL_NOMBRE}*\n\n"
                f"{aviso_ley}\n\n"
                f"📱 *Identificamos tu número de teléfono en nuestro sistema:*\n\n"
                f"👤 {paciente_encontrado.nombres} {paciente_encontrado.apellidos}\n"
                f"🆔 Cédula: {paciente_encontrado.cedula}\n"
                f"📱 Celular: {paciente_encontrado.celular}\n\n"
                f"¿Eres tú?"
            )
            botones = [
                {"id": "identidad_si", "title": "✅ Sí, soy yo"},
                {"id": "identidad_no", "title": "🔄 No, otra cédula"},
            ]
            self.api.enviar_botones(telefono, mensaje, botones)
            sesion.estado_flujo = EstadoFlujo.CONFIRMAR_IDENTIDAD
            self.db.commit()

        else:
            # ── No encontrado → flujo original: pedir cédula ─────────────────
            mensaje = (
                f"🏥 *Bienvenido a {settings.HOSPITAL_NOMBRE}*\n\n"
                f"Soy tu asistente virtual para agendamiento de citas médicas.\n\n"
                f"{aviso_ley}\n\n"
                f"Para comenzar, por favor ingresa tu número de *cédula*:"
            )
            self.api.enviar_mensaje_texto(telefono, mensaje)
            sesion.estado_flujo = EstadoFlujo.VERIFICACION_CEDULA
            self.db.commit()
    
    def procesar_imagen(self, telefono: str, image_id: str) -> None:
        """Compatibilidad: una imagen es un medio con mime image/jpeg."""
        self.procesar_media(telefono, image_id, "image/jpeg")

    def procesar_media(self, telefono: str, media_id: str, mime_type: str = "image/jpeg") -> None:
        """Procesa un medio (foto o PDF) enviado por el usuario usando OCR."""
        sesion = self.obtener_sesion(telefono)
        sesion.ultimo_mensaje = datetime.now()
        self.db.commit()

        # Marca de apertura del chat para medir el tiempo de agendamiento (si falta).
        if not self.obtener_dato_temporal(sesion, 'inicio_ts'):
            self.guardar_dato_temporal(sesion, 'inicio_ts', datetime.now().isoformat())

        estado = sesion.estado_flujo
        print(f"🖼️  Medio recibido | Tel: {telefono} | Estado: {estado} | mime: {mime_type}")

        # Documentos requeridos para agendar (foto o PDF)
        if estado == EstadoFlujo.ESPERAR_DOC_ORDEN:
            self._recibir_documento(telefono, sesion, media_id, 'orden', mime_type)
            return
        if estado == EstadoFlujo.ESPERAR_DOC_AUTORIZACION:
            self._recibir_documento(telefono, sesion, media_id, 'autorizacion', mime_type)
            return

        if estado != EstadoFlujo.VERIFICACION_CEDULA:
            self.api.enviar_mensaje_texto(
                telefono,
                "📎 Recibí tu archivo, pero en este momento solo proceso texto.\n\n"
                "Por favor escribe tu respuesta."
            )
            return

        self.api.enviar_mensaje_texto(telefono, "🔍 Procesando tu documento, un momento...")

        try:
            from ocr_processor import ProcesadorOCR
            ocr = ProcesadorOCR()
            exito, cedula = ocr.procesar_imagen_cedula(media_id, mime_type)

            if not exito:
                self.api.enviar_mensaje_texto(
                    telefono,
                    "❌ No pude descargar la imagen.\n\nPor favor escribe tu número de cédula directamente."
                )
                return

            if cedula:
                self.api.enviar_mensaje_texto(
                    telefono,
                    f"📄 Número detectado en la imagen: *{cedula}*\nVerificando..."
                )
                self.estado_verificacion_cedula(telefono, sesion, cedula)
            else:
                self.api.enviar_mensaje_texto(
                    telefono,
                    "❌ No pude leer el número de cédula en la imagen.\n\n"
                    "Asegúrate de que la foto sea nítida y el número esté visible.\n"
                    "También puedes escribir tu cédula directamente."
                )
        except ImportError:
            self.api.enviar_mensaje_texto(
                telefono,
                "⚠️ El procesamiento de imágenes no está disponible.\n\n"
                "Por favor escribe tu número de cédula."
            )
        except Exception as e:
            print(f"❌ Error en OCR: {e}")
            self.api.enviar_mensaje_texto(
                telefono,
                "❌ Error al procesar la imagen.\n\nPor favor escribe tu número de cédula."
            )

    def estado_verificacion_cedula(self, telefono: str, sesion: SesionWhatsApp, cedula: str) -> None:
        """Verifica si la cédula existe en la base de datos"""
        if not cedula or not cedula.strip().isdigit():
            self.api.enviar_mensaje_texto(telefono, "❌ Por favor ingresa solo números para tu cédula.")
            return
        
        cedula = cedula.strip()
        
        # Buscar paciente en BD
        paciente = self.db.query(Paciente).filter(Paciente.cedula == cedula).first()
        
        self.guardar_dato_temporal(sesion, 'cedula', cedula)
        
        if paciente:
            # PACIENTE ENCONTRADO — pedir confirmación de identidad
            sesion.id_paciente = paciente.id_paciente
            self.db.commit()

            mensaje = (
                f"🔍 *Encontramos este registro:*\n\n"
                f"👤 Nombre: {paciente.nombres} {paciente.apellidos}\n"
                f"🆔 Cédula: {paciente.cedula}\n"
                f"📱 Celular: {paciente.celular}\n"
                f"📧 Correo: {paciente.correo or 'No registrado'}\n\n"
                f"¿Eres tú?"
            )
            botones = [
                {"id": "identidad_si", "title": "✅ Sí, soy yo"},
                {"id": "identidad_no", "title": "❌ No, otra cédula"},
            ]
            self.api.enviar_botones(telefono, mensaje, botones)
            sesion.estado_flujo = EstadoFlujo.CONFIRMAR_IDENTIDAD
            self.db.commit()
        
        else:
            # PACIENTE NO ENCONTRADO - Iniciar registro
            self.guardar_dato_temporal(sesion, 'cedula', cedula)
            
            mensaje = (
                f"👤 No encontramos tu cédula en nuestro sistema.\n\n"
                f"Vamos a registrarte. Es rápido y sencillo.\n\n"
                f"Por favor, ingresa tu *Nombre Completo*:"
            )
            
            self.api.enviar_mensaje_texto(telefono, mensaje)
            sesion.estado_flujo = EstadoFlujo.REGISTRO_NOMBRES
            self.db.commit()

    def estado_confirmar_identidad(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """
        Procesa la confirmación de identidad.
        Puede llegar aquí desde dos rutas:
          a) El usuario ingresó su cédula y fue encontrado en la BD.
          b) El número de WhatsApp fue identificado automáticamente en la BD.
        En ambos casos los botones son los mismos: confirmar o cambiar cédula.
        """
        if button_id == "identidad_si":
            paciente = self.db.query(Paciente).get(sesion.id_paciente)
            self.api.enviar_mensaje_texto(
                telefono,
                f"✅ *¡Bienvenido, {paciente.nombres}!*\n\n"
                f"¿En qué te puedo ayudar hoy?"
            )
            self.mostrar_menu_principal(telefono, sesion)

        elif button_id == "identidad_no":
            # Limpiar identidad y pedir que ingrese otra cédula
            sesion.id_paciente = None
            sesion.datos_temp = "{}"
            sesion.estado_flujo = EstadoFlujo.VERIFICACION_CEDULA
            self.db.commit()
            self.api.enviar_mensaje_texto(
                telefono,
                "De acuerdo. Por favor ingresa el número de *cédula* de la persona que va a atenderse:"
            )

        else:
            # Botón desconocido: volver a mostrar la confirmación
            if sesion.id_paciente:
                paciente = self.db.query(Paciente).get(sesion.id_paciente)
                if paciente:
                    mensaje = (
                        f"🔍 *Confirma tu identidad:*\n\n"
                        f"👤 {paciente.nombres} {paciente.apellidos}\n"
                        f"🆔 {paciente.cedula}\n\n¿Eres tú?"
                    )
                    botones = [
                        {"id": "identidad_si", "title": "✅ Sí, soy yo"},
                        {"id": "identidad_no", "title": "🔄 No, otra cédula"},
                    ]
                    self.api.enviar_botones(telefono, mensaje, botones)
            else:
                # Sin paciente en sesión: pedir cédula
                sesion.estado_flujo = EstadoFlujo.VERIFICACION_CEDULA
                self.db.commit()
                self.api.enviar_mensaje_texto(
                    telefono,
                    "Por favor ingresa tu número de *cédula*:"
                )

    def estado_registro_nombres(self, telefono: str, sesion: SesionWhatsApp, nombre_completo: str) -> None:
        """Registro unificado: Captura Nombre Completo y lo divide en Nombres y Apellidos"""
        if not nombre_completo or len(nombre_completo.strip()) < 3:
            self.api.enviar_mensaje_texto(telefono, "❌ Por favor ingresa tu nombre completo (nombres y apellidos).")
            return
        else:
            nombre_completo = nombre_completo.strip()
        
            # Dividir nombre completo
            partes = nombre_completo.strip().split(maxsplit=1)
            nombres = partes[0]
            apellidos = partes[1] if len(partes) > 1 else ""
        
            #Guardar los nombres y apellidos por separado en datos temporales
            self.guardar_dato_temporal(sesion, 'nombres', nombres.strip())
            self.guardar_dato_temporal(sesion, 'apellidos', apellidos.strip())

            self.api.enviar_mensaje_texto(
                telefono, 
                f"✅ Perfecto.\n\n Registrado {nombre_completo}\n\nAhora ingresa tu número de *CELULAR*:"
            )
        
            sesion.estado_flujo = EstadoFlujo.REGISTRO_CELULAR
            self.db.commit()
            
            print(f"✅ Registro nombres completado para {telefono}")
            
    #    except Exception as e:
    #        print(f"❌ Error en registro de nombre: {e}")
    #        self.api.enviar_mensaje_texto(telefono, "❌ Ocurrió un error. Inténtalo de nuevo.")
    
    #def estado_registro_apellidos(self, telefono: str, sesion: SesionWhatsApp, apellidos: str) -> None:
    #    """Registro: Captura apellidos"""
    #    if not apellidos or len(apellidos.strip()) < 2:
    #        self.api.enviar_mensaje_texto(telefono, "❌ Por favor ingresa tus apellidos completos.")
    #        return
    #    
    #    self.guardar_dato_temporal(sesion, 'apellidos', apellidos.strip())
    #    self.api.enviar_mensaje_texto(telefono, "Excelente ✅\n\nAhora ingresa tu número de *CELULAR*:")
    #    
    #    sesion.estado_flujo = EstadoFlujo.REGISTRO_CELULAR
    #    self.db.commit()
    
    def estado_registro_celular(self, telefono: str, sesion: SesionWhatsApp, celular: str) -> None:
        """Registro: Captura celular"""
        if not celular or not celular.strip().replace('+', '').replace(' ', '').isdigit():
            self.api.enviar_mensaje_texto(telefono, "❌ Por favor ingresa un número de celular válido.")
            return
        
        self.guardar_dato_temporal(sesion, 'celular', celular.strip())
        self.api.enviar_mensaje_texto(
            telefono,
            f"Muy bien ✅\n\n Registrado el numero de celular {celular}\n\nFinalmente, ingresa tu *CORREO ELECTRÓNICO* (o escribe 'no' si no tienes):"
        )
        
        sesion.estado_flujo = EstadoFlujo.REGISTRO_CORREO
        self.db.commit()
    
    def estado_registro_correo(self, telefono: str, sesion: SesionWhatsApp, correo: str) -> None:
        """Registro: Captura correo"""
        correo = correo.strip() if correo else ""
        
        if correo.lower() in ['no', 'no tengo', 'ninguno']:
            correo = None
        elif '@' not in correo:
            self.api.enviar_mensaje_texto(
                telefono,
                "❌ Correo inválido. Por favor ingresa un correo válido o escribe 'no'."
            )
            return
        
        self.guardar_dato_temporal(sesion, 'correo', correo)

        # Tras el correo se pide la EPS a la que está afiliado el paciente.
        self.mostrar_eps_registro(telefono, sesion)

    def mostrar_eps_registro(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Muestra la lista de EPS activas (numerada) para que el paciente elija la suya."""
        eps_list = self.db.query(Eps).filter(Eps.activo == True).order_by(Eps.nombre).all()

        if not eps_list:
            # Sin EPS configuradas: se omite el paso y se pasa a confirmar.
            self.mostrar_confirmacion_registro(telefono, sesion)
            return

        mensaje = "🏥 *¿A qué EPS estás afiliado?*\n\n"
        mensaje += "Responde con el *número* de tu EPS:\n\n"
        eps_dict = {}
        for i, e in enumerate(eps_list, 1):
            mensaje += f"{i}. {e.nombre}\n"
            eps_dict[str(i)] = {"id": e.id_eps, "nombre": e.nombre}

        # Opción para escribir la EPS cuando no está en la lista.
        n_otra = len(eps_list) + 1
        mensaje += f"\n{n_otra}. ➕ Otra (mi EPS no está en la lista)"
        eps_dict[str(n_otra)] = {"otra": True}

        self.api.enviar_mensaje_texto(telefono, mensaje)
        self.guardar_dato_temporal(sesion, 'eps_registro_dict', eps_dict)
        sesion.estado_flujo = EstadoFlujo.REGISTRO_EPS
        self.db.commit()

    def estado_registro_eps(self, telefono: str, sesion: SesionWhatsApp, mensaje: str) -> None:
        """Procesa la EPS elegida por número y pasa a la confirmación."""
        eps_dict = self.obtener_dato_temporal(sesion, 'eps_registro_dict')
        if not eps_dict:
            self.mostrar_eps_registro(telefono, sesion)
            return

        numero = (mensaje or "").strip()
        if not numero.isdigit() or numero not in eps_dict:
            self.api.enviar_mensaje_texto(
                telefono, "❌ Responde con el *número* de tu EPS de la lista enviada."
            )
            return

        data = eps_dict[numero]

        # "➕ Otra": el usuario escribirá el nombre de su EPS.
        if data.get("otra"):
            self.api.enviar_mensaje_texto(
                telefono, "✍️ Escribe el *nombre de tu EPS* tal como aparece en tu carné:"
            )
            sesion.estado_flujo = EstadoFlujo.REGISTRO_EPS_MANUAL
            self.db.commit()
            return

        self.guardar_dato_temporal(sesion, 'id_eps_registro', data["id"])
        self.guardar_dato_temporal(sesion, 'nombre_eps_registro', data["nombre"])
        self.api.enviar_mensaje_texto(telefono, f"✅ EPS: *{data['nombre']}*")
        self.mostrar_confirmacion_registro(telefono, sesion)

    def estado_registro_eps_manual(self, telefono: str, sesion: SesionWhatsApp, nombre: str) -> None:
        """
        Registra la EPS escrita por el usuario cuando no está en la lista.
        Si ya existe una con ese nombre (sin distinguir mayúsculas), se reutiliza;
        si no, se crea con requisitos por defecto (orden + autorización) para que
        el personal la ajuste luego en el panel.
        """
        nombre = (nombre or "").strip()
        if len(nombre) < 2:
            self.api.enviar_mensaje_texto(
                telefono, "❌ Escribe el nombre de tu EPS (al menos 2 caracteres)."
            )
            return

        existente = self.db.query(Eps).filter(func.lower(Eps.nombre) == nombre.lower()).first()
        if existente:
            eps = existente
            # Si estaba inactiva, se reactiva para poder asociarla.
            if not eps.activo:
                eps.activo = True
                self.db.commit()
        else:
            eps = Eps(nombre=nombre, requiere_orden=True, requiere_autorizacion=True, activo=True)
            self.db.add(eps)
            self.db.commit()
            self.db.refresh(eps)
            print(f"➕ Nueva EPS registrada desde el chat: {nombre} (#{eps.id_eps})")

        self.guardar_dato_temporal(sesion, 'id_eps_registro', eps.id_eps)
        self.guardar_dato_temporal(sesion, 'nombre_eps_registro', eps.nombre)
        self.api.enviar_mensaje_texto(telefono, f"✅ EPS: *{eps.nombre}*")
        self.mostrar_confirmacion_registro(telefono, sesion)

    def mostrar_confirmacion_registro(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Resumen de datos del registro (incluida la EPS) para confirmar."""
        nombres = self.obtener_dato_temporal(sesion, 'nombres')
        apellidos = self.obtener_dato_temporal(sesion, 'apellidos')
        celular = self.obtener_dato_temporal(sesion, 'celular')
        cedula = self.obtener_dato_temporal(sesion, 'cedula')
        correo = self.obtener_dato_temporal(sesion, 'correo')
        eps_nombre = self.obtener_dato_temporal(sesion, 'nombre_eps_registro')

        mensaje = (
            f"📋 *Confirma tus datos:*\n\n"
            f"👤 Nombre: {nombres} {apellidos}\n"
            f"🆔 Cédula: {cedula}\n"
            f"📱 Celular: {celular}\n"
            f"📧 Correo: {correo or 'No proporcionado'}\n"
            f"🏥 EPS: {eps_nombre or 'No seleccionada'}\n\n"
            f"¿Los datos son correctos?"
        )
        botones = [
            {"id": "confirmar_si", "title": "✅ Sí, continuar"},
            {"id": "confirmar_no", "title": "❌ No, corregir"}
        ]
        self.api.enviar_botones(telefono, mensaje, botones)
        sesion.estado_flujo = EstadoFlujo.CONFIRMAR_REGISTRO
        self.db.commit()

    def estado_confirmar_registro(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Confirma y guarda el registro"""
        if button_id == "confirmar_si":
            # Asignar el MENOR id_paciente libre (rellena huecos dejados por
            # DELETEs antes de crecer). Delegado a la función SQL menor_id_libre.
            nuevo_id = int(self.db.execute(
                text("SELECT menor_id_libre('pacientes', 'id_paciente')")
            ).scalar() or 1)

            # Crear paciente
            paciente = Paciente(
                id_paciente=nuevo_id,
                cedula=self.obtener_dato_temporal(sesion, 'cedula'),
                nombres=self.obtener_dato_temporal(sesion, 'nombres'),
                apellidos=self.obtener_dato_temporal(sesion, 'apellidos'),
                celular=self.obtener_dato_temporal(sesion, 'celular'),
                correo=self.obtener_dato_temporal(sesion, 'correo'),
                id_eps=self.obtener_dato_temporal(sesion, 'id_eps_registro')
            )

            self.db.add(paciente)
            self.db.commit()
            self.db.refresh(paciente)

            # Mantener la secuencia alineada con el máximo actual
            self.db.execute(text(
                "SELECT setval(pg_get_serial_sequence('pacientes','id_paciente'), "
                "(SELECT COALESCE(MAX(id_paciente),0) FROM pacientes))"
            ))

            sesion.id_paciente = paciente.id_paciente
            self.db.commit()
            
            mensaje = (
                f"✅ *¡Registro exitoso!*\n\n"
                f"Bienvenido {paciente.nombres} {paciente.apellidos}\n\n"
                f"Ahora puedes agendar tus citas médicas."
            )
            
            self.api.enviar_mensaje_texto(telefono, mensaje)
            self.mostrar_menu_principal(telefono, sesion)
        
        else:
            # Reiniciar registro
            self.api.enviar_mensaje_texto(
                telefono,
                "De acuerdo, vamos a comenzar de nuevo.\n\nPor favor, ingresa tus *NOMBRES*:"
            )
            sesion.estado_flujo = EstadoFlujo.REGISTRO_NOMBRES
            self.db.commit()

# ======================================== PROCESAMIENTO CON IA ==================================================

    def procesar_agendamiento_inteligente(
        self, telefono: str, sesion: SesionWhatsApp, mensaje: str, slots: dict = None
    ) -> None:
        """
        Usa Claude para extraer especialidad, fecha y hora del texto libre del usuario
        y pre-rellena la sesión para saltar pasos del flujo tradicional.
        """
        try:
            # Cargar datos necesarios para el contexto de la IA
            especialidades_db = self.db.query(Especialidad).filter(
                Especialidad.activo == True
            ).order_by(Especialidad.nombre).all()

            fechas_db = self.db.query(FechaDisponible).filter(
                FechaDisponible.fecha >= date.today(),
                FechaDisponible.cupos_disponibles > 0,
            ).order_by(FechaDisponible.fecha).limit(20).all()

            especialidades = [
                {"id": e.id_especialidad, "nombre": e.nombre}
                for e in especialidades_db
            ]
            fechas = [
                {"id": f.id_fecha, "fecha": str(f.fecha)}
                for f in fechas_db
            ]

            # Llamar al proveedor de IA configurado para interpretar el mensaje
            from ai_processor import ProcesadorIA
            ia = ProcesadorIA()
            resultado = ia.analizar_solicitud_cita(mensaje, especialidades, fechas)

            print(f"🤖 Claude extrajo: {resultado}")

            if not resultado.get("es_solicitud_cita"):
                # No es una solicitud de cita → flujo normal por palabras clave
                self.procesar_con_ia(telefono, sesion, mensaje)
                return

            # ── Guardar tipo de servicio ──────────────────────────────────────
            self.guardar_dato_temporal(sesion, "tipo_servicio", "cita")

            # ── Especialidad extraída ─────────────────────────────────────────
            id_esp = resultado.get("id_especialidad")
            nombre_esp = resultado.get("nombre_especialidad")

            if id_esp:
                self.guardar_dato_temporal(sesion, "id_especialidad", id_esp)
                self.guardar_dato_temporal(sesion, "nombre_especialidad", nombre_esp or "")

            # ── Datos "pospuestos": fecha / hora / jornada / médico ─────────
            #
            # Aunque el paciente los mencione en el mensaje, NO se fijan como
            # elección final aquí — el hospital exige recibir la orden médica
            # (y la autorización) ANTES de agendar. Se guardan como temporales
            # con sufijo `_ia` para que `continuar_tras_documentos` los
            # aplique automáticamente en cuanto llegue la foto/PDF y así
            # saltar los pasos que ya se pueden resolver.
            fecha_sugerida = resultado.get("fecha_sugerida")
            if fecha_sugerida:
                self.guardar_dato_temporal(sesion, "fecha_ia", fecha_sugerida)

            hora_pref = resultado.get("hora_preferida")
            if hora_pref:
                self.guardar_dato_temporal(sesion, "hora_preferida_ia", hora_pref)

            jornada = resultado.get("jornada")
            if jornada in ("manana", "tarde"):
                self.guardar_dato_temporal(sesion, "turno_ia", jornada)

            nombre_medico_ia = resultado.get("nombre_medico")
            if nombre_medico_ia:
                self.guardar_dato_temporal(sesion, "nombre_medico_ia",
                                           nombre_medico_ia)

            # ── Confirmación de lo entendido ──────────────────────────────────
            resumen = ia.generar_resumen_extraccion(resultado)
            if resumen:
                self.api.enviar_mensaje_texto(
                    telefono,
                    f"✅ Entendí tu solicitud:\n{resumen}\n\nDéjame completar tu agendamiento…"
                )

            # ── Avanzar lo máximo posible hacia el resumen de confirmación ────
            # Auto-selecciona opciones únicas (única especialidad/fecha/jornada/
            # médico/horario) y, si el mensaje trae hora o médico, salta directo
            # al resumen.
            self.avanzar_agendamiento_inteligente(
                telefono, sesion,
                hora_pref=hora_pref,
                nombre_medico=nombre_medico_ia,
            )

        except Exception as e:
            print(f"⚠️ Error en agendamiento inteligente: {e}")
            # Fallback sin interrumpir al usuario
            self.estado_mostrar_especialidades(telefono, sesion, "cita")

    # ── Resolutor inteligente de agendamiento ────────────────────────────────

    def avanzar_agendamiento_inteligente(
        self, telefono: str, sesion: SesionWhatsApp,
        hora_pref: str = None, nombre_medico: str = None,
        fecha_pref: str = None, turno_pref: str = None,
    ) -> None:
        """
        Avanza el agendamiento hasta donde permita la información conocida.

        Los cuatro parámetros son opcionales — si no se pasan, se leen de los
        temporales `_ia` guardados por `procesar_agendamiento_inteligente`.
        Así, tras la carga de documentos, `continuar_tras_documentos` puede
        invocar esta función sin argumentos y todo se aplica solo.

        Orden en el que se consumen:
            1. Precita (tipo_cita + documentos) → si falta algo, entra al
               flujo `iniciar_precita` y se conservan los `_ia`.
            2. Médico: match `nombre_medico_ia` contra los activos de la
               especialidad → si es único, se fija.
            3. Fecha: si `fecha_ia` existe y está en las disponibles del
               médico → se fija; si no, se muestran las fechas.
            4. Hora: primero se filtra por `turno_ia` (mañana/tarde); si
               `hora_preferida_ia` cae dentro de las libres, se fija; si
               tras el filtro por turno queda una única opción, se toma.
            5. Con médico + fecha + hora → salto directo al resumen.
        """
        # ── 0. Reconstruir preferencias desde temporales _ia ────────────────
        hora_pref     = hora_pref     or self.obtener_dato_temporal(sesion, 'hora_preferida_ia')
        nombre_medico = nombre_medico or self.obtener_dato_temporal(sesion, 'nombre_medico_ia')
        fecha_pref    = fecha_pref    or self.obtener_dato_temporal(sesion, 'fecha_ia')
        turno_pref    = turno_pref    or self.obtener_dato_temporal(sesion, 'turno_ia')

        # ── 1. Especialidad ────────────────────────────────────────────────
        id_esp = self.obtener_dato_temporal(sesion, 'id_especialidad')
        if not id_esp:
            self.estado_mostrar_especialidades(telefono, sesion, "cita")
            return

        # ── 2. Precita (tipo_cita + documentos): tope máximo del texto ─────
        # Antes de pedir médico/fecha/hora el hospital exige la orden médica
        # (y la autorización de EPS que lo requiera). Se guarda origen='ia'
        # para que `continuar_tras_documentos` reanude aquí tras las fotos.
        if not self._precita_completa(sesion):
            self.guardar_dato_temporal(sesion, 'origen_flujo', 'ia')
            # Los temporales _ia ya están guardados por procesar_agendamiento_
            # inteligente; si el llamador nos pasó valores nuevos, los sobrescribe.
            if hora_pref:
                self.guardar_dato_temporal(sesion, 'hora_preferida_ia', hora_pref)
            if nombre_medico:
                self.guardar_dato_temporal(sesion, 'nombre_medico_ia', nombre_medico)
            if fecha_pref:
                self.guardar_dato_temporal(sesion, 'fecha_ia', fecha_pref)
            if turno_pref:
                self.guardar_dato_temporal(sesion, 'turno_ia', turno_pref)
            self.iniciar_precita(telefono, sesion)
            return

        # ── 3. Médico: aplicar preferencia _ia si coincide inequívocamente ─
        if not self.obtener_dato_temporal(sesion, 'id_medico') and nombre_medico:
            candidatos = self._medicos_de_especialidad(sesion)
            elegido = self._match_medico_por_nombre(candidatos, nombre_medico)
            if elegido:
                self.guardar_dato_temporal(sesion, 'id_medico', elegido.id_medico)
                self.guardar_dato_temporal(sesion, 'nombre_medico',
                                           f"{elegido.nombres} {elegido.apellidos}")

        if not self.obtener_dato_temporal(sesion, 'id_medico'):
            self.mostrar_medicos_especialidad(telefono, sesion)
            return

        # ── 4. Fecha: preferir la ya elegida; si no, aplicar `fecha_ia` ────
        fecha_str = self.obtener_dato_temporal(sesion, 'fecha_cita')
        if not fecha_str and fecha_pref:
            if self._fecha_disponible_para_medico(
                self.obtener_dato_temporal(sesion, 'id_medico'), fecha_pref
            ):
                self.guardar_dato_temporal(sesion, 'fecha_cita', fecha_pref)
                fecha_str = fecha_pref

        if not fecha_str:
            self.mostrar_fechas_disponibles(telefono, sesion)
            return
        fecha = date.fromisoformat(fecha_str)

        # ── 5. Hora: filtrar por `turno_ia`, aplicar `hora_preferida_ia` ───
        id_medico = self.obtener_dato_temporal(sesion, 'id_medico')
        opciones = self._opciones_horario_medico(id_medico, fecha)
        if not opciones:
            self.api.enviar_mensaje_texto(
                telefono, "❌ No hay horarios disponibles del médico para esa fecha."
            )
            self.mostrar_fechas_disponibles(telefono, sesion)
            return

        # Filtrar por turno si el paciente lo indicó (manana < 12:00 <= tarde).
        if turno_pref in ("manana", "tarde"):
            opciones_turno = [
                op for op in opciones
                if (turno_pref == "manana"
                    and datetime.strptime(op['h'], '%H:%M').time() < time(12, 0))
                or (turno_pref == "tarde"
                    and datetime.strptime(op['h'], '%H:%M').time() >= time(12, 0))
            ]
            # Solo se aplica el filtro si deja al menos 1 opción; si el turno
            # elegido no tiene cupos, no se descarta el médico — se muestra todo.
            if opciones_turno:
                opciones = opciones_turno

        seleccion = None
        if hora_pref:
            for op in opciones:
                if op['h'] == hora_pref:
                    seleccion = op
                    break
        if seleccion is None and len(opciones) == 1:
            seleccion = opciones[0]

        if seleccion:
            self._fijar_opcion_y_confirmar(telefono, sesion, seleccion)
        else:
            self.mostrar_horarios_medico(telefono, sesion)

    # ── Helper: ¿la fecha ISO está entre las disponibles del médico? ─────────
    def _fecha_disponible_para_medico(self, id_medico: int, fecha_iso: str) -> bool:
        """
        True si `fecha_iso` está entre las fechas disponibles del médico
        (usa `_opciones_horario_medico`, que ya filtra por horario activo y
        slots libres). Robusto contra fechas mal formateadas.
        """
        if not id_medico or not fecha_iso:
            return False
        try:
            f = date.fromisoformat(fecha_iso)
        except (ValueError, TypeError):
            return False
        if f < date.today():
            return False
        try:
            return bool(self._opciones_horario_medico(id_medico, f))
        except Exception:
            return False

    def _match_medico_por_nombre(
        self, candidatos: List['Medico'], nombre_medico: str
    ) -> Optional['Medico']:
        """
        Devuelve el Medico cuyo nombre coincide mejor con `nombre_medico` (por
        tokens de ≥3 caracteres). Si hay 1 solo candidato coincidente, se devuelve.
        None si no hay coincidencia inequívoca.
        """
        if not nombre_medico or not candidatos:
            return None
        objetivo = self._normalizar_texto(nombre_medico)
        tokens = [t for t in objetivo.split() if len(t) > 2]
        if not tokens:
            return None
        filtrados = [
            m for m in candidatos
            if any(t in self._normalizar_texto(f"{m.nombres} {m.apellidos}") for t in tokens)
        ]
        return filtrados[0] if len(filtrados) == 1 else None

    @staticmethod
    def _normalizar_texto(texto: str) -> str:
        """Minúsculas sin acentos, para comparar nombres de forma robusta."""
        import unicodedata
        t = unicodedata.normalize('NFKD', texto or '')
        t = ''.join(c for c in t if not unicodedata.combining(c))
        return t.lower().strip()

    def _fijar_opcion_y_confirmar(self, telefono: str, sesion: SesionWhatsApp, op: Dict) -> None:
        """Fija médico + hora de la opción elegida y muestra el resumen."""
        self.guardar_dato_temporal(sesion, 'id_medico', op['im'])
        self.guardar_dato_temporal(sesion, 'nombre_medico', op['nm'])
        self.guardar_dato_temporal(sesion, 'hora_cita', op['h'])
        h = datetime.strptime(op['h'], '%H:%M').time()
        self.guardar_dato_temporal(sesion, 'turno', 'manana' if h < time(12, 0) else 'tarde')
        self.mostrar_resumen_cita(telefono, sesion)

    def procesar_con_ia(self, telefono: str, sesion: SesionWhatsApp, mensaje: str):
        """Enrutador por palabras clave cuando Claude no identifica una cita."""
        detector = IntentDetector()
        intent, _ = detector.analizar_mensaje(mensaje)

        print(f"🔑 Keywords → Intent: {intent}")

        if intent == "ver_citas" or "mis citas" in mensaje.lower():
            self.mostrar_citas_agendadas(telefono, sesion)

        elif intent == "cancelar_cita":
            self.iniciar_cancelacion(telefono, sesion)

        elif any(w in mensaje.lower() for w in ["imagen", "radiografia", "rayos", "tomografia", "resonancia"]):
            self.estado_mostrar_imagen(telefono, sesion)

        elif any(w in mensaje.lower() for w in ["rehab", "rehabilitacion", "fisio", "terapia"]):
            self.estado_mostrar_rehab(telefono, sesion)

        else:
            self.api.enviar_mensaje_texto(
                telefono,
                "🏥 Puedo ayudarte a:\n\n"
                "• Agendar una cita médica\n"
                "• Ver mis citas agendadas\n"
                "• Cancelar una cita\n\n"
                "Escríbeme qué necesitas o usa los botones del menú."
            )
            self.mostrar_menu_principal(telefono, sesion)
            
# ======================================== MENU PRINCIPAL ==================================================
   
    def mostrar_menu_principal(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Menú principal después de verificación exitosa.

        Al entrar aquí se descartan los datos temporales del agendamiento en
        curso (tipo_cita, id_medico, id_medico_control, doc_orden, etc.) para
        que la próxima solicitud arranque limpia. Antes, si el usuario
        cancelaba a media cita, el `tipo_cita` guardado sobrevivía y el
        siguiente intento saltaba el menú de "primera vez / control".
        Se conserva `id_metrica` porque puede pertenecer a una cita ya
        agendada cuya encuesta aún está pendiente.
        """
        self._limpiar_temporales_agendamiento(sesion)

        mensaje = (
            "🏥 Selecciona una opción o escríbe directamente lo que necesitas.\n\n"
            "Por ejemplo: _\"Quiero una cita con cardiología para el viernes\"_"
        )

        botones = [
            {"id": "menu_agendar", "title": "📅 Agendar cita"},
            {"id": "menu_ver",     "title": "📋 Ver mis citas"},
        ]

        self.api.enviar_botones(telefono, mensaje, botones)
        sesion.estado_flujo = EstadoFlujo.MENU_PRINCIPAL
        self.db.commit()

    def _limpiar_temporales_agendamiento(self, sesion: SesionWhatsApp) -> None:
        """
        Descarta todos los datos temporales del flujo de agendamiento actual y
        conserva solo `id_metrica` — la referencia a la métrica de una cita ya
        creada cuya encuesta de satisfacción aún puede estar pendiente.
        """
        id_metrica = self.obtener_dato_temporal(sesion, 'id_metrica')
        if id_metrica:
            sesion.datos_temp = json.dumps({'id_metrica': id_metrica}, ensure_ascii=False)
        else:
            sesion.datos_temp = "{}"

    def estado_menu_principal(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Procesa selección del menú principal"""
        if button_id == "menu_agendar":
            self.mostrar_tipo_servicio(telefono, sesion)
        elif button_id == "menu_ver":
            self.mostrar_citas_agendadas(telefono, sesion)
        else:
            self.mostrar_menu_principal(telefono, sesion)
            
# ======================================== SERVICIO A ELEGIR ==================================================

    def mostrar_tipo_servicio(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Muestra tipos de servicio como lista interactiva (4 opciones)."""
        secciones = [{
            "title": "Servicios disponibles",
            "rows": [
                {"id": "servicio_cita",   "title": "👨‍⚕️ Especialidades"},
                {"id": "servicio_lab",    "title": "🧪 Laboratorio Clínico"},
                {"id": "servicio_imagen", "title": "🔬 Imagenología"},
                {"id": "servicio_rehab",  "title": "🏃 Rehabilitación"},
            ]
        }]
        self.api.enviar_lista(
            telefono,
            "🏥 *¿Qué servicio necesitas?*\n\n_Escribe_ *cancelar* _para volver al menú._",
            "Ver servicios",
            secciones,
        )
        sesion.estado_flujo = EstadoFlujo.MENU_CITAS
        self.db.commit()

    def estado_menu_citas(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Procesa selección del menú de servicios."""
        if button_id == "servicio_cita":
            self.guardar_dato_temporal(sesion, "en_seleccion_servicio", "cita")
            self.estado_mostrar_especialidades(telefono, sesion, "cita")

        elif button_id == "servicio_lab":
            self.guardar_dato_temporal(sesion, "en_seleccion_servicio", "lab")
            self.estado_mostrar_lab(telefono, sesion)

        elif button_id == "servicio_imagen":
            self.guardar_dato_temporal(sesion, "en_seleccion_servicio", "imagen")
            self.estado_mostrar_imagen(telefono, sesion)

        elif button_id == "servicio_rehab":
            self.guardar_dato_temporal(sesion, "en_seleccion_servicio", "rehab")
            self.estado_mostrar_rehab(telefono, sesion)

        else:
            self.api.enviar_mensaje_texto(telefono, "❌ Opción inválida.\n\nSelecciona un servicio.")
            self.mostrar_tipo_servicio(telefono, sesion)

# ======================================== AGENDAMIENTO CITA MEDICA ==================================================

    def estado_mostrar_especialidades(self, telefono: str, sesion: SesionWhatsApp, tipo_servicio: str) -> None:
        """Muestra lista de especialidades como texto numerado simple"""
        self.guardar_dato_temporal(sesion, 'tipo_servicio', tipo_servicio)
    
        especialidades = self.db.query(Especialidad).order_by(Especialidad.nombre).all()
        
    #    print(especialidades)
    
        if not especialidades:
            self.api.enviar_mensaje_texto(
                telefono, 
                "❌ No hay especialidades disponibles en este momento.\n\n"
                "Por favor intenta más tarde o contacta al hospital."
            )
            self.mostrar_menu_principal(telefono, sesion)
            return

        # Construir mensaje numerado SIN Markdown fuerte
        mensaje = "🏥 *Especialidades Disponibles*\n\n"
        mensaje += "Responde solo con el *número* de la especialidad que deseas:\n\n"
        mensaje += "_Escribe_ *cancelar* _para volver al menú principal._\n\n"
        
        especialidades_dict = {}
        
        for i, esp in enumerate(especialidades, 1):
            mensaje += f"{i}. *{esp.nombre}*\n"
            if esp.descripcion:
                mensaje += f"   {esp.descripcion[:120]}\n"
            mensaje += "\n"
            
            especialidades_dict[str(i)] = {
                "id": esp.id_especialidad,
                "nombre": esp.nombre
            }

    #    mensaje += "Ejemplo: Responde *3* si quieres Cardiología"

        self.api.enviar_mensaje_texto(telefono, mensaje)
        
        # Guardar para procesar la respuesta
        self.guardar_dato_temporal(sesion, 'especialidades_disponibles', especialidades_dict)
        self.guardar_dato_temporal(sesion, 'esperando_numero_especialidad', True)
        
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_ESPECIALIDAD
        self.db.commit()

    def estado_seleccionar_especialidad(self, telefono: str, sesion: SesionWhatsApp, button_id: str = None, mensaje: str = None) -> None:
        """Procesa selección de especialidad por número de texto"""
        especialidades_dict = self.obtener_dato_temporal(sesion, 'especialidades_disponibles')

        if not especialidades_dict:
            self.api.enviar_mensaje_texto(telefono, "❌ No hay especialidades cargadas. Reinicia el proceso.")
            self.estado_mostrar_especialidades(telefono, sesion, "cita")
            return

        if not mensaje or not mensaje.strip().isdigit():
            self.api.enviar_mensaje_texto(telefono, "❌ Debes responder con un número válido de la lista.")
            return

        numero = mensaje.strip()

        if numero not in especialidades_dict:
            self.api.enviar_mensaje_texto(telefono, "❌ Número inválido. Selecciona uno de la lista enviada.")
            return

        data = especialidades_dict[numero]
                
        self.guardar_dato_temporal(sesion, 'id_especialidad', data["id"])
        self.guardar_dato_temporal(sesion, 'nombre_especialidad', data["nombre"])

        # Limpiar temporales
        self.guardar_dato_temporal(sesion, 'esperando_numero_especialidad', False)
        self.guardar_dato_temporal(sesion, 'especialidades_disponibles', None)

        self.api.enviar_mensaje_texto(
            telefono,
            f"✅ Has seleccionado: *{data['nombre']}*"
        )

        # Tras la especialidad: tipo de cita (primera vez / control) y documentos
        self.guardar_dato_temporal(sesion, 'origen_flujo', 'manual')
        self.iniciar_precita(telefono, sesion)

        # Compatibilidad con botones (si usas el flujo antiguo)
        #if button_id and button_id.startswith("esp_"):
        #    id_especialidad = int(button_id.replace("esp_", ""))
        #    especialidad = self.db.query(Especialidad).get(id_especialidad)
        #    if especialidad:
        #        self.guardar_dato_temporal(sesion, 'id_especialidad', id_especialidad)
        #        self.guardar_dato_temporal(sesion, 'nombre_especialidad', especialidad.nombre)
        #        self.mostrar_fechas_disponibles(telefono, sesion)

    # ── Tipo de cita + documentos (orden médica y autorización) ──────────────

    def _eps_requisitos(self, sesion: SesionWhatsApp) -> Tuple[bool, bool]:
        """
        Devuelve (requiere_orden, requiere_autorizacion) según la EPS del paciente.
        Si el paciente no tiene EPS asociada, exige ambos documentos por defecto.
        """
        paciente = self.db.query(Paciente).get(sesion.id_paciente) if sesion.id_paciente else None
        if paciente and paciente.id_eps:
            eps = self.db.query(Eps).get(paciente.id_eps)
            if eps:
                return bool(eps.requiere_orden), bool(eps.requiere_autorizacion)
        return True, True

    def _eps_autorizacion_opcional(self, sesion: SesionWhatsApp) -> bool:
        """True si la EPS del paciente pide la autorización pero permite continuar sin ella."""
        paciente = self.db.query(Paciente).get(sesion.id_paciente) if sesion.id_paciente else None
        if paciente and paciente.id_eps:
            eps = self.db.query(Eps).get(paciente.id_eps)
            if eps:
                return bool(eps.autorizacion_opcional)
        return False

    def _autorizacion_resuelta(self, sesion: SesionWhatsApp) -> bool:
        """La autorización está resuelta si se recibió o si el paciente la omitió (EPS opcional)."""
        return bool(
            self.obtener_dato_temporal(sesion, 'doc_autorizacion')
            or self.obtener_dato_temporal(sesion, 'autorizacion_omitida')
        )

    def _precita_completa(self, sesion: SesionWhatsApp) -> bool:
        """True si ya se eligió tipo de cita y se resolvieron los documentos que exige la EPS."""
        if not self.obtener_dato_temporal(sesion, 'tipo_cita'):
            return False
        req_orden, req_auth = self._eps_requisitos(sesion)
        if req_orden and not self.obtener_dato_temporal(sesion, 'doc_orden'):
            return False
        if req_auth and not self._autorizacion_resuelta(sesion):
            return False
        return True

    def iniciar_precita(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Antes de agendar exige: (Otorrinolaringología) elegir el procedimiento,
        el tipo de cita (primera vez/control) y las fotos de la orden médica y la
        autorización. Reanuda desde donde se quedó.
        """
        # Otorrinolaringología: pedir primero el procedimiento específico.
        if self._es_otorrino(sesion) and not self.obtener_dato_temporal(sesion, 'procedimiento'):
            self.mostrar_procedimiento_orl(telefono, sesion)
            return
        req_orden, req_auth = self._eps_requisitos(sesion)
        if not self.obtener_dato_temporal(sesion, 'tipo_cita'):
            self.mostrar_tipo_cita(telefono, sesion)
        elif req_orden and not self.obtener_dato_temporal(sesion, 'doc_orden'):
            self.pedir_documento(telefono, sesion, 'orden')
        elif req_auth and not self._autorizacion_resuelta(sesion):
            self.pedir_documento(telefono, sesion, 'autorizacion')
        else:
            self.continuar_tras_documentos(telefono, sesion)

    # ── Otorrinolaringología: procedimiento específico ───────────────────────

    def _es_otorrino(self, sesion: SesionWhatsApp) -> bool:
        """True si la especialidad seleccionada es Otorrinolaringología."""
        nombre = self.obtener_dato_temporal(sesion, 'nombre_especialidad') or ''
        return 'otorrino' in self._normalizar_texto(nombre)

    def mostrar_procedimiento_orl(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Menú de procedimientos de Otorrinolaringología (antes del flujo normal)."""
        botones = [
            {"id": "orl_cerumen",     "title": "👂 Extrac. cerumen"},
            {"id": "orl_nasolaringo", "title": "🔬 Nasolaringoscopia"},
            {"id": "orl_epistaxis",   "title": "🩸 Control epistaxis"},
        ]
        self.api.enviar_botones(
            telefono,
            "👂 *Otorrinolaringología*\n\n¿Qué procedimiento necesitas?\n\n"
            "_Escribe_ *cancelar* _para volver al menú._",
            botones,
        )
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_PROCEDIMIENTO_ORL
        self.db.commit()

    def estado_procedimiento_orl(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Guarda el procedimiento de Otorrino y continúa con el flujo normal."""
        procedimientos = {
            "orl_cerumen":     "Extracción de cerumen",
            "orl_nasolaringo": "Nasolaringoscopia",
            "orl_epistaxis":   "Control de epistaxis",
        }
        if button_id not in procedimientos:
            self.mostrar_procedimiento_orl(telefono, sesion)
            return
        self.guardar_dato_temporal(sesion, 'procedimiento', procedimientos[button_id])
        self.api.enviar_mensaje_texto(
            telefono, f"✅ Procedimiento: *{procedimientos[button_id]}*."
        )
        # Continuar con el flujo normal (tipo de cita → documentos → agendamiento).
        self.iniciar_precita(telefono, sesion)

    def mostrar_tipo_cita(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Pregunta si la cita es de primera vez o de control."""
        nombre_esp = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
        botones = [
            {"id": "tipocita_primera", "title": "🆕 Primera vez"},
            {"id": "tipocita_control", "title": "🔁 Control"},
        ]
        self.api.enviar_botones(
            telefono,
            f"🏥 *{nombre_esp}*\n\n¿La cita es de *primera vez* o de *control*?\n\n"
            f"_Escribe_ *cancelar* _para volver al menú._",
            botones,
        )
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_TIPO_CITA
        self.db.commit()

    def estado_tipo_cita(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Guarda el tipo de cita y continúa pidiendo los documentos."""
        if button_id == "tipocita_primera":
            self.guardar_dato_temporal(sesion, 'tipo_cita', 'primera_vez')
        elif button_id == "tipocita_control":
            self.guardar_dato_temporal(sesion, 'tipo_cita', 'control')
        else:
            self.mostrar_tipo_cita(telefono, sesion)
            return
        etiqueta = "primera vez" if self.obtener_dato_temporal(sesion, 'tipo_cita') == 'primera_vez' else "control"
        self.api.enviar_mensaje_texto(telefono, f"✅ Cita de *{etiqueta}*.")
        self.iniciar_precita(telefono, sesion)

    # ── Tipo de cita (primera vez / control) y médico de continuidad ─────────

    def _medicos_de_especialidad(self, sesion: SesionWhatsApp) -> List['Medico']:
        """
        Médicos activos de la especialidad seleccionada. En una cita de CONTROL con
        médico previo ya identificado, restringe la lista a ESE médico para dar
        continuidad de atención (el paciente no elige otro).
        """
        id_esp = self.obtener_dato_temporal(sesion, 'id_especialidad')
        q = self.db.query(Medico).filter(Medico.id_especialidad == id_esp,
                                         Medico.activo == True)
        forzado = self.obtener_dato_temporal(sesion, 'id_medico_control')
        if forzado:
            q = q.filter(Medico.id_medico == forzado)
        return q.all()

    def _medico_previo_control(self, sesion: SesionWhatsApp):
        """
        id del médico que atendió antes a este paciente en la especialidad
        seleccionada (para citas de control). Busca primero en 'citas' y, como
        respaldo, en 'historico_citas'. Devuelve None si no hay antecedente.
        """
        id_pac = sesion.id_paciente
        id_esp = self.obtener_dato_temporal(sesion, 'id_especialidad')
        if not (id_pac and id_esp):
            return None
        cita = (self.db.query(Cita)
                .filter(Cita.id_paciente == id_pac,
                        Cita.id_especialidad == id_esp,
                        Cita.id_medico.isnot(None),
                        Cita.estado.in_(['completada', 'agendada', 'inasistida', 'pendiente']))
                .order_by(Cita.fecha_cita.desc(), Cita.id_cita.desc())
                .first())
        if cita:
            return cita.id_medico
        try:  # el histórico es una tabla dinámica; puede no existir
            row = self.db.execute(text(
                "SELECT id_medico FROM historico_citas "
                "WHERE id_paciente = :p AND id_especialidad = :e AND id_medico IS NOT NULL "
                "ORDER BY fecha_cita DESC NULLS LAST LIMIT 1"
            ), {"p": id_pac, "e": id_esp}).fetchone()
            return row[0] if row else None
        except Exception:
            return None

    # Palabras clave para deducir el tipo de cita del NOMBRE del procedimiento
    # que aparece en la orden médica (fallback si el OCR no marca `tipo_cita`).
    _KW_PRIMERA = ('primera vez', 'primera-vez', 'primeravez', 'consulta inicial',
                   'valoracion inicial', 'valoración inicial', 'valoracion por',
                   'valoración por', 'consulta por primera vez')
    _KW_CONTROL = ('control', 'seguimiento', 'revision', 'revisión', 'chequeo',
                   'monitoreo', 'consulta de control', 'consulta control',
                   'consulta de seguimiento')

    def _detectar_tipo_cita_orden(self, datos_orden: dict, codigo_cups: str = None):
        """
        Deduce si la orden médica es 'primera_vez' o 'control' combinando tres
        pistas y priorizándolas:
          1) Campo `tipo_cita` que devuelve el OCR (el modelo lo clasifica).
          2) Palabras clave en el `procedimiento` (nombre del procedimiento).
          3) Código CUPS colombiano (rangos 8902xx = primera vez, 8903xx = control
             para consultas de medicina). No aplica a procedimientos.
        Devuelve 'primera_vez', 'control' o None si no se puede decidir.
        """
        # 1) Campo explícito del OCR
        val = (str((datos_orden or {}).get('tipo_cita') or '')).strip().lower()
        if val in ('primera_vez', 'control'):
            return val

        # 2) Palabras clave en el nombre del procedimiento
        proc = self._normalizar_texto(str((datos_orden or {}).get('procedimiento') or ''))
        if proc:
            tiene_primera = any(k in proc for k in self._KW_PRIMERA)
            tiene_control = any(k in proc for k in self._KW_CONTROL)
            if tiene_primera and not tiene_control:
                return 'primera_vez'
            if tiene_control and not tiene_primera:
                return 'control'

        # 3) Código CUPS: en Colombia, las consultas de medicina siguen el patrón
        #    8902xx = primera vez, 8903xx = control (aplica solo a consultas).
        c = re.sub(r'\D', '', str(codigo_cups or ''))
        if len(c) == 6:
            if c.startswith('8902'):
                return 'primera_vez'
            if c.startswith('8903'):
                return 'control'
        return None

    def _preparar_medico_control(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Para citas de CONTROL, fija el médico que atendió antes al paciente en la
        especialidad (continuidad) y avisa. Para PRIMERA VEZ (o si no hay
        antecedente) limpia cualquier médico forzado para que el paciente elija.
        """
        if self.obtener_dato_temporal(sesion, 'tipo_cita') != 'control':
            self.guardar_dato_temporal(sesion, 'id_medico_control', None)
            return
        prev = self._medico_previo_control(sesion)
        medico = self.db.query(Medico).get(prev) if prev else None
        if medico and medico.activo:
            self.guardar_dato_temporal(sesion, 'id_medico_control', medico.id_medico)
            self.api.enviar_mensaje_texto(
                telefono,
                f"🔁 *Cita de control.* Continuarás con quien te atendió antes: "
                f"*Dr(a). {medico.nombres} {medico.apellidos}*. Verás solo su disponibilidad."
            )
            return
        # Sin antecedente utilizable → permitir elegir médico.
        self.guardar_dato_temporal(sesion, 'id_medico_control', None)
        aviso = ("🔁 *Cita de control.* No encontré un médico que te haya atendido antes "
                 "en esta especialidad")
        if medico and not medico.activo:
            aviso = ("🔁 *Cita de control.* El médico que te atendió antes ya no está "
                     "disponible")
        self.api.enviar_mensaje_texto(telefono, aviso + ", así que podrás elegir uno.")

    def pedir_documento(self, telefono: str, sesion: SesionWhatsApp, tipo: str) -> None:
        """Pide la foto de la orden médica o de la autorización."""
        if tipo == 'orden':
            self.api.enviar_mensaje_texto(
                telefono,
                "📄 *Orden médica*\n\n"
                "Envía una *foto clara* o el *PDF* de tu *orden médica* (remisión).\n\n"
                "_Verificaremos que el *nombre*, la *cédula* y el *procedimiento* coincidan "
                "con tus datos y la especialidad elegida._"
            )
            sesion.estado_flujo = EstadoFlujo.ESPERAR_DOC_ORDEN
        else:
            texto = (
                "📄 *Autorización*\n\n"
                "Ahora envía una *foto clara* o el *PDF* de tu *autorización* (de la EPS).\n\n"
                "_Verificaremos el *nombre*, la *cédula*, la *EPS*, el *prestador* "
                f"(*{settings.HOSPITAL_NOMBRE}*), la *especialidad* y que la *fecha* esté "
                "vigente (no mayor a 3 meses)._"
            )
            if self._eps_autorizacion_opcional(sesion):
                # La EPS pide la autorización pero permite continuar sin ella.
                self.api.enviar_botones(
                    telefono,
                    texto + "\n\n_Si no la tienes a mano, puedes continuar sin ella._",
                    [{"id": "auth_omitir", "title": "➡️ Continuar sin ella"}],
                )
            else:
                self.api.enviar_mensaje_texto(telefono, texto)
            sesion.estado_flujo = EstadoFlujo.ESPERAR_DOC_AUTORIZACION
        self.db.commit()

    def _recibir_documento(self, telefono: str, sesion: SesionWhatsApp, media_id: str,
                           tipo: str, mime_type: str = "image/jpeg") -> None:
        """
        Descarga (foto o PDF), guarda y VERIFICA por OCR que los datos del documento
        coincidan antes de aceptarlo:
          - Orden médica: nombre + cédula del paciente y procedimiento = especialidad.
          - Autorización: nombre + cédula, EPS registrada, prestador = hospital,
            fecha vigente (≤ 3 meses) y procedimiento = especialidad.
        """
        etiqueta = "orden médica" if tipo == 'orden' else "autorización"
        self.api.enviar_mensaje_texto(telefono, f"🔍 Verificando tu *{etiqueta}*, un momento…")
        try:
            import os
            from ocr_processor import ProcesadorOCR
            ext = "pdf" if mime_type == "application/pdf" else "jpg"
            nombre = f"{telefono}_{tipo}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{ext}"
            ruta_rel = f"documentos/{nombre}"
            ruta_abs = os.path.join("static", "documentos", nombre)
            # Contexto: especialidad elegida, para que el OCR tome el código CUPS
            # correcto de la orden cuando ésta lista varios procedimientos.
            ctx_esp = self.obtener_dato_temporal(sesion, 'nombre_especialidad') if tipo == 'orden' else None
            ok, datos = ProcesadorOCR().extraer_datos_documento(
                media_id, tipo, ruta_abs, mime_type, contexto_especialidad=ctx_esp)
        except Exception as e:
            print(f"❌ Error procesando documento: {e}")
            self.api.enviar_mensaje_texto(
                telefono, "❌ Hubo un problema procesando la imagen. Intenta enviarla de nuevo."
            )
            return

        if not ok:
            self.api.enviar_mensaje_texto(
                telefono, "❌ No pude descargar la imagen. Por favor envíala de nuevo."
            )
            return

        # ── PASO 1: confirmar por palabras clave que el documento ES del tipo pedido ──
        tipo_detectado = self._detectar_tipo_documento(datos)
        if tipo_detectado is None:
            self.api.enviar_mensaje_texto(
                telefono,
                f"❌ No pude reconocer este documento como una *{etiqueta}*.\n\n"
                f"Envía una *foto o PDF clara* del documento correcto."
            )
            return  # se mantiene en el mismo estado esperando otro archivo
        if tipo_detectado != tipo:
            otra = "orden médica" if tipo_detectado == 'orden' else "autorización"
            self.api.enviar_mensaje_texto(
                telefono,
                f"❌ Esto parece ser una *{otra}*, pero en este paso necesito tu *{etiqueta}*.\n\n"
                f"Por favor envía el documento correcto."
            )
            return

        # ── PASO 2: ya confirmado el tipo → comparar los demás datos ──
        errores = self._validar_datos_documento(sesion, tipo, datos)
        if errores:
            self.api.enviar_mensaje_texto(
                telefono,
                f"❌ *La {etiqueta} no coincide con tus datos:*\n\n"
                + "\n".join(errores)
                + "\n\nEnvía una foto *clara y completa* del documento correcto, "
                  "o escribe *cancelar* para volver al menú."
            )
            return  # se mantiene en el mismo estado esperando otra foto

        # ── PASO 3 (solo orden): clave única No. orden + código CUPS + cédula ──
        # Se avisa de inmediato al verificar la orden si ese procedimiento ya tiene
        # una cita activa (la comprobación definitiva se repite al confirmar).
        if tipo == 'orden':
            bloqueo = self._cita_duplicada_por_clave(sesion, datos)
            if bloqueo:
                self.mostrar_menu_fin(telefono, sesion, mensaje_intro=bloqueo)
                return

        clave = 'doc_orden' if tipo == 'orden' else 'doc_autorizacion'
        clave_datos = 'doc_orden_datos' if tipo == 'orden' else 'doc_autorizacion_datos'
        self.guardar_dato_temporal(sesion, clave, ruta_rel)
        self.guardar_dato_temporal(sesion, clave_datos, datos)  # se persiste al confirmar la cita
        self.api.enviar_mensaje_texto(telefono, f"✅ *{etiqueta.capitalize()}* verificada. Los datos coinciden.")
        self.iniciar_precita(telefono, sesion)

    def _cita_duplicada_por_clave(self, sesion: SesionWhatsApp, datos_orden: dict) -> Optional[str]:
        """
        Clave única de agendamiento = (No. orden + código CUPS + cédula del paciente).
        Devuelve un mensaje de bloqueo si YA existe una cita NO cancelada con esa clave
        para el paciente; None si se puede agendar. Con datos incompletos (sin No. orden
        o sin código) no bloquea: la clave no está completa.
        """
        numero_orden = (str((datos_orden or {}).get('numero_orden') or '')).strip() or None
        codigo_proc = (str((datos_orden or {}).get('codigo_procedimiento') or '')).strip() or None
        if not (numero_orden and codigo_proc):
            return None
        dup = (self.db.query(Cita)
               .filter(Cita.id_paciente == sesion.id_paciente,
                       Cita.numero_orden == numero_orden,
                       Cita.codigo_procedimiento == codigo_proc,
                       Cita.estado != 'cancelada')
               .order_by(Cita.id_cita.desc())
               .first())
        if not dup:
            return None
        return (
            "⛔ *Este procedimiento ya está agendado.*\n\n"
            f"La orden *{numero_orden}* con el procedimiento *{codigo_proc}* ya tiene "
            f"una cita activa (solicitud *#{dup.id_cita}*).\n\n"
            "No es posible agendar dos veces el mismo procedimiento de la misma orden. "
            "Si necesitas reagendarlo, primero *cancela* la cita anterior desde "
            "«Ver / Cancelar citas» y vuelve a intentarlo."
        )

    # Palabras clave para identificar el tipo de documento por su título/encabezado.
    _KW_ORDEN = ('orden medica', 'orden med', 'remision', 'orden de servicio',
                 'solicitud de procedimiento', 'orden_medica', 'orden clinica')
    _KW_AUTORIZACION = ('autorizacion', 'autorizacion de servicios', 'servicio autorizado')

    def _detectar_tipo_documento(self, datos: dict):
        """
        Identifica si el documento es 'orden' o 'autorizacion' buscando palabras
        clave en el título/tipo que devuelve el OCR. Devuelve 'orden' |
        'autorizacion' | None (None = no se pudo confirmar el tipo).
        """
        td = self._normalizar_texto(datos.get('tipo_documento') or '')
        titulo = self._normalizar_texto(datos.get('titulo') or '')
        texto = f"{td} {titulo}"

        tiene_orden = any(k in texto for k in self._KW_ORDEN)
        tiene_auth = any(k in texto for k in self._KW_AUTORIZACION)
        # La clasificación directa del modelo (tipo_documento) tiene prioridad.
        if td.startswith('orden'):
            tiene_orden = True
        if td.startswith('autoriza'):
            tiene_auth = True

        if tiene_orden and not tiene_auth:
            return 'orden'
        if tiene_auth and not tiene_orden:
            return 'autorizacion'
        return None  # ambiguo (ambos o ninguno) → no se confirma el tipo

    def _validar_datos_documento(self, sesion: SesionWhatsApp, tipo: str, datos: dict) -> List[str]:
        """
        Compara los datos leídos del documento con el paciente registrado y la
        especialidad seleccionada. Devuelve la lista de discrepancias (vacía = OK).
        """
        errores: List[str] = []
        paciente = self.db.query(Paciente).get(sesion.id_paciente) if sesion.id_paciente else None
        if not paciente:
            return ["• No pude identificar al paciente en la sesión."]

        # 1) Nombre del paciente
        nombre_doc = datos.get('nombre_paciente')
        nombre_pac = f"{paciente.nombres} {paciente.apellidos}".strip()
        if not self._nombres_coinciden(nombre_doc, nombre_pac):
            if nombre_doc:
                errores.append(f"• El *nombre* del documento («{nombre_doc}») no coincide con el registrado («{nombre_pac}»).")
            else:
                errores.append("• No pude leer el *nombre* del paciente en el documento.")

        # 2) Cédula
        ced_doc = ''.join(c for c in (datos.get('cedula') or '') if c.isdigit())
        ced_pac = ''.join(c for c in (paciente.cedula or '') if c.isdigit())
        if not ced_doc:
            errores.append("• No pude leer la *cédula* en el documento.")
        elif ced_doc != ced_pac:
            errores.append(f"• La *cédula* del documento ({ced_doc}) no coincide con la registrada ({ced_pac}).")

        # 3) Procedimiento = especialidad (orden y autorización)
        proc_doc = datos.get('procedimiento')
        esp = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
        if not self._procedimiento_coincide(proc_doc, esp, sesion):
            if proc_doc:
                errores.append(f"• El *procedimiento* del documento («{proc_doc}») no corresponde a la especialidad seleccionada («{esp}»).")
            else:
                errores.append("• No pude leer el *procedimiento/especialidad* en el documento.")

        # 3.bis) SOLO orden: la clave de agendamiento exige No. de orden + código
        #        CUPS (válido en la tabla de referencia) + cédula. Si falta alguno,
        #        no se agenda y se pide una foto/PDF más clara.
        if tipo == 'orden':
            if not (str(datos.get('numero_orden') or '').strip()):
                errores.append("• No pude leer el *número de orden* (No. de orden) en el documento.")
            codigo = re.sub(r'\D', '', str(datos.get('codigo_procedimiento') or ''))
            if not codigo:
                errores.append("• No pude leer el *código de procedimiento (CUPS)* en el documento.")
            elif not cups_referencia.existe(codigo):
                errores.append(f"• El *código de procedimiento* ({codigo}) no existe en la tabla de referencia CUPS.")

            # 3.ter) La orden debe coincidir con el tipo de cita elegido por el
            #        paciente (primera vez / control). Se deduce del campo
            #        `tipo_cita` del OCR, del nombre del procedimiento y del
            #        código CUPS. Si es del tipo contrario → se rechaza; si no
            #        se puede determinar → se rechaza pidiendo una orden clara.
            elegido = self.obtener_dato_temporal(sesion, 'tipo_cita')
            if elegido in ('primera_vez', 'control'):
                detectado = self._detectar_tipo_cita_orden(datos, codigo)
                if detectado is None:
                    et_e = 'primera vez' if elegido == 'primera_vez' else 'control'
                    errores.append(
                        f"• No pude confirmar en la orden que sea de *{et_e}*. "
                        f"Envía la orden médica donde diga explícitamente *«{et_e}»* "
                        f"(o cuyo procedimiento sea claramente de {et_e})."
                    )
                elif detectado != elegido:
                    et_e = 'primera vez' if elegido == 'primera_vez' else 'control'
                    et_d = 'primera vez' if detectado == 'primera_vez' else 'control'
                    errores.append(
                        f"• Elegiste una cita de *{et_e}*, pero la orden médica es de *{et_d}*. "
                        f"Envía una *orden de {et_e}* o vuelve al menú y cambia el tipo de cita."
                    )

        # 4) Verificaciones adicionales SOLO para la autorización
        if tipo == 'autorizacion':
            # EPS registrada del paciente
            eps_pac = paciente.eps.nombre if paciente.eps else None
            eps_doc = datos.get('eps')
            if eps_pac and not self._eps_coincide(eps_doc, eps_pac):
                if eps_doc:
                    errores.append(f"• La *EPS* del documento («{eps_doc}») no coincide con la registrada («{eps_pac}»).")
                else:
                    errores.append("• No pude leer la *EPS* en el documento.")

            # Prestador del servicio = el hospital
            prest_doc = datos.get('prestador')
            if not self._prestador_coincide(prest_doc):
                if prest_doc:
                    errores.append(f"• El *prestador del servicio* («{prest_doc}») no es *{settings.HOSPITAL_NOMBRE}*.")
                else:
                    errores.append(f"• No pude leer el *prestador del servicio* (debe ser *{settings.HOSPITAL_NOMBRE}*).")

            # Fecha vigente (no mayor a 3 meses)
            ok_fecha, motivo = self._fecha_vigente(datos.get('fecha'))
            if not ok_fecha:
                errores.append(f"• {motivo}")
        return errores

    def _nombres_coinciden(self, nombre_doc: Optional[str], nombre_pac: str) -> bool:
        """
        True si el nombre del documento coincide razonablemente con el del paciente.
        Tolerante a errores de OCR y a nombres/apellidos intermedios omitidos:
        exige que coincidan al menos 2 tokens (o todos, si el nombre tiene menos).
        """
        if not nombre_doc:
            return False
        td = {t for t in self._normalizar_texto(nombre_doc).split() if len(t) >= 3}
        tp = {t for t in self._normalizar_texto(nombre_pac).split() if len(t) >= 3}
        if not tp:
            return True
        comunes = td & tp
        return len(comunes) >= min(2, len(tp))

    def _procedimiento_coincide(self, proc_doc: Optional[str], especialidad: Optional[str], sesion: SesionWhatsApp) -> bool:
        """
        True si el procedimiento leído corresponde a la especialidad seleccionada
        (o al procedimiento específico de Otorrinolaringología ya elegido).
        Compara por inclusión de texto y por raíz de tokens (p. ej. cardiolog-).
        """
        if not proc_doc:
            return False
        pd = self._normalizar_texto(proc_doc)
        objetivos = [especialidad or '']
        orl = self.obtener_dato_temporal(sesion, 'procedimiento')
        if orl:
            objetivos.append(orl)
        for obj in objetivos:
            on = self._normalizar_texto(obj)
            if not on:
                continue
            if on in pd or pd in on:
                return True
            tokens_doc = pd.split()
            for t in [x for x in on.split() if len(x) >= 4]:
                for tdoc in tokens_doc:
                    if t == tdoc or (len(t) >= 5 and len(tdoc) >= 5 and t[:5] == tdoc[:5]):
                        return True
        return False

    def _eps_coincide(self, eps_doc: Optional[str], eps_pac: str) -> bool:
        """True si la EPS leída coincide con la EPS registrada del paciente."""
        if not eps_doc or not eps_pac:
            return False
        d = self._normalizar_texto(eps_doc)
        p = self._normalizar_texto(eps_pac)
        if p in d or d in p:
            return True
        tokens_doc = d.split()
        for t in [x for x in p.split() if len(x) >= 3]:
            for x in tokens_doc:
                if t == x or (len(t) >= 5 and len(x) >= 5 and t[:5] == x[:5]):
                    return True
        return False

    def _prestador_coincide(self, prest_doc: Optional[str]) -> bool:
        """True si el prestador del servicio corresponde al hospital configurado."""
        if not prest_doc:
            return False
        d = self._normalizar_texto(prest_doc)
        objetivo = self._normalizar_texto(settings.HOSPITAL_NOMBRE)  # p. ej. "hospital civil de ipiales"
        if objetivo in d:
            return True
        tokens = [t for t in objetivo.split() if len(t) >= 4]  # hospital, civil, ipiales
        if not tokens:
            return False
        presentes = sum(1 for t in tokens if t in d)
        return presentes >= max(2, len(tokens) - 1)  # tolera que falte 1 palabra

    def _fecha_vigente(self, fecha_str: Optional[str]) -> Tuple[bool, str]:
        """
        Verifica que la autorización tenga una fecha de expedición vigente:
        no anterior a 3 meses y no en el futuro. Devuelve (ok, motivo_error).
        """
        if not fecha_str:
            return False, "No pude leer la *fecha de expedición* de la autorización."
        try:
            f = date.fromisoformat(str(fecha_str).strip()[:10])
        except ValueError:
            try:
                from dateutil import parser as _dp
                f = _dp.parse(str(fecha_str), dayfirst=True).date()
            except Exception:
                return False, f"No pude interpretar la *fecha* del documento («{fecha_str}»)."
        from dateutil.relativedelta import relativedelta
        hoy = date.today()
        if f < hoy - relativedelta(months=3):
            return False, (f"La *autorización* no está vigente: su fecha ({f.strftime('%d/%m/%Y')}) "
                           f"supera los 3 meses.")
        if f > hoy + timedelta(days=7):
            return False, f"La *fecha* de la autorización ({f.strftime('%d/%m/%Y')}) no es válida."
        return True, ""

    def continuar_tras_documentos(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Con los documentos ya recibidos, entra directo al menú unificado:
        1) elegir médico → 2) elegir fecha del médico → 3) elegir hora → resumen.

        Para citas de CONTROL: se fija automáticamente el médico que atendió
        antes al paciente en la especialidad (continuidad de atención). Si no
        hay antecedente, se le permite elegir uno. Para PRIMERA VEZ: elige libremente.
        """
        # Aplica la restricción por tipo de cita antes de listar médicos.
        self._preparar_medico_control(telefono, sesion)

        origen = self.obtener_dato_temporal(sesion, 'origen_flujo') or 'manual'
        if origen == 'ia':
            # `avanzar_agendamiento_inteligente` lee por sí mismo TODOS los
            # temporales `_ia` (medico/fecha/hora/turno) que se guardaron al
            # interpretar el texto libre, así que no hay que pasarlos aquí.
            # Con la orden médica ya recibida saltará al paso más avanzado que
            # esos datos permitan alcanzar (médico → fecha → hora → resumen).
            self.avanzar_agendamiento_inteligente(telefono, sesion)
        else:
            self.mostrar_medicos_especialidad(telefono, sesion)

    # ── Nuevo paso 1: elegir médico de la especialidad ───────────────────────

    def mostrar_medicos_especialidad(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Primer paso tras los documentos: lista los médicos activos de la
        especialidad. En una cita de CONTROL con médico previo identificado,
        `_medicos_de_especialidad` ya restringe a ese médico (auto-selección).
        """
        medicos = self._medicos_de_especialidad(sesion)
        if not medicos:
            self.mostrar_menu_fin(
                telefono, sesion,
                mensaje_intro=(
                    "❌ No hay médicos registrados para esta especialidad.\n\n"
                    f"📞 *Comunícate con un asesor del hospital:*\n"
                    f"🏥 {settings.HOSPITAL_NOMBRE}\n"
                    f"📍 {settings.HOSPITAL_DIRECCION}\n"
                    f"☎️ {settings.HOSPITAL_TELEFONO}"
                ),
            )
            return

        especialidad = self.obtener_dato_temporal(sesion, 'nombre_especialidad')

        # Auto-selección: si solo hay UN médico disponible (o está forzado por
        # control), se toma directamente y se salta al paso de fechas.
        if len(medicos) == 1:
            m = medicos[0]
            self.guardar_dato_temporal(sesion, 'id_medico', m.id_medico)
            self.guardar_dato_temporal(sesion, 'nombre_medico', f"{m.nombres} {m.apellidos}")
            self.mostrar_fechas_disponibles(telefono, sesion)
            return

        # Lista interactiva (hasta 10 médicos por lista de WhatsApp)
        rows = []
        for m in medicos[:10]:
            rows.append({
                "id": f"med_{m.id_medico}",
                "title": f"Dr(a). {m.nombres} {m.apellidos}"[:24],
            })
        secciones = [{"title": "Médicos disponibles", "rows": rows}]
        self.api.enviar_lista(
            telefono,
            f"👨‍⚕️ *Selecciona el médico*\n\n🏥 {especialidad}\n\n"
            f"_Escribe_ *cancelar* _para volver al menú._",
            "Ver médicos",
            secciones,
        )
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_MEDICO
        self.db.commit()

    def estado_seleccionar_medico_especialidad(
        self, telefono: str, sesion: SesionWhatsApp, button_id: str
    ) -> None:
        """
        Procesa la elección del médico (paso 1 del nuevo flujo). Guarda el médico
        y continúa mostrando las fechas disponibles de ese médico.
        """
        if not (button_id and button_id.startswith("med_")):
            self.mostrar_medicos_especialidad(telefono, sesion)
            return
        try:
            id_medico = int(button_id.replace("med_", ""))
        except ValueError:
            self.mostrar_medicos_especialidad(telefono, sesion)
            return
        medico = self.db.query(Medico).get(id_medico)
        if not medico:
            self.mostrar_medicos_especialidad(telefono, sesion)
            return
        self.guardar_dato_temporal(sesion, 'id_medico', id_medico)
        self.guardar_dato_temporal(sesion, 'nombre_medico', f"{medico.nombres} {medico.apellidos}")
        self.mostrar_fechas_disponibles(telefono, sesion)

    def mostrar_fechas_disponibles(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Paso 2 del nuevo flujo: muestra las fechas en las que el MÉDICO YA ELEGIDO
        tiene al menos un slot disponible (según `slots_disponibles`, semillado de
        esp_horarios.xlsx). Los slots ya ocupados por una cita agendada/pendiente
        del mismo médico+fecha+hora se descuentan mediante JOIN a `citas`.
        """
        id_medico = self.obtener_dato_temporal(sesion, 'id_medico')
        if not id_medico:
            self.mostrar_medicos_especialidad(telefono, sesion)
            return
        medico = self.db.query(Medico).get(id_medico)
        if not medico:
            self.mostrar_medicos_especialidad(telefono, sesion)
            return

        _hoy = date.today()
        _limite_hoy = (datetime.now() + timedelta(minutes=30)).time()

        # Todos los slots futuros del médico (fecha >= hoy)
        slots = (self.db.query(SlotDisponible.fecha, SlotDisponible.hora)
                 .filter(SlotDisponible.id_medico == id_medico,
                         SlotDisponible.fecha >= _hoy)
                 .all())

        # Slots ya ocupados (misma médico + fecha + hora en citas activas)
        ocupados = {
            (r.fecha_cita, r.hora_cita)
            for r in self.db.query(Cita.fecha_cita, Cita.hora_cita).filter(
                Cita.id_medico == id_medico,
                Cita.fecha_cita >= _hoy,
                Cita.estado.in_(['agendada', 'pendiente'])
            ).all()
        }

        # Contar libres por fecha (excluye slots pasados si la fecha es hoy)
        libres_por_fecha: dict = {}
        for s in slots:
            if s.fecha == _hoy and s.hora < _limite_hoy:
                continue
            if (s.fecha, s.hora) in ocupados:
                continue
            libres_por_fecha[s.fecha] = libres_por_fecha.get(s.fecha, 0) + 1

        fechas_ord = sorted(f for f, n in libres_por_fecha.items() if n > 0)
        rows = []
        for f in fechas_ord[:10]:
            dia_label = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][f.weekday()]
            rows.append({
                "id": f"fecha_{f.isoformat()}",
                "title": f"{dia_label} {f.strftime('%d/%m/%Y')}"[:24],
            })

        if not rows:
            # Sin cupos para este médico. Si es el único de la especialidad
            # (o está forzado por continuidad de control), volver a
            # `mostrar_medicos_especialidad` provoca un bucle: auto-selecciona
            # al mismo médico y regresa aquí. Cortamos con un mensaje claro y
            # devolvemos al menú principal.
            especialidad = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
            todos = self._medicos_de_especialidad(sesion)
            if len(todos) <= 1:
                self.mostrar_menu_fin(
                    telefono, sesion,
                    mensaje_intro=(
                        f"❌ *No hay horarios disponibles* para *{especialidad}* en este momento.\n\n"
                        f"Dr(a). {medico.nombres} {medico.apellidos} no tiene cupos abiertos.\n\n"
                        f"📞 *Comunícate con un asesor del hospital* para más información:\n"
                        f"🏥 {settings.HOSPITAL_NOMBRE}\n"
                        f"☎️ {settings.HOSPITAL_TELEFONO}"
                    ),
                )
            else:
                # Hay otros médicos donde elegir: se ofrece cambiar.
                self.mostrar_opciones_sin_medico(
                    telefono, sesion,
                    f"❌ Dr(a). {medico.nombres} {medico.apellidos} no tiene cupos disponibles.\n\n"
                    "¿Deseas elegir otro médico o cancelar la solicitud?",
                    retorno='medico',
                )
            return

        # Auto-selección si solo hay una fecha
        if len(rows) == 1:
            fecha_unica = date.fromisoformat(rows[0]["id"].replace("fecha_", ""))
            self.guardar_dato_temporal(sesion, 'fecha_cita', fecha_unica.isoformat())
            self.api.enviar_mensaje_texto(
                telefono,
                f"📅 Única fecha disponible: *{fecha_unica.strftime('%d/%m/%Y')}*. La selecciono por ti."
            )
            self.mostrar_horarios_medico(telefono, sesion)
            return

        secciones = [{"title": "Fechas disponibles", "rows": rows}]
        self.api.enviar_lista(
            telefono,
            f"📅 *Selecciona la fecha*\n\n"
            f"👨‍⚕️ Dr(a). {medico.nombres} {medico.apellidos}\n\n"
            f"_Escribe_ *cancelar* _para volver al menú._",
            "Ver fechas",
            secciones,
        )
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_FECHA
        self.db.commit()

    def estado_seleccionar_fecha(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Procesa selección de fecha y salta directo a las horas del médico."""
        if not (button_id and button_id.startswith("fecha_")):
            return
        try:
            fecha_obj = date.fromisoformat(button_id.replace("fecha_", ""))
        except ValueError:
            return
        self.guardar_dato_temporal(sesion, 'fecha_cita', fecha_obj.isoformat())
        self.mostrar_horarios_medico(telefono, sesion)

    def _opciones_horario_medico(self, id_medico: int, fecha: date) -> List[Dict]:
        """
        Slots libres del médico en la fecha, tomados de `slots_disponibles`
        (semillado desde esp_horarios.xlsx). Se descuentan los ocupados por
        citas activas (agendada/pendiente) del mismo médico+fecha+hora, y
        si la fecha es hoy se filtran los slots cuya hora ya pasó (+ 30 min).
        Cada opción: {"im": id_medico, "nm": "Nombres Apellidos", "h": "HH:MM"}.
        """
        medico = self.db.query(Medico).get(id_medico)
        if not medico:
            return []
        slots = self.db.query(SlotDisponible.hora).filter(
            SlotDisponible.id_medico == id_medico,
            SlotDisponible.fecha == fecha
        ).all()
        if not slots:
            return []
        ocupados = {
            r.hora_cita
            for r in self.db.query(Cita.hora_cita).filter(
                Cita.id_medico == id_medico,
                Cita.fecha_cita == fecha,
                Cita.estado.in_(['agendada', 'pendiente'])
            ).all()
        }
        limite = (datetime.now() + timedelta(minutes=30)).time() if fecha == date.today() else None
        # Deduplicar y ordenar (por si hubiera repetidos)
        horas = sorted({s.hora for s in slots})
        libres = [h for h in horas
                  if h not in ocupados and (limite is None or h >= limite)]
        return [
            {"im": id_medico,
             "nm": f"{medico.nombres} {medico.apellidos}",
             "h": h.strftime('%H:%M')}
            for h in libres
        ]

    def mostrar_horarios_medico(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Paso 3 del nuevo flujo: horarios disponibles del médico elegido en la
        fecha elegida (sin jornada mañana/tarde). Envía la primera página.
        """
        id_medico = self.obtener_dato_temporal(sesion, 'id_medico')
        fecha_str = self.obtener_dato_temporal(sesion, 'fecha_cita')
        if not (id_medico and fecha_str):
            self.mostrar_medicos_especialidad(telefono, sesion)
            return
        fecha = date.fromisoformat(fecha_str)
        opciones = self._opciones_horario_medico(id_medico, fecha)

        # Auto-selección: si solo hay UN horario+médico disponible, se toma
        # directamente y se salta al resumen, sin pedir que elija de la lista.
        if len(opciones) == 1:
            op = opciones[0]
            hora_dt = datetime.strptime(op['h'], '%H:%M')
            self.api.enviar_mensaje_texto(
                telefono,
                f"🕐 Solo hay un horario disponible: *{hora_dt.strftime('%I:%M %p')}* "
                f"con Dr(a). {op['nm']}. Lo selecciono por ti."
            )
            self._fijar_opcion_y_confirmar(telefono, sesion, op)
            return

        self.guardar_dato_temporal(sesion, 'opciones_horario', opciones)
        self.guardar_dato_temporal(sesion, 'opciones_offset', 0)
        self._enviar_pagina_horarios(telefono, sesion)

    def _enviar_pagina_horarios(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Envía una página de horarios libres del médico elegido en la fecha
        elegida. Muestra hasta HORARIOS_POR_PAGINA opciones y, si hay más, una
        opción extra "Otros" para ver los siguientes.
        """
        opciones = self.obtener_dato_temporal(sesion, 'opciones_horario') or []
        offset = self.obtener_dato_temporal(sesion, 'opciones_offset') or 0
        fecha_str = self.obtener_dato_temporal(sesion, 'fecha_cita')
        fecha = date.fromisoformat(fecha_str)
        medico_nombre = self.obtener_dato_temporal(sesion, 'nombre_medico') or ''

        if not opciones:
            self.mostrar_opciones_sin_medico(
                telefono, sesion,
                "❌ *No hay horarios disponibles* para ese día.\n\n"
                "¿Deseas cancelar la solicitud o elegir otro médico?",
                retorno='medico',
            )
            return

        # Offset cíclico: al pasar "Otros" varias veces, vuelve al inicio
        if offset >= len(opciones):
            offset = 0
            self.guardar_dato_temporal(sesion, 'opciones_offset', 0)

        pagina = opciones[offset:offset + self.HORARIOS_POR_PAGINA]

        dia = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][fecha.weekday()]
        lineas = [
            f"🕐 *Horarios disponibles*",
            f"👨‍⚕️ Dr(a). {medico_nombre}",
            f"📅 {dia} {fecha.strftime('%d/%m/%Y')}",
            "",
            "Responde con el *número* del horario que prefieras:",
            "",
        ]

        # Mapa número → opción (o "otros"), guardado para procesar la respuesta
        menu: dict = {}
        n = 0
        for op in pagina:
            n += 1
            hora_dt = datetime.strptime(op['h'], '%H:%M')
            lineas.append(f"*{n}.* {hora_dt.strftime('%I:%M %p')}")
            menu[str(n)] = op

        # Opción extra "Otros" si hay más horarios
        if len(opciones) > self.HORARIOS_POR_PAGINA:
            n += 1
            lineas.append(f"*{n}.* 🔄 Ver otros horarios")
            menu[str(n)] = "otros"

        lineas.append("")
        lineas.append("_Escribe_ *cancelar* _para volver al menú._")

        self.guardar_dato_temporal(sesion, 'opciones_menu', menu)
        self.api.enviar_mensaje_texto(telefono, "\n".join(lineas))
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_HORA
        self.db.commit()

    def estado_seleccionar_hora(
        self, telefono: str, sesion: SesionWhatsApp,
        button_id: str = None, mensaje: str = None
    ) -> None:
        """
        Procesa la selección unificada de horario + médico hecha por NÚMERO de
        texto. El número se busca en el mapa 'opciones_menu' construido al
        mostrar la página:
        - "otros": muestra la siguiente página de opciones variadas.
        - una opción concreta: fija médico y hora, y muestra el resumen.
        """
        menu = self.obtener_dato_temporal(sesion, 'opciones_menu') or {}

        clave = None
        if mensaje and mensaje.strip().isdigit():
            clave = mensaje.strip()
        elif button_id and str(button_id).isdigit():
            clave = str(button_id)

        if not clave or clave not in menu:
            self.api.enviar_mensaje_texto(
                telefono,
                "❌ Responde con el *número* de un horario de la lista."
            )
            return

        valor = menu[clave]

        if valor == "otros":
            offset = (self.obtener_dato_temporal(sesion, 'opciones_offset') or 0) + self.HORARIOS_POR_PAGINA
            self.guardar_dato_temporal(sesion, 'opciones_offset', offset)
            self._enviar_pagina_horarios(telefono, sesion)
            return

        medico = self.db.query(Medico).get(valor['im'])
        if not medico:
            self.mostrar_opciones_sin_medico(
                telefono, sesion,
                "❌ *No hay médico disponible* para ese horario.\n\n"
                "¿Deseas cancelar la solicitud o elegir otro médico?",
                retorno='medico',
            )
            return

        self._fijar_opcion_y_confirmar(telefono, sesion, valor)

    # ── Sin médico disponible: cancelar o elegir otro médico ─────────────────

    def mostrar_opciones_sin_medico(
        self, telefono: str, sesion: SesionWhatsApp, mensaje: str, retorno: str = 'medico'
    ) -> None:
        """
        Cuando no se puede asignar un médico, ofrece dos opciones: cancelar la
        solicitud (termina el chat) o elegir otro médico (vuelve al paso
        indicado en `retorno`: 'medico' = menú de médicos de la especialidad).
        """
        self.guardar_dato_temporal(sesion, 'sin_medico_retorno', retorno)
        botones = [
            {"id": "sinmedico_otro",     "title": "👨‍⚕️ Otro médico"},
            {"id": "sinmedico_cancelar", "title": "❌ Cancelar"},
        ]
        self.api.enviar_botones(telefono, mensaje, botones)
        sesion.estado_flujo = EstadoFlujo.SIN_MEDICO_DISPONIBLE
        self.db.commit()

    def estado_sin_medico_disponible(
        self, telefono: str, sesion: SesionWhatsApp, button_id: str
    ) -> None:
        """Procesa la respuesta cuando no había médico disponible."""
        if button_id == "sinmedico_cancelar":
            # Cancelar la solicitud → menú fin (volver o terminar con encuesta).
            self.mostrar_menu_fin(
                telefono, sesion,
                mensaje_intro="❌ *Solicitud cancelada.* No se agendó ninguna cita.",
            )

        elif button_id == "sinmedico_otro":
            # Volver al menú de selección de médico de la especialidad.
            # Si es el único médico (caso control con id_medico_control fijado, o
            # especialidad con un solo activo), reintentar caería en el mismo
            # bucle: liberamos el forzado y avisamos.
            todos = self._medicos_de_especialidad(sesion)
            if len(todos) <= 1:
                if self.obtener_dato_temporal(sesion, 'id_medico_control'):
                    # Continuidad en control: soltar la restricción para que
                    # el paciente pueda elegir cualquier médico activo.
                    self.guardar_dato_temporal(sesion, 'id_medico_control', None)
                    todos = self._medicos_de_especialidad(sesion)
                if len(todos) <= 1:
                    # Sigue habiendo un solo médico (o ninguno): no hay a quién
                    # cambiar. Cerramos con mensaje claro para no reciclar el bucle.
                    especialidad = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
                    self.mostrar_menu_fin(
                        telefono, sesion,
                        mensaje_intro=(
                            f"❌ *No hay otros médicos disponibles* para *{especialidad}*.\n\n"
                            f"📞 *Comunícate con un asesor del hospital*:\n"
                            f"🏥 {settings.HOSPITAL_NOMBRE}\n"
                            f"☎️ {settings.HOSPITAL_TELEFONO}"
                        ),
                    )
                    return
            self.mostrar_medicos_especialidad(telefono, sesion)

        else:
            # Botón desconocido: volver a preguntar.
            self.mostrar_opciones_sin_medico(
                telefono, sesion,
                "Por favor elige una opción:",
                self.obtener_dato_temporal(sesion, 'sin_medico_retorno') or 'medico',
            )

    def mostrar_resumen_cita(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """
        Muestra el resumen de la cita antes de enviar la solicitud al hospital.
        Deja MUY claro que la cita NO queda agendada al pulsar "Continuar":
        queda como SOLICITUD pendiente y el personal debe confirmarla
        manualmente. La notificación de confirmación llega por correo y por
        WhatsApp al celular registrado.
        """
        # Obtener datos del paciente
        paciente = self.db.query(Paciente).get(sesion.id_paciente)

        # Obtener datos de la cita
        especialidad = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
        fecha_str = self.obtener_dato_temporal(sesion, 'fecha_cita')
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date()
        hora_str = self.obtener_dato_temporal(sesion, 'hora_cita')
        medico_nombre = self.obtener_dato_temporal(sesion, 'nombre_medico')
        procedimiento = self.obtener_dato_temporal(sesion, 'procedimiento')
        linea_proc = f"   🔧 Procedimiento: {procedimiento}\n" if procedimiento else ""

        mensaje = (
            f"📋 *RESUMEN DE TU SOLICITUD DE CITA*\n\n"
            f"👤 *Paciente:*\n"
            f"   {paciente.nombres} {paciente.apellidos}\n"
            f"   📱 {paciente.celular}\n"
            f"   📧 {paciente.correo or 'No registrado'}\n"
            f"   🆔 {paciente.cedula}\n\n"
            f"🏥 *Detalles de la cita:*\n"
            f"   Especialidad: {especialidad}\n"
            f"{linea_proc}"
            f"   👨‍⚕️ Médico: Dr(a). {medico_nombre}\n"
            f"   📅 Fecha: {fecha.strftime('%d/%m/%Y')}\n"
            f"   🕐 Hora: {hora_str}\n\n"
            f"⚠️ *IMPORTANTE:* al continuar, tu cita *NO queda agendada* "
            f"de inmediato. Queda como *solicitud pendiente* y el personal "
            f"del hospital debe confirmarla manualmente.\n\n"
            f"📧 Recibirás la *confirmación* en tu correo\n"
            f"📱 y por WhatsApp en {paciente.celular}\n\n"
            f"¿Deseas continuar con el agendamiento?"
        )

        # Solo dos botones: continuar (crear la solicitud) o cancelar.
        botones = [
            {"id": "confirm_si",   "title": "✅ Continuar"},
            {"id": "confirm_menu", "title": "❌ Cancelar"},
        ]
        self.api.enviar_botones(telefono, mensaje, botones)
        sesion.estado_flujo = EstadoFlujo.CONFIRMAR_CITA
        self.db.commit()

    def estado_confirmar_cita(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Confirma y guarda la cita"""
        if button_id == "confirm_si":
            # Crear cita
            fecha_str = self.obtener_dato_temporal(sesion, 'fecha_cita')
            hora_str = self.obtener_dato_temporal(sesion, 'hora_cita')

            # ── Clave única de agendamiento: No. orden + código CUPS + cédula ──
            # (la cédula ↔ id_paciente es 1:1). Una misma orden puede traer varios
            # códigos; cada (orden, código) es una cita distinta. Si ya existe una
            # cita NO cancelada con esta clave, no se permite volver a agendarla:
            # el paciente debe cancelar la anterior para reagendar.
            datos_orden = self.obtener_dato_temporal(sesion, 'doc_orden_datos') or {}
            numero_orden = (str(datos_orden.get('numero_orden') or '')).strip() or None
            codigo_proc = (str(datos_orden.get('codigo_procedimiento') or '')).strip() or None
            bloqueo = self._cita_duplicada_por_clave(sesion, datos_orden)
            if bloqueo:
                self.mostrar_menu_fin(telefono, sesion, mensaje_intro=bloqueo)
                return

            # id_cita con formato YYYYMMDDNNNN — se calcula al momento de
            # insertar mediante la función SQL siguiente_id_cita().
            nuevo_id_cita = int(self.db.execute(
                text("SELECT siguiente_id_cita()")
            ).scalar())

            cita = Cita(
                id_cita=nuevo_id_cita,
                id_paciente=sesion.id_paciente,
                id_especialidad=self.obtener_dato_temporal(sesion, 'id_especialidad'),
                id_medico=self.obtener_dato_temporal(sesion, 'id_medico'),
                fecha_cita=datetime.strptime(fecha_str, "%Y-%m-%d").date(),
                hora_cita=datetime.strptime(hora_str, "%H:%M").time(),
                tipo_servicio=self.obtener_dato_temporal(sesion, 'tipo_servicio'),
                turno=self.obtener_dato_temporal(sesion, 'turno'),
                tipo_cita=self.obtener_dato_temporal(sesion, 'tipo_cita'),
                doc_orden=self.obtener_dato_temporal(sesion, 'doc_orden'),
                doc_autorizacion=self.obtener_dato_temporal(sesion, 'doc_autorizacion'),
                procedimiento=self.obtener_dato_temporal(sesion, 'procedimiento'),
                numero_orden=numero_orden,
                codigo_procedimiento=codigo_proc,
                doc_orden_datos=(json.dumps(self.obtener_dato_temporal(sesion, 'doc_orden_datos'), ensure_ascii=False)
                                 if self.obtener_dato_temporal(sesion, 'doc_orden_datos') else None),
                doc_autorizacion_datos=(json.dumps(self.obtener_dato_temporal(sesion, 'doc_autorizacion_datos'), ensure_ascii=False)
                                        if self.obtener_dato_temporal(sesion, 'doc_autorizacion_datos') else None),
                telefono_whatsapp=telefono,
                estado='pendiente'   # requiere confirmación manual del hospital
            )

            self.db.add(cita)
            try:
                self.db.commit()
            except IntegrityError:
                # Red de seguridad ante una carrera: el índice único parcial de la BD
                # rechazó una cita duplicada (misma orden+código+paciente no cancelada).
                self.db.rollback()
                self.mostrar_menu_fin(
                    telefono, sesion,
                    mensaje_intro=(
                        "⛔ *Este procedimiento ya está agendado.*\n\n"
                        f"La orden *{numero_orden}* con el procedimiento *{codigo_proc}* ya tiene "
                        "una cita activa. Cancela la anterior para poder reagendarla."
                    ),
                )
                return
            self.db.refresh(cita)

            # Obtener datos para el mensaje
            paciente = self.db.query(Paciente).get(sesion.id_paciente)
            medico_nombre = self.obtener_dato_temporal(sesion, 'nombre_medico')
            especialidad = self.obtener_dato_temporal(sesion, 'nombre_especialidad')
            tipo_c = "Primera vez" if cita.tipo_cita == 'primera_vez' else "Control"
            linea_proc = f"   🔧 {cita.procedimiento}\n" if cita.procedimiento else ""
            # Documentos realmente recibidos (según lo que exige la EPS del paciente).
            _docs = []
            if cita.doc_orden:
                _docs.append("orden médica")
            if cita.doc_autorizacion:
                _docs.append("autorización")
            linea_docs = f"📄 Documentos recibidos: {' y '.join(_docs)}.\n\n" if _docs else ""

            correo_line = f"   📧 {paciente.correo}\n" if paciente.correo else ""
            mensaje = (
                f"📨 *SOLICITUD DE CITA RECIBIDA*\n\n"
                f"⏳ *Tu cita AÚN NO está agendada.*\n"
                f"Un miembro del personal del hospital revisará tus documentos "
                f"y confirmará la cita manualmente.\n\n"
                f"📋 *Número de solicitud:* #{cita.id_cita}\n"
                f"👤 {paciente.nombres} {paciente.apellidos}\n\n"
                f"🏥 *Detalles solicitados:*\n"
                f"   {especialidad} · {tipo_c}\n"
                f"{linea_proc}"
                f"   👨‍⚕️ Dr(a). {medico_nombre}\n"
                f"   📅 {cita.fecha_cita.strftime('%d/%m/%Y')}\n"
                f"   🕐 {cita.hora_cita.strftime('%H:%M')}\n\n"
                f"{linea_docs}"
                f"🔔 *Recibirás la confirmación:*\n"
                f"   📱 por WhatsApp en {paciente.celular}\n"
                f"{correo_line}"
                f"\nTe avisaremos por estos medios en cuanto el personal *confirme* tu cita. 🙌"
            )

            self.api.enviar_mensaje_texto(telefono, mensaje)

            # ── Métrica de tiempo: desde que se abrió el chat hasta crear la cita ──
            duracion_seg = None
            inicio_ts = self.obtener_dato_temporal(sesion, 'inicio_ts')
            if inicio_ts:
                try:
                    delta = datetime.now() - datetime.fromisoformat(inicio_ts)
                    duracion_seg = max(0, int(delta.total_seconds()))
                except (ValueError, TypeError):
                    duracion_seg = None
            metrica = MetricaAgendamiento(
                id_cita=cita.id_cita,
                id_paciente=sesion.id_paciente,
                telefono=telefono,
                duracion_seg=duracion_seg,
            )
            self.db.add(metrica)
            self.db.commit()
            self.db.refresh(metrica)

            # Limpiar temporales, conservando la referencia a la métrica para la encuesta.
            sesion.datos_temp = json.dumps({'id_metrica': metrica.id})
            self.db.commit()

            # Encuesta de satisfacción: se muestra directamente el selector de
            # estrellas (sin paso previo de "¿deseas calificar?"). El paciente
            # puede escribir "cancelar" si prefiere no calificar.
            self.mostrar_estrellas(telefono, sesion)

        else:  # confirm_menu u otro (el resumen solo ofrece Continuar / Cancelar)
            self.mostrar_menu_fin(
                telefono, sesion,
                mensaje_intro="↩️ Agendamiento cancelado.",
            )

    def mostrar_menu_satisfaccion(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Pregunta al usuario si su solicitud quedó resuelta."""
        botones = [
            {"id": "satisfaccion_si", "title": "✅ Sí, gracias"},
            {"id": "satisfaccion_no", "title": "🔄 No, volver al inicio"},
        ]
        self.api.enviar_botones(
            telefono,
            "¿Tu solicitud quedó completamente resuelta?",
            botones,
        )
        sesion.estado_flujo = EstadoFlujo.SATISFACCION
        self.db.commit()

    def estado_satisfaccion(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Procesa la respuesta de satisfacción post-agendamiento."""
        if button_id == "satisfaccion_si":
            self.api.enviar_mensaje_texto(
                telefono,
                f"😊 ¡Perfecto! Fue un placer atenderte.\n\n"
                f"Recuerda llegar 15 minutos antes de tu cita.\n"
                f"🏥 {settings.HOSPITAL_NOMBRE}\n\n"
                f"¡Hasta pronto! 👋"
            )
            # Cerrar la sesión activa
            sesion.activo = False
            sesion.estado_flujo = EstadoFlujo.INICIO
            sesion.datos_temp = "{}"
            self.db.commit()
        else:
            self.api.enviar_mensaje_texto(
                telefono,
                "Sin problema, aquí estoy para ayudarte. 🙂"
            )
            self.mostrar_menu_principal(telefono, sesion)

    # ── Menú final: volver al menú principal o terminar el chat ──────────────

    def mostrar_menu_fin(
        self, telefono: str, sesion: SesionWhatsApp, mensaje_intro: str = ""
    ) -> None:
        """
        Menú que aparece al final de cada solicitud (agendada, cancelada, o
        rechazada) para dejar al paciente decidir si vuelve al menú principal o
        cierra el chat. Este menú SIEMPRE debe cerrar los caminos finales del
        flujo — evita salidas abruptas y da control claro al usuario.

        Si `mensaje_intro` viene con texto, se envía antes del menú (por si el
        camino que llegó aquí necesita explicar por qué se termina).
        """
        if mensaje_intro:
            self.api.enviar_mensaje_texto(telefono, mensaje_intro)

        botones = [
            {"id": "fin_menu",     "title": "📅 Volver al menú"},
            {"id": "fin_terminar", "title": "👋 Terminar chat"},
        ]
        self.api.enviar_botones(
            telefono,
            "¿Qué deseas hacer ahora?",
            botones,
        )
        sesion.estado_flujo = EstadoFlujo.MENU_FIN
        self.db.commit()

    def estado_menu_fin(
        self, telefono: str, sesion: SesionWhatsApp, button_id: str
    ) -> None:
        """
        Procesa la elección del menú final:
          - "fin_menu"     → vuelve al menú principal (limpia temporales).
          - "fin_terminar" → despide y muestra la encuesta de satisfacción
                             antes de cerrar (aunque no se haya agendado nada).
        """
        if button_id == "fin_menu":
            self.mostrar_menu_principal(telefono, sesion)
        elif button_id == "fin_terminar":
            self.mostrar_estrellas(telefono, sesion)
        else:
            # Botón desconocido: volver a preguntar.
            self.mostrar_menu_fin(telefono, sesion)

    # ── Encuesta de satisfacción (calificación con estrellas) ────────────────

    def mostrar_estrellas(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Muestra la lista de 1 a 5 estrellas para calificar."""
        rows = [
            {"id": "cal_5", "title": "⭐⭐⭐⭐⭐", "description": "5 · Muy buen servicio"},
            {"id": "cal_4", "title": "⭐⭐⭐⭐",   "description": "4 · Buen servicio"},
            {"id": "cal_3", "title": "⭐⭐⭐",     "description": "3 · Servicio regular"},
            {"id": "cal_2", "title": "⭐⭐",       "description": "2 · Mal servicio"},
            {"id": "cal_1", "title": "⭐",         "description": "1 · Muy mal servicio"},
        ]
        secciones = [{"title": "Califica el servicio", "rows": rows}]
        self.api.enviar_lista(
            telefono,
            "⭐ *¿Cómo calificarías el servicio?*\n\nElige de 1 a 5 estrellas.",
            "Calificar",
            secciones,
        )
        sesion.estado_flujo = EstadoFlujo.ENCUESTA_ESTRELLAS
        self.db.commit()

    def estado_encuesta_estrellas(self, telefono: str, sesion: SesionWhatsApp, button_id: str) -> None:
        """Guarda la calificación (1..5) en la métrica del agendamiento."""
        if not (button_id and button_id.startswith("cal_") and button_id[4:].isdigit()):
            self.mostrar_estrellas(telefono, sesion)
            return
        estrellas = int(button_id.replace("cal_", ""))
        if estrellas < 1 or estrellas > 5:
            self.mostrar_estrellas(telefono, sesion)
            return

        # Guardar la calificación:
        #  - Si hay id_metrica (el paciente sí agendó una cita): actualiza esa
        #    fila para conservar el vínculo cita ↔ estrellas.
        #  - Si NO hay id_metrica (el paciente terminó sin agendar): crea una
        #    métrica "huérfana" (sin id_cita) para no perder la calificación.
        id_metrica = self.obtener_dato_temporal(sesion, 'id_metrica')
        actualizada = False
        if id_metrica:
            metrica = self.db.query(MetricaAgendamiento).get(id_metrica)
            if metrica:
                metrica.estrellas = estrellas
                self.db.commit()
                actualizada = True
        if not actualizada:
            self.db.add(MetricaAgendamiento(
                id_paciente=sesion.id_paciente,
                telefono=telefono,
                estrellas=estrellas,
                # sin id_cita ni duracion_seg: es una calificación sin agendamiento
            ))
            self.db.commit()

        self._cerrar_tras_encuesta(
            telefono, sesion,
            f"{'⭐' * estrellas}\n\n¡Gracias por tu calificación! 🙌"
        )

    def _cerrar_tras_encuesta(self, telefono: str, sesion: SesionWhatsApp, mensaje_extra: str) -> None:
        """Mensaje de despedida y cierre de la sesión tras la encuesta."""
        self.api.enviar_mensaje_texto(
            telefono,
            f"{mensaje_extra}\n\n"
            f"Recuerda llegar 15 minutos antes de tu cita.\n"
            f"🏥 {settings.HOSPITAL_NOMBRE}\n\n"
            f"¡Hasta pronto! 👋"
        )
        sesion.activo = False
        sesion.estado_flujo = EstadoFlujo.INICIO
        sesion.datos_temp = "{}"
        self.db.commit()

    def mostrar_citas_agendadas(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Muestra citas agendadas con selección numerada para cancelar."""
        citas = self.db.query(Cita).filter(
            Cita.id_paciente == sesion.id_paciente,
            Cita.estado.in_(['agendada', 'pendiente']),
            Cita.fecha_cita >= date.today()
        ).order_by(Cita.fecha_cita, Cita.hora_cita).all()

        if not citas:
            self.api.enviar_mensaje_texto(
                telefono,
                "📋 No tienes citas agendadas próximas."
            )
            self.mostrar_menu_principal(telefono, sesion)
            return

        citas_dict = {}
        mensaje = f"📋 *TUS CITAS AGENDADAS ({len(citas)}):*\n\n"

        for i, cita in enumerate(citas, 1):
            dia = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"][cita.fecha_cita.weekday()]
            mensaje += (
                f"*{i}.* Cita #{cita.id_cita}\n"
                f"   🏥 {cita.especialidad.nombre}\n"
                f"   👨‍⚕️ Dr(a). {cita.medico.nombres} {cita.medico.apellidos}\n"
                f"   📅 {dia} {cita.fecha_cita.strftime('%d/%m/%Y')}  🕐 {cita.hora_cita.strftime('%H:%M')}\n\n"
            )
            citas_dict[str(i)] = cita.id_cita

        mensaje += "Para *cancelar* una cita escribe su número.\nEjemplo: escribe *1* para cancelar la primera."

        self.api.enviar_mensaje_texto(telefono, mensaje)

        botones = [
            {"id": "back_cancel",  "title": "🔙 Volver al menú"},
            {"id": "menu_agendar", "title": "📅 Agendar otra"},
        ]
        self.api.enviar_botones(telefono, "O elige una opción:", botones)

        self.guardar_dato_temporal(sesion, 'citas_cancelar_dict', citas_dict)
        sesion.estado_flujo = EstadoFlujo.SELECCIONAR_CITA_CANCELAR
        self.db.commit()

    def iniciar_cancelacion(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Muestra las citas del paciente para seleccionar cuál cancelar."""
        self.mostrar_citas_agendadas(telefono, sesion)

    def estado_seleccionar_cita_cancelar(
        self, telefono: str, sesion: SesionWhatsApp,
        button_id: str = None, mensaje: str = None
    ) -> None:
        """Procesa cancelación: acepta número de texto o botones de confirmación."""

        # ── Paso 1: usuario escribió el número de la cita ─────────────────
        if mensaje and mensaje.strip().isdigit():
            numero = mensaje.strip()
            citas_dict = self.obtener_dato_temporal(sesion, 'citas_cancelar_dict')

            if not citas_dict or numero not in citas_dict:
                self.api.enviar_mensaje_texto(
                    telefono,
                    "❌ Número inválido. Escribe el número de la cita que deseas cancelar."
                )
                return

            id_cita = citas_dict[numero]
            cita = self.db.query(Cita).filter(
                Cita.id_cita == id_cita,
                Cita.id_paciente == sesion.id_paciente,
                Cita.estado.in_(['agendada', 'pendiente'])
            ).first()

            if not cita:
                self.api.enviar_mensaje_texto(telefono, "❌ No se encontró esa cita.")
                self.mostrar_menu_principal(telefono, sesion)
                return

            self._mostrar_confirmacion_cancelar(telefono, cita)
            return

        if not button_id:
            return

        # ── Paso 2: usuario confirmó la cancelación ────────────────────────
        if button_id.startswith("confirm_cancel_"):
            id_cita = int(button_id.replace("confirm_cancel_", ""))
            cita = self.db.query(Cita).filter(
                Cita.id_cita == id_cita,
                Cita.id_paciente == sesion.id_paciente,
                Cita.estado.in_(['agendada', 'pendiente'])
            ).first()

            if not cita:
                self.api.enviar_mensaje_texto(
                    telefono,
                    "❌ No se pudo cancelar. La cita ya no está disponible."
                )
                self.mostrar_menu_principal(telefono, sesion)
                return

            cita.estado = 'cancelada'
            cita.motivo_cancelacion = 'Cancelada por el paciente vía WhatsApp'
            cita.updated_at = datetime.now()
            self.db.commit()

            self.api.enviar_mensaje_texto(
                telefono,
                f"✅ *CITA CANCELADA*\n\n"
                f"🏥 {cita.especialidad.nombre}\n"
                f"👨‍⚕️ Dr(a). {cita.medico.nombres} {cita.medico.apellidos}\n"
                f"📅 {cita.fecha_cita.strftime('%d/%m/%Y')}\n"
                f"🕐 {cita.hora_cita.strftime('%H:%M')}\n\n"
                f"Si necesitas reagendar, estamos a tu disposición."
            )
            self.mostrar_menu_satisfaccion(telefono, sesion)
            return

        # ── Paso 2b: usuario no quiere cancelar ───────────────────────────
        if button_id == "back_cancel":
            self.mostrar_menu_principal(telefono, sesion)
            return

        if button_id == "menu_agendar":
            self.estado_mostrar_especialidades(telefono, sesion, "cita")

    def _mostrar_confirmacion_cancelar(self, telefono: str, cita: Cita) -> None:
        """Muestra el mensaje de confirmación antes de cancelar una cita."""
        dia = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"][cita.fecha_cita.weekday()]
        mensaje = (
            f"⚠️ *¿Confirmas la cancelación?*\n\n"
            f"📌 Cita #{cita.id_cita}\n"
            f"🏥 {cita.especialidad.nombre}\n"
            f"👨‍⚕️ Dr(a). {cita.medico.nombres} {cita.medico.apellidos}\n"
            f"📅 {dia} {cita.fecha_cita.strftime('%d/%m/%Y')}\n"
            f"🕐 {cita.hora_cita.strftime('%H:%M')}\n\n"
            f"Esta acción no se puede deshacer."
        )
        botones = [
            {"id": f"confirm_cancel_{cita.id_cita}", "title": "✅ Sí, cancelar"},
            {"id": "back_cancel",                    "title": "↩ No, volver"},
        ]
        self.api.enviar_botones(telefono, mensaje, botones)

    def estado_mostrar_imagen(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Informa al usuario sobre cómo agendar servicios de imagenología y cierra con menú de satisfacción."""
        self.api.enviar_mensaje_texto(
            telefono,
            f"🔬 *Imagenología*\n\n"
            f"Para agendar servicios de imagenología *comunícate con un asesor del hospital*:\n\n"
            f"🏥 {settings.HOSPITAL_NOMBRE}\n"
            f"📍 {settings.HOSPITAL_DIRECCION}\n"
            f"☎️ {settings.HOSPITAL_TELEFONO}\n\n"
            f"📅 *Horario de atención:*\n"
            f"   Lunes a Viernes\n"
            f"   ☀️ Mañana: 07:00 – 11:30\n"
            f"   🌙 Tarde:  14:00 – 17:30\n\n"
            f"Nuestro equipo te asistirá para agendar tu cita."
        )
        self.mostrar_menu_satisfaccion(telefono, sesion)

    def estado_mostrar_rehab(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Informa al usuario sobre cómo agendar servicios de rehabilitación y cierra con menú de satisfacción."""
        self.api.enviar_mensaje_texto(
            telefono,
            f"🏃 *Rehabilitación*\n\n"
            f"Para agendar servicios de rehabilitación *comunícate con un asesor del hospital*:\n\n"
            f"🏥 {settings.HOSPITAL_NOMBRE}\n"
            f"📍 {settings.HOSPITAL_DIRECCION}\n"
            f"☎️ {settings.HOSPITAL_TELEFONO}\n\n"
            f"📅 *Horario de atención:*\n"
            f"   Lunes a Viernes\n"
            f"   ☀️ Mañana: 07:00 – 11:30\n"
            f"   🌙 Tarde:  14:00 – 17:30\n\n"
            f"Nuestro equipo te asistirá para agendar tu cita."
        )
        self.mostrar_menu_satisfaccion(telefono, sesion)

    def estado_mostrar_lab(self, telefono: str, sesion: SesionWhatsApp) -> None:
        """Informa al usuario sobre cómo agendar servicios de Laboratorio Clínico."""
        self.api.enviar_mensaje_texto(
            telefono,
            f"🧪 *Laboratorio Clínico*\n\n"
            f"Para agendar o consultar servicios de laboratorio clínico "
            f"*comunícate con un asesor del hospital*:\n\n"
            f"🏥 {settings.HOSPITAL_NOMBRE}\n"
            f"📍 {settings.HOSPITAL_DIRECCION}\n"
            f"☎️ {settings.HOSPITAL_TELEFONO}\n\n"
            f"📅 *Horario de atención:*\n"
            f"   Lunes a Viernes\n"
            f"   ☀️ Mañana: 06:30 – 11:00\n"
            f"   🌙 Tarde:  13:00 – 16:00\n\n"
            f"⚠️ _Para exámenes en ayunas recuerda no consumir alimentos "
            f"desde 8 horas antes de tu cita._\n\n"
            f"Nuestro equipo te indicará los requisitos específicos para tu examen."
        )
        self.mostrar_menu_satisfaccion(telefono, sesion)
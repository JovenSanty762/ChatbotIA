"""
ChatBot WhatsApp - Hospital
FastAPI + WhatsApp Business API + PostgreSQL + Ngrok
"""
import asyncio
import logging
import os
import sys
import time
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date

# Forzar UTF-8 en la salida para que los emojis de los logs (🏥, 🚀, ✅, …) no
# rompan el arranque cuando la codificación del entorno no es UTF-8: consola
# cp1252 en Windows o locale "C"/POSIX en systemd (Linux). Sin esto, un print
# durante el lifespan puede lanzar UnicodeEncodeError e impedir que el bot inicie.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

import re
import uvicorn
from fastapi import FastAPI, Request, Response, Depends
from fastapi.responses import PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from bot_config import get_settings
from bot_handler import ChatBotHandler, EstadoFlujo
from bot_models import Base, SesionWhatsApp, Paciente, Cita, Especialidad
from database import engine, SessionLocal, get_db
from admin_router import router as admin_router, auth_router
from auth_admin import requerir_auth

settings = get_settings()

# ── Nota: pyngrok NO se importa aquí al nivel de módulo.
# En Windows, uvicorn --reload usa multiprocessing con método "spawn": cada
# proceso hijo reimporta bot_main.py, y pyngrok ejecuta platform.system() vía
# subprocess en tiempo de importación (pyngrok/conf.py línea ~13).
# Si ese proceso hijo es interrumpido durante ese subprocess, se genera el
# KeyboardInterrupt visible en consola.  La solución es importar pyngrok
# de forma diferida, solo dentro de las funciones async que lo necesitan.

# ====================
# Tarea de fondo: expirar sesiones inactivas
# ====================
async def vigilar_sesiones_inactivas():
    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                corte = datetime.now() - timedelta(minutes=settings.SESSION_TIMEOUT_MINUTES)
                sesiones = db.query(SesionWhatsApp).filter(
                    SesionWhatsApp.activo == True,
                    SesionWhatsApp.ultimo_mensaje < corte,
                    SesionWhatsApp.estado_flujo != EstadoFlujo.INICIO,
                ).all()
                if sesiones:
                    handler = ChatBotHandler(db)
                    for sesion in sesiones:
                        handler.expirar_sesion_inactiva(sesion)
                    print(f"⏰ {len(sesiones)} sesión(es) expirada(s) por inactividad")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error en vigilancia de sesiones: {e}")

# ====================
# Tarea de fondo: marcar citas inasistidas automáticamente
# ====================
async def vigilar_citas_inasistidas():
    """
    Cada 2 minutos busca citas 'agendada' cuya fecha+hora ya superó los 5
    minutos de gracia y las marca como 'inasistida' directamente en la BD.
    Funciona de forma completamente independiente del panel web.
    """
    while True:
        await asyncio.sleep(120)   # revisar cada 2 minutos
        try:
            db = SessionLocal()
            try:
                resultado = db.execute(
                    text("""
                        UPDATE citas
                        SET estado = 'inasistida', updated_at = NOW()
                        WHERE estado = 'agendada'
                          AND (fecha_cita + hora_cita + INTERVAL '5 minutes') < NOW()
                    """)
                )
                db.commit()
                if resultado.rowcount > 0:
                    print(f"🏥 {resultado.rowcount} cita(s) marcadas como inasistidas automáticamente")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error en vigilancia de inasistencias: {e}")

# ====================
# Tarea de fondo: archivar citas cuya fecha ya pasó hace más de 7 días
# ====================
async def vigilar_citas_antiguas():
    """
    Cada hora archiva en 'historico_citas' las citas cuya FECHA ya pasó hace más
    de 7 días y las quita de la tabla activa 'citas'. Mantiene el panel limpio y
    el histórico al día aunque nadie abra el panel. La primera pasada corre de
    inmediato al arrancar.
    """
    from reset_sistema import archivar_citas_antiguas  # noqa: PLC0415
    while True:
        try:
            db = SessionLocal()
            try:
                n = archivar_citas_antiguas(db, 7)
                db.commit()
                if n:
                    print(f"🗄️  {n} cita(s) antigua(s) (+7 días) archivadas en el histórico")
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error archivando citas antiguas: {e}")
        await asyncio.sleep(60 * 60)   # cada hora

# ====================
# Tarea de fondo: limpieza de fechas vencidas
# ====================
async def vigilar_fechas_disponibles():
    """
    Limpieza diaria de fechas vencidas. NO genera fechas nuevas
    automáticamente — las fechas + horarios se cargan manualmente desde
    el panel administrativo (botón "Cargar horarios" en la pestaña Fechas)
    subiendo un Excel semanal. Esta tarea solo elimina lo que ya pasó
    (fechas_disponibles y slots_disponibles anteriores a hoy) para que la
    base de datos no crezca indefinidamente.
    """
    while True:
        try:
            db = SessionLocal()
            try:
                db.execute(text("DELETE FROM fechas_disponibles WHERE fecha < CURRENT_DATE"))
                db.execute(text("DELETE FROM slots_disponibles WHERE fecha < CURRENT_DATE"))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            print(f"❌ Error en limpieza de fechas vencidas: {e}")
        await asyncio.sleep(12 * 60 * 60)   # cada 12 horas

# ====================
# Tarea de fondo: reconectar túnel Ngrok si cae
# ====================
async def vigilar_tunel_ngrok():
    # Import diferido: evita que los worker-processes del reloader ejecuten
    # el subprocess de detección de plataforma de pyngrok al reimportar el módulo.
    from pyngrok import ngrok  # noqa: PLC0415
    logging.getLogger("pyngrok").setLevel(logging.CRITICAL)
    logging.getLogger("pyngrok.process").setLevel(logging.CRITICAL)
    while True:
        await asyncio.sleep(30)
        try:
            tunnels = ngrok.get_tunnels()
            if not tunnels:
                print("⚠️  Túnel Ngrok caído, reconectando...")
                public_url = await _conectar_ngrok_async(ngrok)
                print(f"✅ Túnel Ngrok reconectado: {public_url}/webhook")
        except Exception:
            pass  # Si falla la reconexión se reintenta en 30 s

# ====================
# Ngrok: liberar endpoint ocupado y conectar con reintento (ERR_NGROK_334)
# ====================
def _matar_ngrok_so():
    """
    Mata procesos ngrok huérfanos del sistema operativo (de una ejecución previa
    que no se cerró limpiamente). Esos procesos mantienen ocupado el dominio
    reservado y provocan el error ERR_NGROK_334 al reconectar.
    """
    import subprocess
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/IM", "ngrok.exe"],
                           capture_output=True, timeout=10)
        else:
            subprocess.run(["pkill", "-x", "ngrok"], capture_output=True, timeout=10)
    except Exception:
        pass

async def _conectar_ngrok_async(ngrok, intentos: int = 4):
    """
    Conecta el túnel. Si el endpoint ya está en línea (ERR_NGROK_334) porque quedó
    un túnel previo, cierra ese túnel (agente pyngrok + proceso huérfano del SO) y
    reintenta con una espera creciente para dar tiempo a que ngrok lo libere.
    """
    ultimo = None
    for i in range(intentos):
        try:
            ngrok.set_auth_token(settings.NGROK_AUTH_TOKEN)
            return ngrok.connect(settings.PORT, bind_tls=True)
        except Exception as e:
            ultimo = e
            if "ERR_NGROK_334" in str(e) or "already online" in str(e):
                print(f"⚠️  Endpoint ocupado por un túnel previo; liberándolo (intento {i + 1}/{intentos})…")
                try:
                    ngrok.kill()
                except Exception:
                    pass
                _matar_ngrok_so()
                await asyncio.sleep(min(3 * (i + 1), 12))
            else:
                raise
    raise ultimo

# ====================
# Lifespan
# ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "="*60)
    print("🏥 CHATBOT WHATSAPP - HOSPITAL")
    print("="*60)

    Base.metadata.create_all(bind=engine)
    print("✅ Tablas verificadas")

    # ── Esquema, migraciones, funciones y datos semilla: archivo SQL ÚNICO ────
    # Todo vive en sql_db.sql (idempotente y no destructivo). Se ejecuta en cada
    # arranque para alinear la BD con el modelo, sembrar datos base y crear las
    # funciones (trigger de cupos, refrescar_fechas_disponibles, etc.).
    try:
        ruta_sql = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sql_db.sql")
        with open(ruta_sql, encoding="utf-8") as f:
            script_sql = f.read()
        # Conexión cruda (psycopg2, protocolo simple sin parámetros): ejecuta el
        # script COMPLETO multi-sentencia de una sola vez, respetando los bloques
        # con $$ (funciones/DO). Una sola transacción: si algo falla, revierte.
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            cur.execute(script_sql)
            cur.close()
            raw.commit()
        finally:
            raw.close()
        print("✅ Esquema y datos base sincronizados (sql_db.sql)")
    except Exception as e:
        print(f"⚠️  No se pudo aplicar sql_db.sql: {e}")

    db = SessionLocal()
    try:
        ChatBotHandler(db).resetear_todas_las_sesiones()
        # NOTA: las fechas de agendamiento ya NO se generan automáticamente.
        # Se cargan desde el panel administrativo (Fechas > Cargar horarios)
        # subiendo el Excel semanal del hospital. Solo se limpian aquí las
        # fechas vencidas para mantener la BD compacta.
        try:
            db.execute(text("DELETE FROM fechas_disponibles WHERE fecha < CURRENT_DATE"))
            db.execute(text("DELETE FROM slots_disponibles  WHERE fecha < CURRENT_DATE"))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"⚠️  No se pudieron limpiar las fechas vencidas: {e}")
    finally:
        db.close()

    tareas = [
        asyncio.create_task(vigilar_sesiones_inactivas()),
        asyncio.create_task(vigilar_citas_inasistidas()),
        asyncio.create_task(vigilar_citas_antiguas()),
        asyncio.create_task(vigilar_fechas_disponibles()),
    ]

    if settings.NGROK_ENABLED:
        # Ngrok arranca en segundo plano para no bloquear el servidor.
        # El import se hace AQUÍ (dentro del lifespan async), no al nivel de módulo,
        # para que los worker-processes del reloader nunca lo ejecuten.
        async def _arrancar_ngrok():
            try:
                from pyngrok import ngrok  # noqa: PLC0415
                logging.getLogger("pyngrok").setLevel(logging.CRITICAL)
                logging.getLogger("pyngrok.process").setLevel(logging.CRITICAL)
                tunnels = ngrok.get_tunnels()
                if tunnels:
                    public_url = tunnels[0].public_url
                    print(f"🔄 Ngrok reutilizado: {public_url}")
                else:
                    # Liberar cualquier ngrok huérfano de una ejecución previa
                    # que aún tenga tomado el dominio reservado.
                    _matar_ngrok_so()
                    public_url = await _conectar_ngrok_async(ngrok)
                    print(f"🌐 Ngrok activo: {public_url}")
    #            print(f"📱 Webhook: {public_url}/webhook  |  Token: {settings.VERIFY_TOKEN}")
            except Exception as e:
                print(f"⚠️  Ngrok no pudo conectar: {e}")

        tareas.append(asyncio.create_task(_arrancar_ngrok()))
        tareas.append(asyncio.create_task(vigilar_tunel_ngrok()))

    #print(f"⏰ Vigilancia de sesiones activa (timeout: {settings.SESSION_TIMEOUT_MINUTES} min)")
    #print("🏥 Vigilancia de inasistencias activa (cada 2 min, gracia: 5 min)")
    print("🚀 Servidor listo\n")

    yield

    for t in tareas:
        t.cancel()

    # Cerrar Ngrok al apagar el bot para no dejar un ngrok.exe huérfano que
    # siga ocupando el dominio (causa del error ERR_NGROK_334 al reiniciar).
    if settings.NGROK_ENABLED:
        try:
            from pyngrok import ngrok  # noqa: PLC0415
            ngrok.kill()
            _matar_ngrok_so()   # asegura que no quede ningún ngrok.exe huérfano
            print("🛑 Ngrok cerrado correctamente")
        except Exception as e:
            print(f"⚠️  No se pudo cerrar Ngrok limpiamente: {e}")

# ====================
# App
# ====================
app = FastAPI(
    title="ChatBot WhatsApp - Hospital",
    version="2.0.0",
    lifespan=lifespan,
)

# ─── Middleware: blindar el panel cuando el request viene por Internet ───────
# El bot expone dos superficies muy distintas: /webhook (público, lo necesita
# Meta) y todo lo demás (panel administrativo con datos de pacientes). Cuando
# se usa un túnel como ngrok, la misma URL sirve ambas cosas — este middleware
# corta ese solape: si el request llega por un host público (patrón configurado
# en settings.PUBLIC_HOST_PATTERN), solo /webhook responde; el resto devuelve
# 404 sin revelar que existe un panel detrás.
_public_host_rx = re.compile(settings.PUBLIC_HOST_PATTERN or r"$^", re.IGNORECASE)
_WEBHOOK_PATHS = ("/webhook",)  # match por igualdad o prefijo /webhook/xxx

class RestringirPanelDesdeInternet(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        host = (
            request.headers.get("x-forwarded-host")
            or request.headers.get("host")
            or ""
        ).lower()
        if host and _public_host_rx.search(host):
            path = request.url.path
            permitido = any(
                path == p or path.startswith(p + "/") for p in _WEBHOOK_PATHS
            )
            if not permitido:
                # 404 opaco: no confirma que exista un panel administrativo.
                return PlainTextResponse("Not Found", status_code=404)
        return await call_next(request)

app.add_middleware(RestringirPanelDesdeInternet)

app.include_router(auth_router)   # /admin/login, /logout, /me (sin sesión previa)
app.include_router(admin_router)  # resto del panel (exige sesión válida)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ====================
# Endpoints
# ====================
@app.get("/admin", include_in_schema=False)
async def admin_panel():
    # no-store evita que el navegador sirva una versión vieja del panel tras
    # actualizar static/admin.html (así no hay que forzar Ctrl+F5 cada vez).
    return FileResponse(
        "static/admin.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

@app.get("/")
async def root():
    return {"hospital": settings.HOSPITAL_NOMBRE, "status": "active"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    if mode == "subscribe" and token == settings.VERIFY_TOKEN:
        print(f"✅ Webhook verificado")
        return PlainTextResponse(challenge)
    print(f"❌ Verificación fallida — token recibido: {token}")
    return Response(content="Forbidden", status_code=403)

# ── Procesamiento en segundo plano ───────────────────────────────────────────
# El webhook responde 200 de INMEDIATO y el trabajo pesado (OCR, BD, envío a
# WhatsApp) corre en un hilo aparte, para no bloquear el event loop ni provocar
# reintentos de WhatsApp (que causaban el "congelamiento").
_tareas_webhook: set = set()          # referencias a tareas en curso (evita GC)
_ids_procesados: dict = {}            # id de mensaje -> tiempo (deduplicación)
_locks_telefono: dict = {}            # telefono -> asyncio.Lock (orden por usuario)


def _mensaje_duplicado(mid: str) -> bool:
    """True si el mensaje ya se procesó. WhatsApp reenvía/duplica mensajes."""
    if not mid:
        return False
    ahora = time.monotonic()
    if len(_ids_procesados) > 3000:   # limpieza de ids viejos (> 10 min)
        for k in [k for k, t in _ids_procesados.items() if ahora - t > 600]:
            _ids_procesados.pop(k, None)
    if mid in _ids_procesados:
        return True
    _ids_procesados[mid] = ahora
    return False


def _lock_telefono(telefono: str) -> asyncio.Lock:
    lock = _locks_telefono.get(telefono)
    if lock is None:
        lock = asyncio.Lock()
        _locks_telefono[telefono] = lock
    return lock


def _procesar_sincrono(telefono: str, clase: str, dato) -> None:
    """Trabajo bloqueante (OCR/BD/WhatsApp). Corre en un hilo, con su propia sesión."""
    db = SessionLocal()
    try:
        handler = ChatBotHandler(db)
        if clase == "text":
            handler.procesar_mensaje(telefono, mensaje=dato)
        elif clase == "button":
            handler.procesar_mensaje(telefono, button_id=dato)
        elif clase == "media":
            handler.procesar_media(telefono, dato["id"], dato["mime"])
    except Exception as e:
        print(f"❌ Error procesando mensaje de {telefono}: {e}")
        traceback.print_exc()
    finally:
        db.close()


async def _procesar_en_fondo(telefono: str, clase: str, dato) -> None:
    # Serializa por teléfono: los mensajes de un mismo usuario se procesan en orden,
    # así "varios documentos seguidos" no compiten entre sí ni corrompen la sesión.
    async with _lock_telefono(telefono):
        await asyncio.to_thread(_procesar_sincrono, telefono, clase, dato)


def _lanzar_fondo(coro) -> None:
    t = asyncio.create_task(coro)
    _tareas_webhook.add(t)
    t.add_done_callback(_tareas_webhook.discard)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored"}

    if body.get("object") != "whatsapp_business_account":
        return {"status": "ignored"}

    try:
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                for message in change.get("value", {}).get("messages", []):
                    if _mensaje_duplicado(message.get("id")):
                        continue
                    telefono = message.get("from")
                    mtype = message.get("type")
                    if not telefono:
                        continue
                    print(f"📩 De: {telefono} | Tipo: {mtype}")

                    if mtype == "text":
                        texto = message.get("text", {}).get("body", "")
                        _lanzar_fondo(_procesar_en_fondo(telefono, "text", texto))

                    elif mtype == "image":
                        img = message.get("image", {})
                        if img.get("id"):
                            _lanzar_fondo(_procesar_en_fondo(
                                telefono, "media",
                                {"id": img["id"], "mime": img.get("mime_type") or "image/jpeg"}))

                    elif mtype == "document":
                        doc = message.get("document", {})
                        if doc.get("id"):
                            _lanzar_fondo(_procesar_en_fondo(
                                telefono, "media",
                                {"id": doc["id"], "mime": doc.get("mime_type") or "application/pdf"}))

                    elif mtype == "interactive":
                        inter = message.get("interactive", {})
                        if inter.get("type") == "button_reply":
                            bid = inter.get("button_reply", {}).get("id")
                            if bid:
                                _lanzar_fondo(_procesar_en_fondo(telefono, "button", bid))
                        elif inter.get("type") == "list_reply":
                            lid = inter.get("list_reply", {}).get("id")
                            if lid:
                                _lanzar_fondo(_procesar_en_fondo(telefono, "button", lid))
    except Exception as e:
        print(f"❌ Error en webhook: {e}")
        traceback.print_exc()

    # Responder 200 SIEMPRE y de inmediato → WhatsApp no reintenta.
    return {"status": "success"}

# ====================
# Endpoints de Administración
# ====================
@app.get("/stats")
async def estadisticas(db: Session = Depends(get_db), _usuario: str = Depends(requerir_auth)):
    return {
        "pacientes_registrados": db.query(func.count(Paciente.id_paciente)).scalar(),
        "total_citas": db.query(func.count(Cita.id_cita)).scalar(),
        "citas_hoy": db.query(func.count(Cita.id_cita)).filter(
            Cita.fecha_cita == date.today(), Cita.estado == 'agendada'
        ).scalar(),
        "especialidades_activas": db.query(func.count(Especialidad.id_especialidad)).filter(
            Especialidad.activo == True
        ).scalar(),
        "hospital": settings.HOSPITAL_NOMBRE,
    }

@app.get("/pacientes")
async def listar_pacientes(db: Session = Depends(get_db), _usuario: str = Depends(requerir_auth)):
    return [
        {"id": p.id_paciente, "nombres": p.nombres, "apellidos": p.apellidos,
         "cedula": p.cedula, "celular": p.celular, "correo": p.correo}
        for p in db.query(Paciente).order_by(Paciente.created_at.desc()).limit(50).all()
    ]

@app.get("/citas")
async def listar_citas(db: Session = Depends(get_db), _usuario: str = Depends(requerir_auth)):
    return [
        {"id": c.id_cita,
         "paciente": f"{c.paciente.nombres} {c.paciente.apellidos}",
         "especialidad": c.especialidad.nombre,
         "medico": f"Dr(a). {c.medico.nombres} {c.medico.apellidos}",
         "fecha": str(c.fecha_cita), "hora": str(c.hora_cita), "estado": c.estado}
        for c in db.query(Cita).filter(
            Cita.fecha_cita >= date.today()
        ).order_by(Cita.fecha_cita, Cita.hora_cita).limit(50).all()
    ]

@app.get("/especialidades")
async def listar_especialidades(db: Session = Depends(get_db), _usuario: str = Depends(requerir_auth)):
    return [
        {"id": e.id_especialidad, "nombre": e.nombre, "descripcion": e.descripcion}
        for e in db.query(Especialidad).filter(
            Especialidad.activo == True
        ).order_by(Especialidad.nombre).all()
    ]

# ====================
# Ejecutar
# ====================
if __name__ == "__main__":
    if settings.RELOAD:
        # Recarga automática: al guardar cualquier archivo .py el programa se
        # reinicia solo (uvicorn --reload). En Windows cada reinicio reimporta
        # el módulo (arranque un poco más lento), pero se actualiza sin que
        # tengas que pararlo y volver a arrancarlo a mano.
        #print("🔁 Recarga automática ACTIVA — el bot se reiniciará solo al guardar cambios en el código (.py).")
        uvicorn.run(
            "bot_main:app",
            host=settings.HOST,
            port=settings.PORT,
            reload=True,
            reload_dirs=["."],
            reload_includes=["*.py"],
            reload_excludes=[
                "venv/*", "venv/**/*",
                "node_modules/*", "node_modules/**/*",
                ".git/*", ".git/**/*",
                "static/*", "__pycache__/*",
                "*.pyc", "*.pyo", "*.log",
            ],
            reload_delay=1.0,
            log_level="info",
        )
    else:
        # Modo rápido (por defecto): se pasa el objeto `app` ya importado, sin
        # reloader ni subproceso → el servidor queda listo en cuanto termina
        # la inicialización (sin reimportar todos los módulos otra vez).
        uvicorn.run(
            app,
            host=settings.HOST,
            port=settings.PORT,
            log_level="info",
        )

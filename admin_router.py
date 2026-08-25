"""
Router de administración – CRUD completo para el panel web del hospital.
"""
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Cookie, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, desc, text
from sqlalchemy.orm import Session

from database import get_db
from bot_models import Cita, Especialidad, FechaDisponible, HorarioMedico, Medico, Paciente, Eps, MetricaAgendamiento
from bot_config import get_settings
from auth_admin import (
    requerir_auth, credenciales_validas, establecer_cookie,
    limpiar_cookie, verificar_token,
)
from reset_sistema import (
    reiniciar_sistema, eliminar_todos_pacientes, eliminar_todos_medicos,
    archivar_citas_antiguas,
    _asegurar_historico, _asegurar_historico_pacientes,
    _COLS_CITA, _SELECT_COLS, _COLS_PACIENTE,
)

# Citas cuya fecha ya pasó hace más de estos días se archivan solas.
DIAS_ARCHIVAR_CITAS = 7

settings = get_settings()

# ─── Router de autenticación (SIN guard: login/logout/estado de sesión) ───────
auth_router = APIRouter(prefix="/admin", tags=["auth"])


class LoginRequest(BaseModel):
    usuario: str
    password: str


@auth_router.post("/login")
def login(data: LoginRequest, response: Response):
    """Valida credenciales y entrega la cookie de sesión firmada."""
    if not credenciales_validas(data.usuario, data.password):
        raise HTTPException(401, "Usuario o contraseña incorrectos.")
    establecer_cookie(response, data.usuario)
    return {"ok": True, "usuario": data.usuario}


@auth_router.post("/logout")
def logout(response: Response):
    """Cierra la sesión borrando la cookie."""
    limpiar_cookie(response)
    return {"ok": True}


@auth_router.get("/me")
def me(hospital_admin_session: str = Cookie(default=None)):
    """Indica si la sesión actual es válida (usado por el frontend al arrancar)."""
    usuario = verificar_token(hospital_admin_session)
    if not usuario:
        raise HTTPException(401, "No autenticado.")
    return {"usuario": usuario}


# ─── Router principal del panel (TODAS las rutas exigen sesión válida) ────────
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(requerir_auth)],
)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_datos(valor: Optional[str]) -> Optional[dict]:
    """Convierte el JSON de datos OCR guardado en la cita a dict (o None)."""
    if not valor:
        return None
    try:
        d = json.loads(valor)
        return d if isinstance(d, dict) and d else None
    except Exception:
        return None

def _reset_sequence(db: Session, table: str, pk_col: str) -> None:
    """
    Reinicia la secuencia de PostgreSQL al valor máximo actual del PK,
    de modo que el próximo INSERT tome el primer ID disponible tras el
    último registro existente y no genere saltos innecesarios.
    """
    db.execute(text(
        f"SELECT setval("
        f"  pg_get_serial_sequence('{table}', '{pk_col}'), "
        f"  COALESCE((SELECT MAX({pk_col}) FROM {table}), 0)"
        f")"
    ))

def _menor_id_libre(db: Session, table: str, pk_col: str) -> int:
    """
    Devuelve el menor entero >=1 que no está siendo usado como PK en la tabla.
    Rellena huecos dejados por DELETEs antes de crecer: los IDs se mantienen
    lo más pequeños posible. Delega a la función SQL `menor_id_libre`
    definida en sql_db.sql. Si la tabla está vacía, devuelve 1.
    """
    return int(db.execute(
        text("SELECT menor_id_libre(:t, :c)"),
        {"t": table, "c": pk_col},
    ).scalar() or 1)

# ─── Schemas ─────────────────────────────────────────────────────────────────

class MedicoCreate(BaseModel):
    nombres: str
    apellidos: str
    registro_medico: Optional[str] = None  # se asigna automáticamente (menor libre)
    id_especialidad: int
    activo: bool = True

class MedicoUpdate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    registro_medico: Optional[str] = None
    id_especialidad: Optional[int] = None
    activo: Optional[bool] = None

class EspecialidadCreate(BaseModel):
    nombre: str
    descripcion: Optional[str] = None
    activo: bool = True

class EspecialidadUpdate(BaseModel):
    nombre: Optional[str] = None
    descripcion: Optional[str] = None
    activo: Optional[bool] = None

class PacienteUpdate(BaseModel):
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    cedula: Optional[str] = None
    celular: Optional[str] = None
    correo: Optional[str] = None
    id_eps: Optional[int] = None

class EpsCreate(BaseModel):
    nombre: str
    requiere_orden: bool = True
    requiere_autorizacion: bool = True
    autorizacion_opcional: bool = False
    activo: bool = True

class EpsUpdate(BaseModel):
    nombre: Optional[str] = None
    requiere_orden: Optional[bool] = None
    requiere_autorizacion: Optional[bool] = None
    autorizacion_opcional: Optional[bool] = None
    activo: Optional[bool] = None

class FechaCreate(BaseModel):
    fecha: date
    cupos_disponibles: int = 50
    activo: bool = True

class FechaUpdate(BaseModel):
    activo: Optional[bool] = None
    cupos_disponibles: Optional[int] = None

class HorarioCreate(BaseModel):
    id_medico: int
    dia_semana: int
    hora_inicio: str   # "HH:MM"
    hora_fin: str      # "HH:MM"
    activo: bool = True

class HorarioUpdate(BaseModel):
    dia_semana: Optional[int] = None
    hora_inicio: Optional[str] = None
    hora_fin: Optional[str] = None
    activo: Optional[bool] = None

class ResetRequest(BaseModel):
    password: str

# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    # Archiva y saca del panel las citas cuya fecha pasó hace más de 7 días.
    archivar_citas_antiguas(db, DIAS_ARCHIVAR_CITAS)
    db.commit()
    today = date.today()
    # Prioridad de visualización en el dashboard:
    #   0) PENDIENTES (requieren confirmación manual del hospital) — primero
    #   1) agendadas, de la más próxima a la más alejada (fecha ascendente)
    #   2) inasistidas (más recientes primero)
    #   3) completadas (más recientes primero)
    # Se toman hasta 10 citas en total.
    pendientes = (
        db.query(Cita).filter(Cita.estado == "pendiente")
        .order_by(desc(Cita.created_at)).limit(10).all()
    )
    agendadas = (
        db.query(Cita).filter(Cita.estado == "agendada")
        .order_by(Cita.fecha_cita.asc(), Cita.hora_cita.asc()).limit(10).all()
    )
    inasistidas = (
        db.query(Cita).filter(Cita.estado == "inasistida")
        .order_by(desc(Cita.fecha_cita), desc(Cita.hora_cita)).limit(10).all()
    )
    completadas = (
        db.query(Cita).filter(Cita.estado == "completada")
        .order_by(desc(Cita.fecha_cita), desc(Cita.hora_cita)).limit(10).all()
    )
    recientes = (pendientes + agendadas + inasistidas + completadas)[:10]

    # Métricas para las tarjetas del dashboard.
    prom_estrellas = db.query(func.avg(MetricaAgendamiento.estrellas)).filter(
        MetricaAgendamiento.estrellas.isnot(None)
    ).scalar()
    total_calif = db.query(func.count()).select_from(MetricaAgendamiento).filter(
        MetricaAgendamiento.estrellas.isnot(None)
    ).scalar()
    prom_tiempo = db.query(func.avg(MetricaAgendamiento.duracion_seg)).filter(
        MetricaAgendamiento.duracion_seg.isnot(None)
    ).scalar()
    prom_confirmacion = db.query(func.avg(MetricaAgendamiento.tiempo_confirmacion_seg)).filter(
        MetricaAgendamiento.tiempo_confirmacion_seg.isnot(None)
    ).scalar()

    return {
        "satisfaccion_promedio": round(float(prom_estrellas), 1) if prom_estrellas is not None else None,
        "satisfaccion_total": total_calif,
        "tiempo_promedio_seg": int(prom_tiempo) if prom_tiempo is not None else None,
        "tiempo_confirmacion_promedio_seg": int(prom_confirmacion) if prom_confirmacion is not None else None,
        "total_pacientes": db.query(func.count(Paciente.id_paciente)).scalar(),
        "citas_pendientes": db.query(func.count(Cita.id_cita)).filter(
            Cita.estado == "pendiente"
        ).scalar(),
        "citas_hoy": db.query(func.count(Cita.id_cita)).filter(
            Cita.fecha_cita == today, Cita.estado == "agendada"
        ).scalar(),
        "citas_mes": db.query(func.count(Cita.id_cita)).filter(
            func.extract("month", Cita.fecha_cita) == today.month,
            func.extract("year", Cita.fecha_cita) == today.year,
            Cita.estado == "agendada",
        ).scalar(),
        "medicos_activos": db.query(func.count(Medico.id_medico)).filter(
            Medico.activo == True
        ).scalar(),
        "especialidades_activas": db.query(func.count(Especialidad.id_especialidad)).filter(
            Especialidad.activo == True
        ).scalar(),
        "citas_recientes": [
            {
                "id": c.id_cita,
                "paciente": f"{c.paciente.nombres} {c.paciente.apellidos}",
                "especialidad": c.especialidad.nombre,
                "medico": f"Dr(a). {c.medico.nombres} {c.medico.apellidos}",
                "fecha": str(c.fecha_cita),
                "hora": str(c.hora_cita)[:5],
                "estado": c.estado,
            }
            for c in recientes
        ],
    }

# ─── Métricas: satisfacción y tiempos de agendamiento ────────────────────────

@router.get("/metricas")
def metricas(db: Session = Depends(get_db)):
    califadas = MetricaAgendamiento.estrellas.isnot(None)
    con_tiempo = MetricaAgendamiento.duracion_seg.isnot(None)
    con_confirmacion = MetricaAgendamiento.tiempo_confirmacion_seg.isnot(None)

    total_calif = db.query(func.count()).select_from(MetricaAgendamiento).filter(califadas).scalar()
    prom = db.query(func.avg(MetricaAgendamiento.estrellas)).filter(califadas).scalar()
    distrib = {str(i): 0 for i in range(1, 6)}
    for e, c in (db.query(MetricaAgendamiento.estrellas, func.count())
                 .filter(califadas).group_by(MetricaAgendamiento.estrellas).all()):
        distrib[str(int(e))] = c

    # Tiempos de agendamiento (chatbot)
    total_t = db.query(func.count()).select_from(MetricaAgendamiento).filter(con_tiempo).scalar()
    avg_t = db.query(func.avg(MetricaAgendamiento.duracion_seg)).filter(con_tiempo).scalar()
    min_t = db.query(func.min(MetricaAgendamiento.duracion_seg)).filter(con_tiempo).scalar()
    max_t = db.query(func.max(MetricaAgendamiento.duracion_seg)).filter(con_tiempo).scalar()

    # Tiempos de confirmación (personal administrativo)
    total_conf = db.query(func.count()).select_from(MetricaAgendamiento).filter(con_confirmacion).scalar()
    avg_conf = db.query(func.avg(MetricaAgendamiento.tiempo_confirmacion_seg)).filter(con_confirmacion).scalar()
    min_conf = db.query(func.min(MetricaAgendamiento.tiempo_confirmacion_seg)).filter(con_confirmacion).scalar()
    max_conf = db.query(func.max(MetricaAgendamiento.tiempo_confirmacion_seg)).filter(con_confirmacion).scalar()

    recientes = (db.query(MetricaAgendamiento)
                 .order_by(desc(MetricaAgendamiento.created_at)).limit(15).all())

    def _nombre(m):
        if m.id_paciente:
            p = db.query(Paciente).get(m.id_paciente)
            if p:
                return f"{p.nombres} {p.apellidos}"
        return m.telefono or "—"

    return {
        "satisfaccion": {
            "total": total_calif,
            "promedio": round(float(prom), 2) if prom is not None else None,
            "distribucion": distrib,
        },
        "tiempos": {
            "total": total_t,
            "promedio_seg": int(avg_t) if avg_t is not None else None,
            "min_seg": int(min_t) if min_t is not None else None,
            "max_seg": int(max_t) if max_t is not None else None,
        },
        "tiempo_confirmacion": {
            "total": total_conf,
            "promedio_seg": int(avg_conf) if avg_conf is not None else None,
            "min_seg": int(min_conf) if min_conf is not None else None,
            "max_seg": int(max_conf) if max_conf is not None else None,
        },
        "recientes": [
            {
                "id_cita": m.id_cita,
                "paciente": _nombre(m),
                "estrellas": m.estrellas,
                "duracion_seg": m.duracion_seg,
                "tiempo_confirmacion_seg": m.tiempo_confirmacion_seg,
                "fecha": str(m.created_at)[:16] if m.created_at else "",
            }
            for m in recientes
        ],
    }

# ─── Sistema (reinicio protegido) ─────────────────────────────────────────────

@router.post("/sistema/reset")
def reset_sistema_web(data: ResetRequest, db: Session = Depends(get_db)):
    """
    Reinicio protegido por contraseña: archiva las citas en historico_citas,
    borra las citas, reinicia id_cita a 1 y renumera los médicos a 1..N.
    Misma lógica que el ejecutable reset_sistema.py.
    """
    if data.password != settings.ADMIN_RESET_PASSWORD:
        raise HTTPException(403, "Contraseña incorrecta. Reinicio cancelado.")
    try:
        resultado = reiniciar_sistema(db)
        db.commit()
        return {"ok": True, **resultado}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error durante el reinicio: {str(e)}")

@router.post("/sistema/eliminar_pacientes")
def eliminar_pacientes_web(data: ResetRequest, db: Session = Depends(get_db)):
    """
    Elimina TODOS los registros de pacientes (protegido por contraseña).
    Archiva las citas en historico_citas antes de borrarlas.
    """
    if data.password != settings.ADMIN_RESET_PASSWORD:
        raise HTTPException(403, "Contraseña incorrecta. Operación cancelada.")
    try:
        resultado = eliminar_todos_pacientes(db)
        db.commit()
        return {"ok": True, **resultado}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error eliminando pacientes: {str(e)}")

@router.post("/sistema/eliminar_medicos")
def eliminar_medicos_web(data: ResetRequest, db: Session = Depends(get_db)):
    """
    Elimina TODOS los médicos y sus horarios (protegido por contraseña).
    Archiva las citas en historico_citas antes de borrarlas.
    """
    if data.password != settings.ADMIN_RESET_PASSWORD:
        raise HTTPException(403, "Contraseña incorrecta. Operación cancelada.")
    try:
        resultado = eliminar_todos_medicos(db)
        db.commit()
        return {"ok": True, **resultado}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error eliminando médicos: {str(e)}")

# ─── Histórico de citas (solo lectura) ─────────────────────────────────────────

def _ensure_historico(db: Session) -> bool:
    """Garantiza que exista la tabla historico_citas con sus columnas.
    Devuelve False si no existe la tabla 'citas' base (sistema sin inicializar)."""
    db.execute(text("CREATE TABLE IF NOT EXISTS historico_citas (LIKE citas INCLUDING DEFAULTS)"))
    for col, typ in (
        ("archivado_en", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("paciente_nombre", "TEXT"),
        ("especialidad_nombre", "TEXT"),
        ("medico_nombre", "TEXT"),
    ):
        db.execute(text(f"ALTER TABLE historico_citas ADD COLUMN IF NOT EXISTS {col} {typ}"))
    db.commit()
    return True

@router.get("/historico")
def listar_historico(
    buscar: Optional[str] = None,
    estado: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """Consulta de solo lectura del archivo histórico de citas."""
    _ensure_historico(db)

    where = " WHERE 1=1"
    params: dict = {}
    if estado:
        where += " AND h.estado = :estado"
        params["estado"] = estado
    if buscar:
        where += (" AND (COALESCE(h.paciente_nombre, '') ILIKE :q "
                  "OR COALESCE(p.cedula, '') ILIKE :q "
                  "OR COALESCE(h.medico_nombre, '') ILIKE :q)")
        params["q"] = f"%{buscar}%"

    base_from = (
        " FROM historico_citas h "
        " LEFT JOIN pacientes p ON p.id_paciente = h.id_paciente "
        " LEFT JOIN especialidades e ON e.id_especialidad = h.id_especialidad "
        " LEFT JOIN medicos m ON m.id_medico = h.id_medico "
        + where
    )

    total = db.execute(text("SELECT COUNT(*)" + base_from), params).scalar()

    filas = db.execute(text(
        "SELECT h.id_cita, "
        "       COALESCE(h.paciente_nombre, p.nombres || ' ' || p.apellidos, '—') AS paciente, "
        "       p.cedula AS cedula, "
        "       COALESCE(h.especialidad_nombre, e.nombre, '—') AS especialidad, "
        "       COALESCE(h.medico_nombre, 'Dr(a). ' || m.nombres || ' ' || m.apellidos, '—') AS medico, "
        "       h.fecha_cita, h.hora_cita, h.turno, h.estado, h.tipo_servicio, h.archivado_en "
        + base_from +
        " ORDER BY h.archivado_en DESC NULLS LAST, h.fecha_cita DESC, h.hora_cita DESC "
        " OFFSET :skip LIMIT :limit",
    ), {**params, "skip": skip, "limit": limit}).mappings().all()

    return {
        "total": total,
        "items": [
            {
                "id": r["id_cita"],
                "paciente": r["paciente"],
                "cedula": r["cedula"] or "—",
                "especialidad": r["especialidad"],
                "medico": r["medico"],
                "fecha": str(r["fecha_cita"]),
                "hora": str(r["hora_cita"])[:5],
                "turno": r["turno"] or "—",
                "estado": r["estado"],
                "tipo_servicio": r["tipo_servicio"] or "—",
                "archivado": str(r["archivado_en"])[:19] if r["archivado_en"] else "—",
            }
            for r in filas
        ],
    }

# ─── Citas ───────────────────────────────────────────────────────────────────

@router.post("/citas/actualizar_inasistencias")
def actualizar_inasistencias(db: Session = Depends(get_db)):
    """
    Marca como 'inasistida' toda cita agendada cuya fecha+hora superó los
    5 minutos de gracia. Usa UPDATE directo en SQL para mayor eficiencia.
    Este mismo criterio lo aplica la tarea de fondo en bot_main.py.
    """
    try:
        result = db.execute(
            text("""
                UPDATE citas
                SET estado = 'inasistida', updated_at = NOW()
                WHERE estado = 'agendada'
                  AND (fecha_cita + hora_cita + INTERVAL '5 minutes') < NOW()
            """)
        )
        db.commit()
        return {"actualizadas": result.rowcount}
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Error actualizando inasistencias: {str(e)}")

@router.get("/citas/pendientes/contador")
def contador_citas_pendientes(db: Session = Depends(get_db)):
    """
    Endpoint LIGERO que solo devuelve el numero de citas en estado 'pendiente'.
    Se usa para el polling del panel (cada 30 s) y para disparar notificaciones
    del navegador cuando llegan nuevas solicitudes de agendamiento sin necesidad
    de recargar todo el dashboard.
    """
    n = db.query(func.count(Cita.id_cita)).filter(Cita.estado == "pendiente").scalar()
    return {"pendientes": int(n or 0)}

@router.get("/citas")
def listar_citas(
    estado: Optional[str] = None,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
    buscar: Optional[str] = None,
    id_especialidad: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    # Archiva y saca de la vista las citas cuya fecha pasó hace más de 7 días.
    archivar_citas_antiguas(db, DIAS_ARCHIVAR_CITAS)
    db.commit()
    q = (
        db.query(Cita)
        .join(Cita.paciente)
        .join(Cita.especialidad)
        .join(Cita.medico)
    )
    if estado:
        q = q.filter(Cita.estado == estado)
    if fecha_desde:
        q = q.filter(Cita.fecha_cita >= fecha_desde)
    if fecha_hasta:
        q = q.filter(Cita.fecha_cita <= fecha_hasta)
    if id_especialidad:
        q = q.filter(Cita.id_especialidad == id_especialidad)
    if buscar:
        q = q.filter(
            or_(
                Paciente.nombres.ilike(f"%{buscar}%"),
                Paciente.apellidos.ilike(f"%{buscar}%"),
                Paciente.cedula.ilike(f"%{buscar}%"),
            )
        )
    total = q.count()
    # Las últimas citas agendadas (las más recientes) primero.
    citas = q.order_by(desc(Cita.created_at), desc(Cita.id_cita)).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": c.id_cita,
                "paciente": f"{c.paciente.nombres} {c.paciente.apellidos}",
                "cedula": c.paciente.cedula,
                "celular": c.paciente.celular,
                "especialidad": c.especialidad.nombre,
                "medico": f"Dr(a). {c.medico.nombres} {c.medico.apellidos}",
                "fecha": str(c.fecha_cita),
                "hora": str(c.hora_cita)[:5],
                "turno": c.turno or "—",
                "estado": c.estado,
                "tipo_servicio": c.tipo_servicio,
                "tipo_cita": ("Primera vez" if c.tipo_cita == "primera_vez"
                              else "Control" if c.tipo_cita == "control" else "—"),
                "numero_orden": c.numero_orden or "—",
                "codigo_procedimiento": c.codigo_procedimiento or "—",
                "doc_orden": (f"/static/{c.doc_orden}" if c.doc_orden else None),
                "doc_autorizacion": (f"/static/{c.doc_autorizacion}" if c.doc_autorizacion else None),
                "doc_orden_datos": _parse_datos(c.doc_orden_datos),
                "doc_autorizacion_datos": _parse_datos(c.doc_autorizacion_datos),
            }
            for c in citas
        ],
    }

@router.put("/citas/{id_cita}/asistencia")
def marcar_asistencia_cita(id_cita: int, db: Session = Depends(get_db)):
    """Marca una cita como 'completada' (el paciente sí asistió)."""
    cita = db.query(Cita).filter(Cita.id_cita == id_cita).first()
    if not cita:
        raise HTTPException(404, "Cita no encontrada")
    if cita.estado == "cancelada":
        raise HTTPException(400, "No se puede registrar asistencia en una cita cancelada")
    cita.estado = "completada"
    cita.updated_at = datetime.now()
    db.commit()
    return {"ok": True}

@router.put("/citas/{id_cita}/confirmar")
def confirmar_cita_hospital(id_cita: int, db: Session = Depends(get_db)):
    """
    Confirma manualmente una cita pendiente (verificados los documentos):
    la pasa a 'agendada' y envía la confirmación por WhatsApp al paciente.
    También registra el tiempo de confirmación en la métrica.
    """
    cita = db.query(Cita).filter(Cita.id_cita == id_cita).first()
    if not cita:
        raise HTTPException(404, "Cita no encontrada")
    if cita.estado != "pendiente":
        raise HTTPException(400, "Solo se pueden confirmar citas en estado 'pendiente'")

    ahora = datetime.now()
    cita.estado = "agendada"
    cita.updated_at = ahora

    # Calcular tiempo de confirmación: desde created_at hasta ahora
    tiempo_confirmacion_seg = None
    if cita.created_at:
        delta = ahora - cita.created_at
        tiempo_confirmacion_seg = max(0, int(delta.total_seconds()))

    # Actualizar la métrica con el tiempo de confirmación
    metrica = db.query(MetricaAgendamiento).filter(
        MetricaAgendamiento.id_cita == id_cita
    ).first()
    if metrica:
        metrica.tiempo_confirmacion_seg = tiempo_confirmacion_seg

    db.commit()

    # UN SOLO mensaje al paciente confirmando el agendamiento definitivo.
    tel = cita.telefono_whatsapp or (cita.paciente.celular if cita.paciente else None)
    enviado = False
    if tel:
        try:
            from bot_handler import WhatsAppButtonsAPI
            msg = (
                "✅ *¡CITA AGENDADA!*\n\n"
                "Tu cita médica fue *confirmada por el personal del hospital* "
                "y quedó agendada oficialmente.\n\n"
                f"📋 *Código de cita:* #{cita.id_cita}\n"
                f"🏥 Especialidad: {cita.especialidad.nombre}\n"
                f"👨‍⚕️ Médico: Dr(a). {cita.medico.nombres} {cita.medico.apellidos}\n"
                f"📅 Fecha: {cita.fecha_cita.strftime('%d/%m/%Y')}\n"
                f"🕐 Hora: {str(cita.hora_cita)[:5]}\n\n"
                f"📍 *Llega 15 minutos antes* de tu cita.\n"
                f"🏥 {settings.HOSPITAL_NOMBRE}\n\n"
                "¡Te esperamos! 🙌"
            )
            enviado = WhatsAppButtonsAPI.enviar_mensaje_texto(tel, msg)
        except Exception as e:
            print(f"⚠️ No se pudo enviar la confirmación por WhatsApp: {e}")
    return {"ok": True, "whatsapp_enviado": bool(enviado)}

@router.put("/citas/{id_cita}/cancelar")
def cancelar_cita(id_cita: int, db: Session = Depends(get_db)):
    """
    Cancela / rechaza una cita desde el panel administrativo. Envía UN SOLO
    mensaje al paciente por WhatsApp explicando qué pasó y invitandolo a
    volver a agendar. Diferencia el texto según el estado anterior:
      - 'pendiente'  → la SOLICITUD fue rechazada (nunca llegó a agendarse).
      - 'agendada'   → la CITA (ya confirmada) tuvo que cancelarse.
    """
    cita = db.query(Cita).filter(Cita.id_cita == id_cita).first()
    if not cita:
        raise HTTPException(404, "Cita no encontrada")
    if cita.estado not in ("agendada", "pendiente"):
        raise HTTPException(400, "Solo se pueden cancelar citas pendientes o agendadas")

    estado_anterior = cita.estado
    cita.estado = "cancelada"
    cita.motivo_cancelacion = "Cancelada/rechazada por administrador"
    cita.updated_at = datetime.now()
    db.commit()

    # UN SOLO mensaje al paciente por WhatsApp, adaptado al caso.
    tel = cita.telefono_whatsapp or (cita.paciente.celular if cita.paciente else None)
    enviado = False
    if tel:
        try:
            from bot_handler import WhatsAppButtonsAPI
            detalles = (
                f"📋 *Código:* #{cita.id_cita}\n"
                f"🏥 {cita.especialidad.nombre}\n"
                f"👨‍⚕️ Dr(a). {cita.medico.nombres} {cita.medico.apellidos}\n"
                f"📅 {cita.fecha_cita.strftime('%d/%m/%Y')}\n"
                f"🕐 {str(cita.hora_cita)[:5]}"
            )
            if estado_anterior == "pendiente":
                msg = (
                    "❌ *SOLICITUD DE CITA RECHAZADA*\n\n"
                    "Tu solicitud de cita *no fue confirmada* por el personal "
                    "del hospital y quedó cancelada.\n\n"
                    f"{detalles}\n\n"
                    "🔁 *Puedes intentar agendar de nuevo* escribiéndonos por "
                    "este mismo WhatsApp. Revisa que tus documentos (orden "
                    "médica y autorización) estén claros y actualizados.\n\n"
                    f"📞 Si necesitas ayuda, comunícate con un asesor del hospital:\n"
                    f"☎️ {settings.HOSPITAL_TELEFONO}"
                )
            else:  # estado_anterior == "agendada"
                msg = (
                    "❌ *CITA CANCELADA*\n\n"
                    "Tu cita médica fue *cancelada* por el hospital.\n\n"
                    f"{detalles}\n\n"
                    "🔁 *Puedes agendar una nueva cita* escribiéndonos por "
                    "este mismo WhatsApp cuando lo necesites.\n\n"
                    f"📞 Si necesitas ayuda o quieres saber el motivo, "
                    f"comunícate con un asesor del hospital:\n"
                    f"☎️ {settings.HOSPITAL_TELEFONO}"
                )
            enviado = WhatsAppButtonsAPI.enviar_mensaje_texto(tel, msg)
        except Exception as e:
            print(f"⚠️ No se pudo enviar la cancelación por WhatsApp: {e}")
    return {"ok": True, "whatsapp_enviado": bool(enviado), "estado_anterior": estado_anterior}

# Nota: el borrado individual de citas se eliminó a propósito. Desde el panel
# web solo se permite CANCELAR citas (quedan en estado 'cancelada' y siguen en
# el sistema). El borrado masivo + reinicio de IDs se hace con reset_sistema.py,
# que además archiva el histórico en 'historico_citas'.

# ─── Médicos ─────────────────────────────────────────────────────────────────

@router.get("/medicos")
def listar_medicos(
    buscar: Optional[str] = None,
    id_especialidad: Optional[int] = None,
    activo: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Medico)
    if buscar:
        q = q.filter(
            or_(
                Medico.nombres.ilike(f"%{buscar}%"),
                Medico.apellidos.ilike(f"%{buscar}%"),
            )
        )
    if id_especialidad:
        q = q.filter(Medico.id_especialidad == id_especialidad)
    if activo is not None:
        q = q.filter(Medico.activo == activo)
    return [
        {
            "id": m.id_medico,
            "nombres": m.nombres,
            "apellidos": m.apellidos,
            "registro_medico": m.registro_medico,
            "id_especialidad": m.id_especialidad,
            "especialidad": m.especialidad.nombre if m.especialidad else "",
            "activo": m.activo,
        }
        for m in q.order_by(Medico.apellidos).all()
    ]

def _siguiente_registro(db: Session) -> str:
    """
    Calcula el MENOR número de registro libre con formato RM-NNN (3 cifras).
    Reutiliza huecos dejados por médicos borrados; si no hay, toma el siguiente.
    """
    usados = set()
    for (reg,) in db.execute(
        text(r"SELECT registro_medico FROM medicos WHERE registro_medico ~ '^RM-[0-9]+$'")
    ).all():
        try:
            usados.add(int(reg.split("-")[1]))
        except (ValueError, IndexError):
            pass
    n = 1
    while n in usados:
        n += 1
    return f"RM-{n:03d}"

@router.get("/medicos/siguiente_registro")
def medico_siguiente_registro(db: Session = Depends(get_db)):
    """Devuelve el próximo número de registro que se asignaría (informativo)."""
    return {"registro_medico": _siguiente_registro(db)}

@router.post("/medicos", status_code=201)
def crear_medico(data: MedicoCreate, db: Session = Depends(get_db)):
    if not db.query(Especialidad).filter(Especialidad.id_especialidad == data.id_especialidad).first():
        raise HTTPException(400, "La especialidad no existe")
    # El número de registro se asigna SIEMPRE automáticamente (menor libre);
    # se ignora cualquier valor enviado por el cliente.
    registro = _siguiente_registro(db)
    # Asignar el MENOR id_medico libre (rellena huecos dejados por médicos borrados)
    m = Medico(
        id_medico=_menor_id_libre(db, "medicos", "id_medico"),
        nombres=data.nombres,
        apellidos=data.apellidos,
        registro_medico=registro,
        id_especialidad=data.id_especialidad,
        activo=data.activo,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    # Mantener la secuencia alineada con el máximo actual y renumerar los RM
    # de todos los médicos según id_medico ascendente (RM-001, RM-002, …).
    _reset_sequence(db, "medicos", "id_medico")
    db.execute(text("SELECT renumerar_registros_medicos()"))
    db.commit()
    db.refresh(m)
    return {"id": m.id_medico, "registro_medico": m.registro_medico, "ok": True}

@router.put("/medicos/{id_medico}")
def actualizar_medico(id_medico: int, data: MedicoUpdate, db: Session = Depends(get_db)):
    m = db.query(Medico).filter(Medico.id_medico == id_medico).first()
    if not m:
        raise HTTPException(404, "Médico no encontrado")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    db.commit()
    return {"ok": True}

@router.delete("/medicos/{id_medico}")
def eliminar_medico(id_medico: int, db: Session = Depends(get_db)):
    m = db.query(Medico).filter(Medico.id_medico == id_medico).first()
    if not m:
        raise HTTPException(404, "Médico no encontrado")
    citas_activas = (
        db.query(func.count(Cita.id_cita))
        .filter(
            Cita.id_medico == id_medico,
            Cita.estado == "agendada",
            Cita.fecha_cita >= date.today(),
        )
        .scalar()
    )
    if citas_activas:
        raise HTTPException(
            400,
            f"El médico tiene {citas_activas} cita(s) activa(s). Cancélalas primero.",
        )
    db.query(HorarioMedico).filter(HorarioMedico.id_medico == id_medico).delete()
    db.delete(m)
    db.commit()
    _reset_sequence(db, "medicos", "id_medico")
    _reset_sequence(db, "horarios_medicos", "id_horario")
    # Renumerar RM tras la baja para mantener la serie 001, 002, … consecutiva.
    db.execute(text("SELECT renumerar_registros_medicos()"))
    db.commit()
    return {"ok": True}

# ─── Pacientes ───────────────────────────────────────────────────────────────

@router.get("/pacientes")
def listar_pacientes(
    buscar: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Paciente)
    if buscar:
        q = q.filter(
            or_(
                Paciente.nombres.ilike(f"%{buscar}%"),
                Paciente.apellidos.ilike(f"%{buscar}%"),
                Paciente.cedula.ilike(f"%{buscar}%"),
                Paciente.celular.ilike(f"%{buscar}%"),
            )
        )
    total = q.count()
    pacientes = q.order_by(desc(Paciente.created_at)).offset(skip).limit(limit).all()
    return {
        "total": total,
        "items": [
            {
                "id": p.id_paciente,
                "nombres": p.nombres,
                "apellidos": p.apellidos,
                "cedula": p.cedula,
                "celular": p.celular,
                "correo": p.correo or "",
                "id_eps": p.id_eps,
                "eps": p.eps.nombre if p.eps else "",
                "created_at": str(p.created_at)[:10] if p.created_at else "",
                "total_citas": db.query(func.count(Cita.id_cita))
                    .filter(Cita.id_paciente == p.id_paciente)
                    .scalar(),
            }
            for p in pacientes
        ],
    }

@router.put("/pacientes/{id_paciente}")
def actualizar_paciente(id_paciente: int, data: PacienteUpdate, db: Session = Depends(get_db)):
    p = db.query(Paciente).filter(Paciente.id_paciente == id_paciente).first()
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if data.cedula and data.cedula != p.cedula:
        if db.query(Paciente).filter(Paciente.cedula == data.cedula).first():
            raise HTTPException(400, "Ya existe un paciente con esa cédula")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return {"ok": True}

@router.delete("/pacientes/{id_paciente}")
def eliminar_paciente(id_paciente: int, db: Session = Depends(get_db)):
    p = db.query(Paciente).filter(Paciente.id_paciente == id_paciente).first()
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    citas_activas = (
        db.query(func.count(Cita.id_cita))
        .filter(Cita.id_paciente == id_paciente, Cita.estado == "agendada")
        .scalar()
    )
    if citas_activas:
        raise HTTPException(
            400,
            f"El paciente tiene {citas_activas} cita(s) activa(s). Cancélalas primero."
        )
    # Archivar en el histórico antes de borrar: el paciente y sus citas.
    _asegurar_historico(db)
    _asegurar_historico_pacientes(db)
    db.execute(text(
        f"INSERT INTO historico_citas ({_COLS_CITA}, paciente_nombre, especialidad_nombre, medico_nombre) "
        f"SELECT {_SELECT_COLS}, p.nombres || ' ' || p.apellidos, e.nombre, "
        f"'Dr(a). ' || m.nombres || ' ' || m.apellidos "
        f"FROM citas c "
        f"LEFT JOIN pacientes p ON p.id_paciente = c.id_paciente "
        f"LEFT JOIN especialidades e ON e.id_especialidad = c.id_especialidad "
        f"LEFT JOIN medicos m ON m.id_medico = c.id_medico "
        f"WHERE c.id_paciente = :id"
    ), {"id": id_paciente})
    db.execute(text(
        f"INSERT INTO historico_pacientes ({_COLS_PACIENTE}) "
        f"SELECT {_COLS_PACIENTE} FROM pacientes WHERE id_paciente = :id"
    ), {"id": id_paciente})
    # Eliminar citas del paciente antes de eliminar el paciente
    db.query(Cita).filter(Cita.id_paciente == id_paciente).delete()
    db.delete(p)
    db.commit()
    _reset_sequence(db, "pacientes", "id_paciente")
    # NOTA: citas.id_cita ya no tiene secuencia (formato YYYYMMDDNNNN); no se realinea.
    return {"ok": True}

# ─── Especialidades ──────────────────────────────────────────────────────────

@router.get("/especialidades")
def listar_especialidades(db: Session = Depends(get_db)):
    return [
        {
            "id": e.id_especialidad,
            "nombre": e.nombre,
            "descripcion": e.descripcion or "",
            "activo": e.activo,
            "total_medicos": db.query(func.count(Medico.id_medico))
                .filter(Medico.id_especialidad == e.id_especialidad)
                .scalar(),
        }
        for e in db.query(Especialidad).order_by(Especialidad.nombre).all()
    ]

@router.post("/especialidades", status_code=201)
def crear_especialidad(data: EspecialidadCreate, db: Session = Depends(get_db)):
    if db.query(Especialidad).filter(Especialidad.nombre.ilike(data.nombre)).first():
        raise HTTPException(400, "Ya existe una especialidad con ese nombre")
    e = Especialidad(
        id_especialidad=_menor_id_libre(db, "especialidades", "id_especialidad"),
        **data.model_dump(),
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    _reset_sequence(db, "especialidades", "id_especialidad")
    return {"id": e.id_especialidad, "ok": True}

@router.put("/especialidades/{id_especialidad}")
def actualizar_especialidad(
    id_especialidad: int, data: EspecialidadUpdate, db: Session = Depends(get_db)
):
    e = db.query(Especialidad).filter(Especialidad.id_especialidad == id_especialidad).first()
    if not e:
        raise HTTPException(404, "Especialidad no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(e, k, v)
    db.commit()
    return {"ok": True}

@router.delete("/especialidades/{id_especialidad}")
def eliminar_especialidad(id_especialidad: int, db: Session = Depends(get_db)):
    e = db.query(Especialidad).filter(Especialidad.id_especialidad == id_especialidad).first()
    if not e:
        raise HTTPException(404, "Especialidad no encontrada")
    medicos = (
        db.query(func.count(Medico.id_medico))
        .filter(Medico.id_especialidad == id_especialidad)
        .scalar()
    )
    if medicos:
        raise HTTPException(400, f"Hay {medicos} médico(s) en esta especialidad. Elimínalos primero.")
    db.delete(e)
    db.commit()
    _reset_sequence(db, "especialidades", "id_especialidad")
    return {"ok": True}

# ─── EPS ─────────────────────────────────────────────────────────────────────

@router.get("/eps")
def listar_eps(db: Session = Depends(get_db)):
    return [
        {
            "id": e.id_eps,
            "nombre": e.nombre,
            "requiere_orden": e.requiere_orden,
            "requiere_autorizacion": e.requiere_autorizacion,
            "autorizacion_opcional": e.autorizacion_opcional,
            "activo": e.activo,
            "total_pacientes": db.query(func.count(Paciente.id_paciente))
                .filter(Paciente.id_eps == e.id_eps)
                .scalar(),
        }
        for e in db.query(Eps).order_by(Eps.nombre).all()
    ]

@router.post("/eps", status_code=201)
def crear_eps(data: EpsCreate, db: Session = Depends(get_db)):
    if db.query(Eps).filter(Eps.nombre.ilike(data.nombre)).first():
        raise HTTPException(400, "Ya existe una EPS con ese nombre")
    e = Eps(id_eps=_menor_id_libre(db, "eps", "id_eps"), **data.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    _reset_sequence(db, "eps", "id_eps")
    return {"id": e.id_eps, "ok": True}

@router.put("/eps/{id_eps}")
def actualizar_eps(id_eps: int, data: EpsUpdate, db: Session = Depends(get_db)):
    e = db.query(Eps).filter(Eps.id_eps == id_eps).first()
    if not e:
        raise HTTPException(404, "EPS no encontrada")
    if data.nombre and data.nombre.strip().lower() != e.nombre.lower():
        if db.query(Eps).filter(Eps.nombre.ilike(data.nombre)).first():
            raise HTTPException(400, "Ya existe una EPS con ese nombre")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(e, k, v)
    db.commit()
    return {"ok": True}

@router.delete("/eps/{id_eps}")
def eliminar_eps(id_eps: int, db: Session = Depends(get_db)):
    e = db.query(Eps).filter(Eps.id_eps == id_eps).first()
    if not e:
        raise HTTPException(404, "EPS no encontrada")
    pacientes = (
        db.query(func.count(Paciente.id_paciente))
        .filter(Paciente.id_eps == id_eps)
        .scalar()
    )
    if pacientes:
        raise HTTPException(
            400,
            f"Hay {pacientes} paciente(s) afiliado(s) a esta EPS. "
            f"Desactívala en lugar de eliminarla."
        )
    db.delete(e)
    db.commit()
    _reset_sequence(db, "eps", "id_eps")
    return {"ok": True}

# ─── Fechas Disponibles ──────────────────────────────────────────────────────

@router.get("/fechas")
def listar_fechas(solo_futuras: bool = True, db: Session = Depends(get_db)):
    """
    Lista las fechas de agendamiento con estadísticas REALES basadas en
    `slots_disponibles` (los slots concretos cargados desde el Excel semanal),
    no en el contador estático `cupos_disponibles`. Cada fila devuelve:
      · slots totales del día (según Excel)
      · slots ocupados (citas agendadas o pendientes)
      · slots libres
      · cuántos médicos distintos tienen slots ese día
    """
    q = db.query(FechaDisponible)
    if solo_futuras:
        q = q.filter(FechaDisponible.fecha >= date.today())
    fechas = q.order_by(FechaDisponible.fecha).all()

    # Slots por fecha (total + médicos distintos)
    slots_por_fecha = {
        r.fecha: (int(r.total), int(r.medicos))
        for r in db.execute(text("""
            SELECT fecha, COUNT(*) AS total, COUNT(DISTINCT id_medico) AS medicos
            FROM slots_disponibles
            GROUP BY fecha
        """)).all()
    }
    # Ocupados por fecha (citas activas)
    ocupados_por_fecha = {
        r.fecha_cita: int(r.n)
        for r in db.execute(text("""
            SELECT fecha_cita, COUNT(*) AS n
            FROM citas WHERE estado IN ('agendada', 'pendiente')
            GROUP BY fecha_cita
        """)).all()
    }

    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    out = []
    for f in fechas:
        total_slots, medicos = slots_por_fecha.get(f.fecha, (0, 0))
        ocupados = ocupados_por_fecha.get(f.fecha, 0)
        out.append({
            "id": f.id_fecha,
            "fecha": str(f.fecha),
            "dia": dias[f.fecha.weekday()],
            "medicos": medicos,
            "slots_totales": total_slots,
            "slots_ocupados": ocupados,
            "slots_libres": max(0, total_slots - ocupados),
            "activo": f.activo,
        })
    return out


@router.post("/fechas/limpiar-huerfanas")
def limpiar_fechas_huerfanas(db: Session = Depends(get_db)):
    """
    Sincroniza `fechas_disponibles` con la verdad actual del sistema:
      1. Borra fechas HUÉRFANAS (sin slots ni citas asociadas).
      2. Agrega fechas que TIENEN slots pero no están registradas.
      3. Renumera los id_fecha en orden por fecha ascendente empezando en 1
         (id_fecha no es FK de nada, así que renumerar es seguro).
    Devuelve un desglose de lo que hizo.
    """
    # 1) Borrar huérfanas
    r = db.execute(text("""
        DELETE FROM fechas_disponibles fd
        WHERE NOT EXISTS (SELECT 1 FROM slots_disponibles s WHERE s.fecha = fd.fecha)
          AND NOT EXISTS (SELECT 1 FROM citas c            WHERE c.fecha_cita = fd.fecha
                                                             AND c.estado IN ('agendada','pendiente'))
    """))
    borradas = r.rowcount or 0

    # 2) Agregar fechas que tienen slots pero no están registradas
    r = db.execute(text("""
        INSERT INTO fechas_disponibles (fecha, cupos_disponibles, activo)
        SELECT DISTINCT s.fecha, 50, TRUE
        FROM slots_disponibles s
        WHERE NOT EXISTS (SELECT 1 FROM fechas_disponibles fd WHERE fd.fecha = s.fecha)
    """))
    sincronizadas = r.rowcount or 0

    # 3) Renumerar id_fecha en orden por fecha (compacto: 1..N)
    #    Fase intermedia con IDs negativos para no chocar con el UNIQUE del PK.
    db.execute(text("""
        WITH orden AS (
            SELECT id_fecha, ROW_NUMBER() OVER (ORDER BY fecha) AS rn FROM fechas_disponibles
        )
        UPDATE fechas_disponibles f SET id_fecha = -o.rn FROM orden o WHERE f.id_fecha = o.id_fecha;
    """))
    db.execute(text("UPDATE fechas_disponibles SET id_fecha = -id_fecha WHERE id_fecha < 0"))
    _reset_sequence(db, "fechas_disponibles", "id_fecha")
    db.commit()

    total = db.execute(text("SELECT COUNT(*) FROM fechas_disponibles")).scalar() or 0
    return {
        "borradas": borradas,
        "agregadas_por_sincronia": sincronizadas,
        "total_actual": int(total),
    }

@router.post("/fechas", status_code=201)
def crear_fecha(data: FechaCreate, db: Session = Depends(get_db)):
    if db.query(FechaDisponible).filter(FechaDisponible.fecha == data.fecha).first():
        raise HTTPException(400, "Ya existe una fecha disponible para ese día")
    f = FechaDisponible(
        id_fecha=_menor_id_libre(db, "fechas_disponibles", "id_fecha"),
        **data.model_dump(),
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    _reset_sequence(db, "fechas_disponibles", "id_fecha")
    return {"id": f.id_fecha, "ok": True}

@router.put("/fechas/{id_fecha}")
def actualizar_fecha(id_fecha: int, data: FechaUpdate, db: Session = Depends(get_db)):
    f = db.query(FechaDisponible).filter(FechaDisponible.id_fecha == id_fecha).first()
    if not f:
        raise HTTPException(404, "Fecha no encontrada")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(f, k, v)
    db.commit()
    return {"ok": True}

@router.delete("/fechas/{id_fecha}")
def eliminar_fecha(id_fecha: int, db: Session = Depends(get_db)):
    f = db.query(FechaDisponible).filter(FechaDisponible.id_fecha == id_fecha).first()
    if not f:
        raise HTTPException(404, "Fecha no encontrada")
    db.delete(f)
    db.commit()
    _reset_sequence(db, "fechas_disponibles", "id_fecha")
    return {"ok": True}

@router.post("/fechas/refrescar")
def refrescar_fechas(dias: int = 60, db: Session = Depends(get_db)):
    """
    NO-OP tras el rediseño: las fechas ya no se generan automáticamente. Se
    conservan endpoint y firma para compatibilidad; ahora las fechas se cargan
    desde el panel via 'Cargar horarios' subiendo el Excel semanal.
    """
    return {"insertadas": 0, "aviso": "generación automática deshabilitada — usa 'Cargar horarios'"}


# ═════════════════════════════════════════════════════════════════════════════
# Carga de horarios semanales desde Excel (con preview + confirmación)
# ═════════════════════════════════════════════════════════════════════════════
#
# Flujo en dos pasos:
#   1) POST /horarios/cargar-preview  — sube el .xlsx + fecha del lunes,
#      lo parsea y devuelve un JSON con lo que SE VA a agregar. NO toca la BD.
#   2) POST /horarios/aplicar         — recibe la lista de slots del preview
#      (ya editada por el personal) y los inserta con ON CONFLICT DO NOTHING.
# El índice UNIQUE `uq_slot_medico_fecha_hora` garantiza que no haya duplicados
# aunque se ejecute varias veces.

_DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]

def _normalizar_dia(texto: str) -> Optional[int]:
    """Devuelve 0..6 (Lun..Dom) según el header, o None si no reconoce el día."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower().strip()
    for i, dia in enumerate(_DIAS_SEMANA):
        if t.startswith(dia):
            return i
    return None

def _norm_nombre_medico(texto: str) -> str:
    """Normaliza un nombre para comparar (mayúsculas, sin tildes, sin espacios extra)."""
    import unicodedata, re as _re
    t = unicodedata.normalize("NFKD", str(texto or "").replace("\xf1", "ñ"))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return _re.sub(r"\s+", " ", t).upper().strip()

def _parse_horas_celda(cell) -> List[str]:
    """
    Extrae todas las horas HH:MM de una celda del Excel. Soporta:
      - datetime.time / datetime.datetime (celda con formato hora)
      - texto: '11:00', '11:00 am', '15:30 15:45', '07:46:00', '11.00'
    """
    import datetime as _dt, re as _re
    if cell is None:
        return []
    if isinstance(cell, _dt.time):
        return [cell.strftime("%H:%M")]
    if isinstance(cell, _dt.datetime):
        return [cell.time().strftime("%H:%M")]
    s = str(cell).lower()
    out = set()
    for m in _re.finditer(r"(\d{1,2})[:.](\d{2})(?:[:.]\d{2})?\s*(am|pm)?", s):
        hh, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        if ampm == "pm" and hh < 12: hh += 12
        if ampm == "am" and hh == 12: hh = 0
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            out.add(f"{hh:02d}:{mm:02d}")
    return sorted(out)


@router.post("/horarios/cargar-preview")
async def cargar_horarios_preview(
    archivo: UploadFile = File(...),
    fecha_lunes: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Parsea el Excel de horarios semanales y devuelve un preview SIN modificar
    la BD. El personal revisa el preview y luego llama /horarios/aplicar para
    persistir. `fecha_lunes` = 'YYYY-MM-DD' del lunes de la semana objetivo.
    """
    # 1) Validar fecha lunes
    try:
        lunes = date.fromisoformat(fecha_lunes)
    except ValueError:
        raise HTTPException(400, "Fecha inválida (formato esperado: YYYY-MM-DD)")
    if lunes.weekday() != 0:
        raise HTTPException(400, f"La fecha {lunes} no es un lunes (ISO {lunes.isoweekday()})")

    # 2) Leer el Excel
    try:
        import openpyxl
        from io import BytesIO
    except ImportError:
        raise HTTPException(500, "openpyxl no está instalado en el servidor (pip install openpyxl)")

    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(400, "El archivo está vacío")
    try:
        wb = openpyxl.load_workbook(BytesIO(contenido), read_only=True, data_only=True)
        ws = wb.worksheets[0]
    except Exception as e:
        raise HTTPException(400, f"No se pudo abrir el Excel: {e}")

    # 3) Cabecera: buscar columnas de días (Lunes…Domingo)
    rows = ws.iter_rows(values_only=True)
    header = next(rows, None)
    if not header:
        raise HTTPException(400, "El Excel no tiene cabecera")

    # Mapa índice_columna → offset_dia (0=lunes, 1=martes, …). Las cols 0 y 1
    # son ESPECIALIDAD y ESPECIALISTAS respectivamente.
    col_dia: Dict[int, int] = {}
    for idx, celda in enumerate(header):
        d = _normalizar_dia(celda)
        if d is not None and idx >= 2:
            col_dia[idx] = d
    if not col_dia:
        raise HTTPException(
            400,
            "No se detectaron columnas de días. La cabecera debe incluir "
            "Lunes, Martes, Miércoles, etc."
        )

    # 4) Cargar médicos actuales para hacer match por nombre
    medicos_db = db.query(Medico).filter(Medico.activo == True).all()
    idx_medicos: Dict[str, "Medico"] = {}
    for m in medicos_db:
        idx_medicos[_norm_nombre_medico(f"{m.nombres} {m.apellidos}")] = m

    def _match_medico(nombre_excel: str):
        """Match exacto normalizado → si no, por tokens ≥3 chars (>=3 aciertos)."""
        key = _norm_nombre_medico(nombre_excel.split("/")[0])
        if key in idx_medicos:
            return idx_medicos[key]
        toks = [t for t in key.split() if len(t) >= 3]
        if len(toks) < 2:
            return None
        for k_med, med in idx_medicos.items():
            seed_toks = set(k_med.split())
            aciertos = sum(1 for t in toks if t in seed_toks)
            if aciertos >= min(3, len(toks)):
                return med
        return None

    # 5) Recorrer filas y armar los slots
    slots_por_medico: Dict[int, Dict] = {}   # id_medico → {medico, slots:[{fecha,hora}]}
    filas_ignoradas: List[str] = []
    for i, row in enumerate(rows, start=2):
        if not row:
            continue
        nombre_excel = row[1] if len(row) > 1 else None
        if not nombre_excel or not str(nombre_excel).strip():
            continue
        medico = _match_medico(str(nombre_excel))
        if not medico:
            filas_ignoradas.append(str(nombre_excel).strip())
            continue
        for col_idx, offset in col_dia.items():
            if col_idx >= len(row):
                continue
            horas = _parse_horas_celda(row[col_idx])
            if not horas:
                continue
            fecha = lunes + timedelta(days=offset)
            entrada = slots_por_medico.setdefault(medico.id_medico, {
                "id_medico": medico.id_medico,
                "nombre": f"{medico.nombres} {medico.apellidos}",
                "especialidad": medico.especialidad.nombre if medico.especialidad else "",
                "slots": [],
            })
            for h in horas:
                entrada["slots"].append({"fecha": fecha.isoformat(), "hora": h})
    wb.close()

    # 6) Detectar choques con citas ya agendadas y con slots ya existentes
    todos = []
    for e in slots_por_medico.values():
        for s in e["slots"]:
            todos.append((e["id_medico"], s["fecha"], s["hora"]))

    conflictos_citas: List[Dict] = []
    duplicados: List[Dict] = []
    if todos:
        # Slots ya en BD (misma tupla)
        existentes = {
            (r.id_medico, r.fecha.isoformat(), str(r.hora)[:5])
            for r in db.execute(text(
                "SELECT id_medico, fecha, hora FROM slots_disponibles "
                "WHERE fecha BETWEEN :ini AND :fin"
            ), {"ini": lunes, "fin": lunes + timedelta(days=6)}).fetchall()
        }
        # Citas ya agendadas/pendientes en la misma tupla
        citas_ocupadas = {
            (r.id_medico, r.fecha_cita.isoformat(), str(r.hora_cita)[:5])
            for r in db.execute(text(
                "SELECT id_medico, fecha_cita, hora_cita FROM citas "
                "WHERE fecha_cita BETWEEN :ini AND :fin "
                "  AND estado IN ('agendada','pendiente')"
            ), {"ini": lunes, "fin": lunes + timedelta(days=6)}).fetchall()
        }
        for k in todos:
            if k in existentes:
                duplicados.append({"id_medico": k[0], "fecha": k[1], "hora": k[2]})
            if k in citas_ocupadas:
                conflictos_citas.append({"id_medico": k[0], "fecha": k[1], "hora": k[2]})

    return {
        "fecha_lunes": lunes.isoformat(),
        "fecha_domingo": (lunes + timedelta(days=6)).isoformat(),
        "medicos": list(slots_por_medico.values()),
        "total_slots": len(todos),
        "filas_ignoradas": sorted(set(filas_ignoradas)),
        "duplicados": duplicados,
        "conflictos_citas": conflictos_citas,
    }


class SlotAplicar(BaseModel):
    id_medico: int
    fecha: str    # YYYY-MM-DD
    hora: str     # HH:MM

class AplicarHorariosRequest(BaseModel):
    slots: List[SlotAplicar]

@router.post("/horarios/aplicar")
def aplicar_horarios(data: AplicarHorariosRequest, db: Session = Depends(get_db)):
    """
    Persiste los slots confirmados por el personal (después del preview).
    Idempotente: ON CONFLICT (id_medico, fecha, hora) DO NOTHING evita
    duplicados. Retorna cuántos slots se insertaron y cuántos ya existían.
    También registra la fecha en `fechas_disponibles` para que el trigger de
    cupos siga funcionando en las citas.
    """
    if not data.slots:
        raise HTTPException(400, "No hay slots para aplicar")

    # Validar y agrupar por (medico, fecha, hora); dedup en request también
    unicos = set()
    for s in data.slots:
        try:
            date.fromisoformat(s.fecha)
            datetime.strptime(s.hora, "%H:%M")
        except ValueError:
            raise HTTPException(400, f"Slot inválido: {s.dict()}")
        unicos.add((int(s.id_medico), s.fecha, s.hora))

    # Fechas únicas (para registrar en fechas_disponibles)
    fechas_unicas = sorted({s[1] for s in unicos})

    # Insertar slots
    insertados = 0
    for id_medico, f_iso, h_str in unicos:
        r = db.execute(text(
            "INSERT INTO slots_disponibles (id_medico, fecha, hora) "
            "VALUES (:m, :f, :h) "
            "ON CONFLICT (id_medico, fecha, hora) DO NOTHING"
        ), {"m": id_medico, "f": f_iso, "h": h_str})
        insertados += r.rowcount or 0

    # Registrar cada fecha en fechas_disponibles (no toca las existentes)
    fechas_creadas = 0
    for f_iso in fechas_unicas:
        r = db.execute(text(
            "INSERT INTO fechas_disponibles (fecha, cupos_disponibles, activo) "
            "VALUES (:f, 50, TRUE) "
            "ON CONFLICT (fecha) DO NOTHING"
        ), {"f": f_iso})
        fechas_creadas += r.rowcount or 0

    db.commit()
    return {
        "solicitados": len(unicos),
        "slots_creados": insertados,
        "slots_ya_existentes": len(unicos) - insertados,
        "fechas_registradas": fechas_creadas,
    }

# ─── Horarios Médicos ─────────────────────────────────────────────────────────

@router.get("/horarios")
def listar_horarios(
    id_medico: Optional[int] = None,
    id_especialidad: Optional[int] = None,
    db: Session = Depends(get_db),
):
    q = db.query(HorarioMedico).join(HorarioMedico.medico)
    if id_medico:
        q = q.filter(HorarioMedico.id_medico == id_medico)
    if id_especialidad:
        q = q.filter(Medico.id_especialidad == id_especialidad)
    dias = ["", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    return [
        {
            "id": h.id_horario,
            "id_medico": h.id_medico,
            "medico": f"Dr(a). {h.medico.nombres} {h.medico.apellidos}" if h.medico else "",
            "id_especialidad": h.medico.id_especialidad if h.medico else None,
            "especialidad": h.medico.especialidad.nombre if (h.medico and h.medico.especialidad) else "—",
            "dia_semana": h.dia_semana,
            "dia": dias[h.dia_semana] if 1 <= h.dia_semana <= 7 else str(h.dia_semana),
            "hora_inicio": str(h.hora_inicio)[:5],
            "hora_fin": str(h.hora_fin)[:5],
            "activo": h.activo,
        }
        for h in q.order_by(HorarioMedico.id_medico, HorarioMedico.dia_semana).all()
    ]

@router.post("/horarios", status_code=201)
def crear_horario(data: HorarioCreate, db: Session = Depends(get_db)):
    if not db.query(Medico).filter(Medico.id_medico == data.id_medico).first():
        raise HTTPException(404, "Médico no encontrado")
    try:
        h_inicio = datetime.strptime(data.hora_inicio, "%H:%M").time()
        h_fin = datetime.strptime(data.hora_fin, "%H:%M").time()
    except ValueError:
        raise HTTPException(400, "Formato de hora inválido. Use HH:MM")
    if h_inicio >= h_fin:
        raise HTTPException(400, "La hora de inicio debe ser antes que la hora de fin")
    h = HorarioMedico(
        id_horario=_menor_id_libre(db, "horarios_medicos", "id_horario"),
        id_medico=data.id_medico,
        dia_semana=data.dia_semana,
        hora_inicio=h_inicio,
        hora_fin=h_fin,
        activo=data.activo,
    )
    db.add(h)
    db.commit()
    db.refresh(h)
    _reset_sequence(db, "horarios_medicos", "id_horario")
    return {"id": h.id_horario, "ok": True}

@router.put("/horarios/{id_horario}")
def actualizar_horario(id_horario: int, data: HorarioUpdate, db: Session = Depends(get_db)):
    h = db.query(HorarioMedico).filter(HorarioMedico.id_horario == id_horario).first()
    if not h:
        raise HTTPException(404, "Horario no encontrado")
    if data.dia_semana is not None:
        if not (1 <= data.dia_semana <= 7):
            raise HTTPException(400, "El día de la semana debe estar entre 1 y 7")
        h.dia_semana = data.dia_semana
    if data.hora_inicio:
        h.hora_inicio = datetime.strptime(data.hora_inicio, "%H:%M").time()
    if data.hora_fin:
        h.hora_fin = datetime.strptime(data.hora_fin, "%H:%M").time()
    if data.activo is not None:
        h.activo = data.activo
    db.commit()
    return {"ok": True}

@router.delete("/horarios/{id_horario}")
def eliminar_horario(id_horario: int, db: Session = Depends(get_db)):
    h = db.query(HorarioMedico).filter(HorarioMedico.id_horario == id_horario).first()
    if not h:
        raise HTTPException(404, "Horario no encontrado")
    db.delete(h)
    db.commit()
    _reset_sequence(db, "horarios_medicos", "id_horario")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# Limpieza de documentos (fotos/PDF de órdenes y autorizaciones)
# ═════════════════════════════════════════════════════════════════════════════

_FRECUENCIAS_VALIDAS = ("desactivado", "diario", "semanal", "mensual")

def _fmt_bytes(n: int) -> str:
    """Presenta un tamaño en bytes de forma legible (B / KB / MB / GB)."""
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"


def _leer_config(db: Session, clave: str, default: str = "") -> str:
    """Lee un valor de la tabla `configuracion` con default seguro."""
    r = db.execute(text("SELECT valor FROM configuracion WHERE clave = :k"),
                   {"k": clave}).fetchone()
    return (r.valor if r and r.valor is not None else default)


def _escribir_config(db: Session, clave: str, valor: str) -> None:
    """Upsert en `configuracion`."""
    db.execute(text("""
        INSERT INTO configuracion (clave, valor, updated_at)
        VALUES (:k, :v, CURRENT_TIMESTAMP)
        ON CONFLICT (clave) DO UPDATE
        SET valor = EXCLUDED.valor, updated_at = CURRENT_TIMESTAMP
    """), {"k": clave, "v": valor})


@router.get("/sistema/limpieza-docs")
def obtener_estado_limpieza_docs(db: Session = Depends(get_db)):
    """
    Estado del sistema de limpieza de documentos:
      · frecuencia configurada
      · fecha de la última ejecución
      · estadísticas actuales (cuántos hay, cuántos se borrarían, tamaños)
    """
    import limpieza_documentos as _ld
    estado = _ld.estado_documentos(db)
    return {
        "frecuencia": _leer_config(db, "limpieza_docs_frecuencia", "semanal"),
        "ultima_ejecucion": _leer_config(db, "limpieza_docs_ultima", ""),
        "total_archivos": estado["total"],
        "protegidos": estado["protegidos"],
        "borrable": estado["borrable"],
        "bytes_total": estado["bytes_total"],
        "bytes_borrable": estado["bytes_borrable"],
        "tamano_total": _fmt_bytes(estado["bytes_total"]),
        "tamano_borrable": _fmt_bytes(estado["bytes_borrable"]),
    }


class FrecuenciaRequest(BaseModel):
    frecuencia: str

@router.put("/sistema/limpieza-docs")
def cambiar_frecuencia_limpieza(data: FrecuenciaRequest, db: Session = Depends(get_db)):
    """Cambia cada cuánto se ejecuta la limpieza automática."""
    f = (data.frecuencia or "").strip().lower()
    if f not in _FRECUENCIAS_VALIDAS:
        raise HTTPException(400, f"Frecuencia inválida. Usa una de: {', '.join(_FRECUENCIAS_VALIDAS)}")
    _escribir_config(db, "limpieza_docs_frecuencia", f)
    db.commit()
    return {"ok": True, "frecuencia": f}


@router.post("/sistema/limpieza-docs/ejecutar")
def ejecutar_limpieza_docs_ahora(db: Session = Depends(get_db)):
    """
    Ejecuta la limpieza AHORA (botón manual del panel). Los documentos de
    citas 'pendiente' y 'agendada' quedan intactos; el resto se elimina.
    """
    import limpieza_documentos as _ld
    r = _ld.limpiar_documentos(db)
    return {
        "ok": True,
        "borrados": r["borrados"],
        "protegidos": r["protegidos"],
        "bytes_liberados": r["bytes_liberados"],
        "espacio_liberado": _fmt_bytes(r["bytes_liberados"]),
        "ejecutado_en": r["ejecutado_en"],
        "errores": r["errores"],
    }

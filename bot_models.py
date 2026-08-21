"""
Modelos de Base de Datos - ChatBot WhatsApp con Botones
Sistema de Agendamiento de Citas Médicas
"""
from sqlalchemy import Column, Integer, BigInteger, String, Boolean, DateTime, Date, Time, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Eps(Base):
    """
    EPS (Entidad Promotora de Salud) a la que está afiliado el paciente.
    Define qué documentos exige al agendar una cita: orden médica,
    autorización, ambas o ninguna.
    """
    __tablename__ = "eps"

    id_eps = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    requiere_orden = Column(Boolean, default=True)          # exige foto de la orden médica
    requiere_autorizacion = Column(Boolean, default=True)   # pide la autorización
    # Si es True, la autorización se PIDE pero el paciente puede continuar sin ella.
    autorizacion_opcional = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relaciones
    pacientes = relationship("Paciente", back_populates="eps")

class Paciente(Base):
    """Tabla de pacientes registrados"""
    __tablename__ = "pacientes"

    id_paciente = Column(Integer, primary_key=True, index=True)
    cedula = Column(String(20), unique=True, nullable=False, index=True)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    celular = Column(String(20), nullable=False)
    correo = Column(String(100))
    id_eps = Column(Integer, ForeignKey("eps.id_eps"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    citas = relationship("Cita", back_populates="paciente")
    eps = relationship("Eps", back_populates="pacientes")

class Especialidad(Base):
    """Tabla de especialidades médicas (22 especialidades)"""
    __tablename__ = "especialidades"
    
    id_especialidad = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, nullable=False)
    descripcion = Column(Text)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relaciones
    medicos = relationship("Medico", back_populates="especialidad")
    citas = relationship("Cita", back_populates="especialidad")

class Medico(Base):
    """Tabla de médicos por especialidad"""
    __tablename__ = "medicos"
    
    id_medico = Column(Integer, primary_key=True, index=True)
    id_especialidad = Column(Integer, ForeignKey("especialidades.id_especialidad"))
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    registro_medico = Column(String(50), unique=True, nullable=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relaciones
    especialidad = relationship("Especialidad", back_populates="medicos")
    horarios = relationship("HorarioMedico", back_populates="medico")
    citas = relationship("Cita", back_populates="medico")

class FechaDisponible(Base):
    """Tabla de fechas disponibles para agendamiento"""
    __tablename__ = "fechas_disponibles"
    
    id_fecha = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, nullable=False, index=True)
    activo = Column(Boolean, default=True)
    cupos_disponibles = Column(Integer, default=50)
    created_at = Column(DateTime, default=datetime.utcnow)

class HorarioMedico(Base):
    """Horarios disponibles de cada médico"""
    __tablename__ = "horarios_medicos"

    id_horario = Column(Integer, primary_key=True, index=True)
    id_medico = Column(Integer, ForeignKey("medicos.id_medico"))
    dia_semana = Column(Integer, nullable=False)  # 1=Lunes, 7=Domingo
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    activo = Column(Boolean, default=True)

    # Relaciones
    medico = relationship("Medico", back_populates="horarios")

class SlotDisponible(Base):
    """
    Slots concretos de agendamiento: cada fila = una cita posible (médico, fecha,
    hora exacta). A diferencia de HorarioMedico (rangos por día de semana), aquí
    cada slot es una posibilidad puntual — semillados desde `esp_horarios.xlsx`
    (fechas específicas con horas concretas ofrecidas por el hospital).
    Se descartan del listado los que ya tengan una cita agendada/pendiente
    mediante JOIN a `citas` (no se marca ocupado en esta tabla).
    """
    __tablename__ = "slots_disponibles"

    id_slot = Column(Integer, primary_key=True, index=True)
    id_medico = Column(Integer, ForeignKey("medicos.id_medico"), nullable=False, index=True)
    fecha = Column(Date, nullable=False, index=True)
    hora = Column(Time, nullable=False)

class Cita(Base):
    """Tabla de citas agendadas"""
    __tablename__ = "citas"

    # id_cita usa formato YYYYMMDDNNNN (ver siguiente_id_cita() en sql_db.sql).
    # BigInteger porque el valor 202608190001 excede el rango de INT (2 147 483 647).
    # NO es autoincremental: se calcula al insertar mediante la función SQL.
    id_cita = Column(BigInteger, primary_key=True, autoincrement=False, index=True)
    id_paciente = Column(Integer, ForeignKey("pacientes.id_paciente"), index=True)
    id_especialidad = Column(Integer, ForeignKey("especialidades.id_especialidad"))
    id_medico = Column(Integer, ForeignKey("medicos.id_medico"))
    fecha_cita = Column(Date, nullable=False, index=True)
    hora_cita = Column(Time, nullable=False)
    tipo_servicio = Column(String(50), nullable=False)  # cita, imagenologia, rehabilitacion
    turno = Column(String(10))  # manana, tarde
    # pendiente = esperando confirmación manual del hospital; agendada = confirmada
    estado = Column(String(20), default='pendiente')  # pendiente, agendada, cancelada, completada, inasistida
    tipo_cita = Column(String(20))            # primera_vez, control
    doc_orden = Column(String(255))           # ruta de la imagen de la orden médica
    doc_autorizacion = Column(String(255))    # ruta de la imagen de la autorización
    telefono_whatsapp = Column(String(20))    # número de WhatsApp que agendó (para confirmar)
    procedimiento = Column(String(50))        # subtipo (p. ej. Otorrino: cerumen/nasolaringoscopia/epistaxis)
    # Clave única de agendamiento: (numero_orden + codigo_procedimiento + cédula del paciente).
    # Una misma orden (numero_orden) puede traer varios códigos; cada código es una cita distinta.
    numero_orden = Column(String(50))         # No. de la orden médica leído por OCR
    codigo_procedimiento = Column(String(50)) # código CUPS del procedimiento leído por OCR
    doc_orden_datos = Column(Text)            # JSON con los datos leídos por OCR de la orden médica
    doc_autorizacion_datos = Column(Text)     # JSON con los datos leídos por OCR de la autorización
    motivo_cancelacion = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    paciente = relationship("Paciente", back_populates="citas")
    especialidad = relationship("Especialidad", back_populates="citas")
    medico = relationship("Medico", back_populates="citas")

class SesionWhatsApp(Base):
    """Sesiones activas de WhatsApp"""
    __tablename__ = "sesiones_whatsapp"
    
    id_sesion = Column(Integer, primary_key=True, index=True)
    telefono = Column(String(20), nullable=False, index=True)
    id_paciente = Column(Integer, ForeignKey("pacientes.id_paciente"))
    estado_flujo = Column(String(50), default='inicio')  # inicio, verificacion, menu, etc.
    datos_temp = Column(Text)  # JSON con datos temporales
    ultimo_mensaje = Column(DateTime, default=datetime.utcnow)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class MetricaAgendamiento(Base):
    """
    Métricas de cada agendamiento COMPLETADO:
      - duracion_seg: tiempo desde que se abrió el chat hasta crear la cita.
      - tiempo_confirmacion_seg: tiempo desde que se creó la cita hasta que fue confirmada manualmente.
      - estrellas: calificación de satisfacción 1..5 (NULL si no calificó).
    Tabla independiente (sin FK a citas) para que el resumen acumulado NO se
    pierda cuando las citas se archivan al histórico.
    """
    __tablename__ = "metricas_agendamiento"

    id = Column(Integer, primary_key=True, index=True)
    id_cita = Column(BigInteger)       # referencia informativa (sin FK dura)
    id_paciente = Column(Integer)
    telefono = Column(String(20))
    estrellas = Column(Integer)        # 1..5 o NULL
    duracion_seg = Column(Integer)     # segundos del agendamiento
    tiempo_confirmacion_seg = Column(Integer)  # segundos hasta confirmación (NULL si no confirmada)
    created_at = Column(DateTime, default=datetime.utcnow)

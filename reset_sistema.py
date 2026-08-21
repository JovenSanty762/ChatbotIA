"""
reset_sistema.py — Ejecutable de reinicio del sistema de citas.

Qué hace (en una sola transacción):
  1. ARCHIVA todas las citas actuales en la tabla 'historico_citas' (con los
     nombres de paciente, especialidad y médico) para conservar el registro
     histórico de las citas que se han ido asignando.
  2. BORRA únicamente las citas ACTIVAS (estado 'agendada'). Las citas en otros
     estados (cancelada/completada/inasistida) se conservan en la tabla 'citas'.
  3. RESTAURA los cupos de las fechas futuras.

NO modifica los IDs de los médicos ni reinicia el id_cita (este sigue de forma
ascendente; solo vuelve a 1 si la tabla de citas queda completamente vacía).

Uso:
    python reset_sistema.py            # pide confirmación
    python reset_sistema.py --force    # sin confirmación (para automatizar)

El histórico NUNCA se borra: cada ejecución agrega las citas vigentes a
'historico_citas' (con la fecha de archivado).
"""

import sys
from sqlalchemy import text

from database import engine

# Columnas de 'citas' que se copian al histórico (sin incluir archivado_en)
_COLS_CITA = (
    "id_cita, id_paciente, id_especialidad, id_medico, fecha_cita, hora_cita, "
    "tipo_servicio, estado, motivo_cancelacion, created_at, updated_at, turno"
)
# Las mismas columnas, prefijadas con 'c.' para el SELECT con JOINs
_SELECT_COLS = ", ".join(f"c.{col.strip()}" for col in _COLS_CITA.split(","))

# Columnas de 'pacientes' que se copian al histórico
_COLS_PACIENTE = "id_paciente, cedula, nombres, apellidos, celular, correo, created_at, updated_at"


# ─── Helpers reutilizables ────────────────────────────────────────────────────

def _asegurar_historico(conn) -> None:
    """Crea la tabla historico_citas y sus columnas si no existen."""
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS historico_citas (LIKE citas INCLUDING DEFAULTS)"
    ))
    conn.execute(text(
        "ALTER TABLE historico_citas "
        "ADD COLUMN IF NOT EXISTS archivado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    ))
    conn.execute(text("ALTER TABLE historico_citas ADD COLUMN IF NOT EXISTS paciente_nombre TEXT"))
    conn.execute(text("ALTER TABLE historico_citas ADD COLUMN IF NOT EXISTS especialidad_nombre TEXT"))
    conn.execute(text("ALTER TABLE historico_citas ADD COLUMN IF NOT EXISTS medico_nombre TEXT"))


def _archivar_citas(conn) -> int:
    """Copia TODAS las citas a historico_citas capturando los nombres actuales."""
    return conn.execute(text(
        f"INSERT INTO historico_citas "
        f"({_COLS_CITA}, paciente_nombre, especialidad_nombre, medico_nombre) "
        f"SELECT {_SELECT_COLS}, "
        f"       p.nombres || ' ' || p.apellidos, "
        f"       e.nombre, "
        f"       'Dr(a). ' || m.nombres || ' ' || m.apellidos "
        f"FROM citas c "
        f"LEFT JOIN pacientes p ON p.id_paciente = c.id_paciente "
        f"LEFT JOIN especialidades e ON e.id_especialidad = c.id_especialidad "
        f"LEFT JOIN medicos m ON m.id_medico = c.id_medico"
    )).rowcount


def archivar_citas_antiguas(conn, dias: int = 7) -> int:
    """
    Archiva en 'historico_citas' las citas cuya FECHA DE LA CITA ya pasó hace más
    de `dias` días y las elimina de la tabla activa 'citas'. Es idempotente
    (si no hay citas viejas, no hace nada). Devuelve cuántas archivó.
    Se puede llamar con una Connection o con una Session de SQLAlchemy.
    """
    _asegurar_historico(conn)
    corte = "fecha_cita < CURRENT_DATE - (:dias * INTERVAL '1 day')"
    archivadas = conn.execute(text(
        f"INSERT INTO historico_citas "
        f"({_COLS_CITA}, paciente_nombre, especialidad_nombre, medico_nombre) "
        f"SELECT {_SELECT_COLS}, "
        f"       p.nombres || ' ' || p.apellidos, "
        f"       e.nombre, "
        f"       'Dr(a). ' || m.nombres || ' ' || m.apellidos "
        f"FROM citas c "
        f"LEFT JOIN pacientes p ON p.id_paciente = c.id_paciente "
        f"LEFT JOIN especialidades e ON e.id_especialidad = c.id_especialidad "
        f"LEFT JOIN medicos m ON m.id_medico = c.id_medico "
        f"WHERE c.{corte}"
    ), {"dias": dias}).rowcount
    conn.execute(text(f"DELETE FROM citas WHERE {corte}"), {"dias": dias})
    return archivadas


def _asegurar_historico_pacientes(conn) -> None:
    """Crea la tabla historico_pacientes si no existe (sin PK, para permitir
    varios archivados del mismo id_paciente a lo largo del tiempo)."""
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS historico_pacientes (LIKE pacientes INCLUDING DEFAULTS)"
    ))
    conn.execute(text(
        "ALTER TABLE historico_pacientes "
        "ADD COLUMN IF NOT EXISTS archivado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    ))


def _archivar_pacientes(conn) -> int:
    """Copia TODOS los pacientes a historico_pacientes."""
    _asegurar_historico_pacientes(conn)
    return conn.execute(text(
        f"INSERT INTO historico_pacientes ({_COLS_PACIENTE}) "
        f"SELECT {_COLS_PACIENTE} FROM pacientes"
    )).rowcount


def _alinear_secuencia(conn, tabla: str, col: str) -> None:
    """Deja la secuencia en MAX(col)+1 (o 1 si la tabla queda vacía)."""
    conn.execute(text(
        f"SELECT setval(pg_get_serial_sequence('{tabla}','{col}'), "
        f"COALESCE((SELECT MAX({col}) FROM {tabla}), 0) + 1, false)"
    ))


def _restaurar_cupos(conn) -> None:
    conn.execute(text(
        "UPDATE fechas_disponibles SET cupos_disponibles = 50 "
        "WHERE fecha >= CURRENT_DATE"
    ))


def reiniciar_sistema(conn) -> dict:
    """
    Archiva todas las citas y borra SOLO las activas (agendadas). Las demás se
    conservan. No modifica los IDs de los médicos.
    """
    _asegurar_historico(conn)
    archivadas = _archivar_citas(conn)
    total_hist = conn.execute(text("SELECT COUNT(*) FROM historico_citas")).scalar()

    borradas = conn.execute(text(
        "DELETE FROM citas WHERE estado = 'agendada'"
    )).rowcount

    # NOTA: citas.id_cita usa formato YYYYMMDDNNNN (no secuencia SERIAL).
    _restaurar_cupos(conn)

    # Nota: los IDs de los médicos NO se modifican.

    return {
        "archivadas": archivadas,
        "total_historico": total_hist,
        "activas_eliminadas": borradas,
    }


def eliminar_todos_pacientes(conn) -> dict:
    """
    Elimina TODOS los registros de pacientes. Como las citas dependen de los
    pacientes, primero se archivan y se borran todas las citas, y se desvinculan
    las sesiones de WhatsApp (id_paciente → NULL) para no violar la FK.
    """
    _asegurar_historico(conn)
    archivadas = _archivar_citas(conn)
    # Guardar los pacientes en el histórico antes de borrarlos (como las citas)
    pacientes_archivados = _archivar_pacientes(conn)

    # Desvincular sesiones (FK sesiones_whatsapp.id_paciente) y forzar reinicio
    conn.execute(text(
        "UPDATE sesiones_whatsapp SET id_paciente = NULL, estado_flujo = 'inicio' "
        "WHERE id_paciente IS NOT NULL"
    ))
    citas_borradas = conn.execute(text("DELETE FROM citas")).rowcount
    pacientes_borrados = conn.execute(text("DELETE FROM pacientes")).rowcount

    _alinear_secuencia(conn, "pacientes", "id_paciente")
    _restaurar_cupos(conn)

    return {
        "archivadas": archivadas,
        "citas_eliminadas": citas_borradas,
        "pacientes_archivados": pacientes_archivados,
        "pacientes_eliminados": pacientes_borrados,
    }


def eliminar_todos_medicos(conn) -> dict:
    """
    Elimina TODOS los médicos. Como las citas y los horarios dependen de los
    médicos, primero se archivan y borran las citas y se borran los horarios.
    """
    _asegurar_historico(conn)
    archivadas = _archivar_citas(conn)

    citas_borradas = conn.execute(text("DELETE FROM citas")).rowcount
    horarios_borrados = conn.execute(text("DELETE FROM horarios_medicos")).rowcount
    medicos_borrados = conn.execute(text("DELETE FROM medicos")).rowcount

    _alinear_secuencia(conn, "medicos", "id_medico")
    _alinear_secuencia(conn, "horarios_medicos", "id_horario")
    # Sin médicos no hay cupos reales; las fechas se conservan pero quedarán sin
    # disponibilidad hasta crear médicos con horarios de nuevo.
    _restaurar_cupos(conn)

    return {
        "archivadas": archivadas,
        "citas_eliminadas": citas_borradas,
        "horarios_eliminados": horarios_borrados,
        "medicos_eliminados": medicos_borrados,
    }


def _confirmar() -> bool:
    if "--force" in sys.argv or "-f" in sys.argv:
        return True
    print("\n⚠️  Esto ARCHIVA todas las citas en historico_citas y BORRA solo")
    print("    las citas ACTIVAS (agendadas). Las demás (canceladas/completadas)")
    print("    se conservan. Los IDs de los médicos NO se modifican.\n")
    return input("Escribe 'SI' para continuar: ").strip().upper() == "SI"


def main() -> None:
    if not _confirmar():
        print("Operación cancelada. No se hizo ningún cambio.")
        return

    with engine.begin() as conn:
        res = reiniciar_sistema(conn)

    print("\n✅ Reinicio completado:")
    print(f"   • Citas archivadas en esta corrida : {res['archivadas']}")
    print(f"   • Citas en el histórico (acumulado): {res['total_historico']}")
    print(f"   • Citas activas eliminadas         : {res['activas_eliminadas']}")
    print("   • IDs de médicos                   : sin cambios")
    print("\nEl histórico se conserva en la tabla 'historico_citas'.")


if __name__ == "__main__":
    main()

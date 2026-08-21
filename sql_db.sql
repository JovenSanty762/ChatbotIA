-- ============================================================================
-- sql_db.sql  ·  ARCHIVO SQL ÚNICO del proyecto
-- ChatBot WhatsApp - Hospital Civil de Ipiales
--
-- FUENTE ÚNICA de: esquema (tablas/índices) + migraciones + funciones/triggers
-- + datos semilla. `bot_main.py` lo EJECUTA AUTOMÁTICAMENTE al arrancar (justo
-- después de create_all). Por eso TODO aquí es IDEMPOTENTE y NO DESTRUCTIVO:
-- se puede correr en cada inicio sin borrar datos, duplicar filas ni reordenar
-- horarios. Cualquier cambio de base de datos se agrega AQUÍ (ya no en
-- bot_main.py ni en otros .sql).
--
-- También puede ejecutarse a mano en una BD nueva:
--     psql -U postgres -d hospital_chatbot -f sql_db.sql
--
-- Secciones:
--   1) Tablas
--   2) Índices y unicidad
--   3) Migraciones de esquema (para BD creadas con versiones anteriores)
--   4) Funciones, triggers y vistas
--   5) Datos semilla (especialidades, EPS, un médico por especialidad, horarios)
--   6) Realineación de secuencias SERIAL
-- ============================================================================

SET client_encoding = 'UTF8';

-- ############################################################################
-- 1) TABLAS  (orden respetando llaves foráneas)
-- ############################################################################

CREATE TABLE IF NOT EXISTS eps (
    id_eps                SERIAL PRIMARY KEY,
    nombre                VARCHAR(100) UNIQUE NOT NULL,
    requiere_orden        BOOLEAN DEFAULT TRUE,
    requiere_autorizacion BOOLEAN DEFAULT TRUE,
    autorizacion_opcional BOOLEAN DEFAULT FALSE,
    activo                BOOLEAN DEFAULT TRUE,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS especialidades (
    id_especialidad SERIAL PRIMARY KEY,
    nombre          VARCHAR(100) UNIQUE NOT NULL,
    descripcion     TEXT,
    activo          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pacientes (
    id_paciente  SERIAL PRIMARY KEY,
    cedula       VARCHAR(20) UNIQUE NOT NULL,
    nombres      VARCHAR(100) NOT NULL,
    apellidos    VARCHAR(100) NOT NULL,
    celular      VARCHAR(20) NOT NULL,
    correo       VARCHAR(100),
    id_eps       INTEGER REFERENCES eps(id_eps),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medicos (
    id_medico        SERIAL PRIMARY KEY,
    id_especialidad  INTEGER NOT NULL REFERENCES especialidades(id_especialidad),
    nombres          VARCHAR(100) NOT NULL,
    apellidos        VARCHAR(100) NOT NULL,
    registro_medico  VARCHAR(50) UNIQUE NOT NULL,
    activo           BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS fechas_disponibles (
    id_fecha          SERIAL PRIMARY KEY,
    fecha             DATE NOT NULL,
    cupos_disponibles INTEGER DEFAULT 50,
    activo            BOOLEAN DEFAULT TRUE,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS horarios_medicos (
    id_horario   SERIAL PRIMARY KEY,
    id_medico    INTEGER NOT NULL REFERENCES medicos(id_medico),
    dia_semana   INTEGER NOT NULL CHECK (dia_semana BETWEEN 1 AND 7), -- 1=Lunes … 7=Domingo
    hora_inicio  TIME NOT NULL,
    hora_fin     TIME NOT NULL,
    activo       BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS slots_disponibles (
    id_slot    SERIAL PRIMARY KEY,
    id_medico  INTEGER NOT NULL REFERENCES medicos(id_medico),
    fecha      DATE NOT NULL,
    hora       TIME NOT NULL
);

CREATE TABLE IF NOT EXISTS citas (
    -- id_cita usa el formato YYYYMMDDNNNN (ver función siguiente_id_cita).
    -- Es BIGINT explícito y NO se autoincrementa: el ID se calcula al insertar.
    id_cita                BIGINT PRIMARY KEY,
    id_paciente            INTEGER NOT NULL REFERENCES pacientes(id_paciente),
    id_especialidad        INTEGER NOT NULL REFERENCES especialidades(id_especialidad),
    id_medico              INTEGER NOT NULL REFERENCES medicos(id_medico),
    fecha_cita             DATE NOT NULL,
    hora_cita              TIME NOT NULL,
    tipo_servicio          VARCHAR(50) NOT NULL,        -- cita, imagenologia, rehabilitacion
    turno                  VARCHAR(10),                 -- manana, tarde
    estado                 VARCHAR(20) DEFAULT 'pendiente'
                              CHECK (estado IN ('pendiente','agendada','cancelada','completada','inasistida')),
    tipo_cita              VARCHAR(20),                 -- primera_vez, control
    doc_orden              VARCHAR(255),
    doc_autorizacion       VARCHAR(255),
    telefono_whatsapp      VARCHAR(20),
    procedimiento          VARCHAR(50),
    numero_orden           VARCHAR(50),                 -- No. de orden médica (clave única de agendamiento)
    codigo_procedimiento   VARCHAR(50),                 -- código CUPS (clave única con numero_orden + cédula)
    doc_orden_datos        TEXT,
    doc_autorizacion_datos TEXT,
    motivo_cancelacion     TEXT,
    created_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sesiones_whatsapp (
    id_sesion      SERIAL PRIMARY KEY,
    telefono       VARCHAR(20) NOT NULL,
    id_paciente    INTEGER REFERENCES pacientes(id_paciente),
    estado_flujo   VARCHAR(50) DEFAULT 'inicio',   -- inicio, verificacion, menu, etc.
    datos_temp     TEXT,                           -- JSON con datos temporales
    ultimo_mensaje TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activo         BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS metricas_agendamiento (
    id                      SERIAL PRIMARY KEY,
    id_cita                 BIGINT,
    id_paciente             INTEGER,
    telefono                VARCHAR(20),
    estrellas               INTEGER,     -- 1..5 o NULL
    duracion_seg            INTEGER,     -- tiempo del agendamiento (chatbot)
    tiempo_confirmacion_seg INTEGER,     -- tiempo hasta la confirmación manual (personal)
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ############################################################################
-- 2) ÍNDICES Y UNICIDAD
-- ############################################################################

CREATE INDEX IF NOT EXISTS idx_pacientes_cedula   ON pacientes(cedula);
CREATE INDEX IF NOT EXISTS idx_pacientes_celular   ON pacientes(celular);
CREATE INDEX IF NOT EXISTS idx_citas_fecha         ON citas(fecha_cita);
CREATE INDEX IF NOT EXISTS idx_citas_paciente      ON citas(id_paciente);
CREATE INDEX IF NOT EXISTS idx_citas_estado        ON citas(estado);
CREATE INDEX IF NOT EXISTS idx_sesiones_telefono   ON sesiones_whatsapp(telefono);
CREATE INDEX IF NOT EXISTS idx_sesiones_activo     ON sesiones_whatsapp(activo);
CREATE INDEX IF NOT EXISTS idx_fechas_disponibles  ON fechas_disponibles(fecha, activo);

-- `fecha` única: la exige `refrescar_fechas_disponibles` (ON CONFLICT (fecha)).
-- Se crea como índice único IF NOT EXISTS para que también quede en las BD
-- creadas por el ORM (create_all), que no declara la unicidad.
-- Slots: unicidad e índices para el lookup rápido por (médico, fecha).
CREATE UNIQUE INDEX IF NOT EXISTS uq_slot_medico_fecha_hora
    ON slots_disponibles(id_medico, fecha, hora);
CREATE INDEX IF NOT EXISTS idx_slot_medico_fecha
    ON slots_disponibles(id_medico, fecha);

CREATE UNIQUE INDEX IF NOT EXISTS uq_fechas_disponibles_fecha ON fechas_disponibles(fecha);
-- (El índice único de la clave de agendamiento se crea en la sección 3, DESPUÉS
--  de garantizar que existan las columnas numero_orden y codigo_procedimiento.)

-- ############################################################################
-- 3) MIGRACIONES DE ESQUEMA  (alinean BD antiguas con el modelo actual)
--    Todo con IF EXISTS / IF NOT EXISTS → seguro de re-ejecutar.
-- ############################################################################

-- ---- sesiones_whatsapp: renombres de versiones viejas ----------------------
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='sesiones_whatsapp' AND column_name='estado_conversacion') THEN
        ALTER TABLE sesiones_whatsapp RENAME COLUMN estado_conversacion TO estado_flujo;
    END IF;
END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='sesiones_whatsapp' AND column_name='datos_sesion') THEN
        ALTER TABLE sesiones_whatsapp RENAME COLUMN datos_sesion TO datos_temp;
    END IF;
END $$;

-- ---- pacientes -------------------------------------------------------------
ALTER TABLE pacientes ADD COLUMN IF NOT EXISTS id_eps INTEGER;
ALTER TABLE pacientes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='pacientes_id_eps_fkey') THEN
        ALTER TABLE pacientes
            ADD CONSTRAINT pacientes_id_eps_fkey FOREIGN KEY (id_eps) REFERENCES eps(id_eps);
    END IF;
END $$;

-- ---- eps -------------------------------------------------------------------
ALTER TABLE eps ADD COLUMN IF NOT EXISTS autorizacion_opcional BOOLEAN DEFAULT FALSE;

-- ---- citas: columnas nuevas (documentos, confirmación manual, turno) -------
ALTER TABLE citas ADD COLUMN IF NOT EXISTS turno                  VARCHAR(10);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS tipo_cita              VARCHAR(20);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS doc_orden              VARCHAR(255);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS doc_autorizacion       VARCHAR(255);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS telefono_whatsapp      VARCHAR(20);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS procedimiento          VARCHAR(50);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS doc_orden_datos        TEXT;
ALTER TABLE citas ADD COLUMN IF NOT EXISTS doc_autorizacion_datos TEXT;
ALTER TABLE citas ADD COLUMN IF NOT EXISTS motivo_cancelacion     TEXT;
ALTER TABLE citas ADD COLUMN IF NOT EXISTS numero_orden           VARCHAR(50);
ALTER TABLE citas ADD COLUMN IF NOT EXISTS codigo_procedimiento   VARCHAR(50);

-- Migración: id_cita de INTEGER SERIAL → BIGINT (formato YYYYMMDDNNNN).
-- Solo cambia el tipo si la columna sigue siendo INTEGER. Elimina la secuencia
-- (ya no autoincremental) y quita el DEFAULT — el ID se calcula al insertar
-- mediante `siguiente_id_cita()`.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='citas' AND column_name='id_cita' AND data_type='integer') THEN
        ALTER TABLE citas ALTER COLUMN id_cita DROP DEFAULT;
        ALTER TABLE citas ALTER COLUMN id_cita TYPE BIGINT;
        DROP SEQUENCE IF EXISTS citas_id_cita_seq CASCADE;
    END IF;
END $$;

-- CLAVE ÚNICA DE AGENDAMIENTO: (paciente + No. orden + código de procedimiento).
-- Se crea AQUÍ (no en la sección de índices) para asegurar que las columnas
-- numero_orden/codigo_procedimiento ya existan también en BD antiguas. Impide
-- agendar dos veces el MISMO procedimiento de la MISMA orden para el mismo
-- paciente (cédula ↔ id_paciente es 1:1). Es PARCIAL: solo aplica a citas NO
-- canceladas y con los tres datos presentes → tras cancelar se puede reagendar,
-- y no bloquea citas antiguas sin estos datos (columnas nuevas = NULL).
CREATE UNIQUE INDEX IF NOT EXISTS uq_cita_orden_proc_paciente
    ON citas (id_paciente, numero_orden, codigo_procedimiento)
    WHERE estado <> 'cancelada'
      AND numero_orden IS NOT NULL
      AND codigo_procedimiento IS NOT NULL;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='citas' AND column_name='motivo_consulta') THEN
        ALTER TABLE citas RENAME COLUMN motivo_consulta TO motivo_cancelacion;
    END IF;
END $$;
-- CHECK de estado: incluye 'pendiente' (confirmación manual) e 'inasistida'.
ALTER TABLE citas DROP CONSTRAINT IF EXISTS citas_estado_check;
ALTER TABLE citas ADD CONSTRAINT citas_estado_check
    CHECK (estado IN ('pendiente','agendada','cancelada','completada','inasistida'));

-- ---- fechas_disponibles ----------------------------------------------------
ALTER TABLE fechas_disponibles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;

-- ---- metricas_agendamiento: tiempo de confirmación manual ------------------
ALTER TABLE metricas_agendamiento ADD COLUMN IF NOT EXISTS tiempo_confirmacion_seg INTEGER;

-- Y su id_cita (referencia informativa) pasa a BIGINT para acomodar el nuevo
-- formato YYYYMMDDNNNN que excede el rango INT.
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='metricas_agendamiento' AND column_name='id_cita' AND data_type='integer') THEN
        ALTER TABLE metricas_agendamiento ALTER COLUMN id_cita TYPE BIGINT;
    END IF;
END $$;

-- ############################################################################
-- 4) FUNCIONES, TRIGGERS Y VISTAS
-- ############################################################################

-- ---- Trigger: ajustar cupos al crear / cancelar / reagendar ----------------
CREATE OR REPLACE FUNCTION trg_actualizar_cupos_fecha()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        UPDATE fechas_disponibles
           SET cupos_disponibles = GREATEST(cupos_disponibles - 1, 0)
         WHERE fecha = NEW.fecha_cita;

    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.estado != 'cancelada' AND NEW.estado = 'cancelada' THEN
            UPDATE fechas_disponibles
               SET cupos_disponibles = cupos_disponibles + 1
             WHERE fecha = NEW.fecha_cita;
        END IF;

        IF OLD.fecha_cita IS DISTINCT FROM NEW.fecha_cita AND NEW.estado = 'agendada' THEN
            UPDATE fechas_disponibles
               SET cupos_disponibles = cupos_disponibles + 1
             WHERE fecha = OLD.fecha_cita;
            UPDATE fechas_disponibles
               SET cupos_disponibles = GREATEST(cupos_disponibles - 1, 0)
             WHERE fecha = NEW.fecha_cita;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cupos_cita ON citas;
CREATE TRIGGER trg_cupos_cita
    AFTER INSERT OR UPDATE ON citas
    FOR EACH ROW
    EXECUTE FUNCTION trg_actualizar_cupos_fecha();

-- ---- Reciclado de IDs: menor entero libre ≥ 1 en una tabla/columna --------
-- Devuelve el ID más pequeño que NO está en uso. Si la tabla está vacía → 1.
-- Rellena huecos antes de crecer, evitando que los IDs se disparen tras muchos
-- DELETE. Reemplaza el patrón MAX(id)+1 en todos los INSERT del sistema.
CREATE OR REPLACE FUNCTION menor_id_libre(p_tabla text, p_col text)
RETURNS INTEGER AS $$
DECLARE
    r INTEGER;
BEGIN
    EXECUTE format(
        'WITH usados AS (SELECT %1$I AS n FROM %2$I),
              serie  AS (SELECT generate_series(1, COALESCE((SELECT MAX(n) FROM usados), 0) + 1) AS n)
         SELECT MIN(s.n) FROM serie s
         LEFT JOIN usados u ON u.n = s.n
         WHERE u.n IS NULL',
        p_col, p_tabla
    ) INTO r;
    RETURN COALESCE(r, 1);
END;
$$ LANGUAGE plpgsql;

-- ---- ID de cita con formato YYYYMMDDNNNN --------------------------------
-- Los primeros 8 dígitos son la fecha del día (año, mes, día), los últimos 4
-- son un contador secuencial que se reinicia cada día (0001, 0002, …). Máximo
-- 9 999 citas por día — si se excede lanza excepción (marca clara para
-- ampliar el formato antes de romper).
CREATE OR REPLACE FUNCTION siguiente_id_cita()
RETURNS BIGINT AS $$
DECLARE
    ymd      BIGINT := to_char(CURRENT_DATE, 'YYYYMMDD')::BIGINT;
    base     BIGINT := ymd * 10000;
    contador INTEGER;
BEGIN
    -- Menor contador libre del día (rellena huecos primero: si se borró la
    -- cita ...0002, la próxima cita del día toma ese hueco, no ...0005).
    WITH usados AS (
        SELECT (id_cita - base)::INTEGER AS n
        FROM citas
        WHERE id_cita >= base AND id_cita < base + 10000
    ),
    serie AS (
        SELECT generate_series(1, COALESCE((SELECT MAX(n) FROM usados), 0) + 1) AS n
    )
    SELECT MIN(s.n) INTO contador
    FROM serie s
    LEFT JOIN usados u ON u.n = s.n
    WHERE u.n IS NULL;

    contador := COALESCE(contador, 1);
    IF contador > 9999 THEN
        RAISE EXCEPTION 'Se agotó el contador diario de citas (9 999) para %', CURRENT_DATE;
    END IF;
    RETURN base + contador;
END;
$$ LANGUAGE plpgsql;

-- ---- Renumerar registro_medico a RM-001, RM-002, … ----------------------
-- Idempotente: se ejecuta en cada arranque. Renumera todos los médicos según
-- id_medico ascendente. Usa una fase intermedia TMP-… para no chocar con la
-- restricción UNIQUE del propio campo.
CREATE OR REPLACE FUNCTION renumerar_registros_medicos()
RETURNS INTEGER AS $$
DECLARE
    total INTEGER;
BEGIN
    WITH orden AS (
        SELECT id_medico, ROW_NUMBER() OVER (ORDER BY id_medico) AS rn FROM medicos
    )
    UPDATE medicos m
       SET registro_medico = 'TMP-' || o.rn
      FROM orden o
     WHERE m.id_medico = o.id_medico;

    WITH orden AS (
        SELECT id_medico, ROW_NUMBER() OVER (ORDER BY id_medico) AS rn FROM medicos
    )
    UPDATE medicos m
       SET registro_medico = 'RM-' || LPAD(o.rn::text, 3, '0')
      FROM orden o
     WHERE m.id_medico = o.id_medico;

    SELECT COUNT(*) INTO total FROM medicos;
    RETURN total;
END;
$$ LANGUAGE plpgsql;

-- ---- Fechas disponibles: ventana móvil (agrega días hábiles hacia adelante) -
CREATE OR REPLACE FUNCTION refrescar_fechas_disponibles(dias_adelante INTEGER DEFAULT 60)
RETURNS INTEGER AS $$
DECLARE
    insertadas INTEGER := 0;
    d DATE;
    dia_iso INTEGER;
BEGIN
    -- Limpiar fechas vencidas (ya no sirven para agendar)
    DELETE FROM fechas_disponibles WHERE fecha < CURRENT_DATE;

    -- Crear los días hábiles con al menos un médico activo con horario ese día
    FOR i IN 1..dias_adelante LOOP
        d := CURRENT_DATE + i;
        dia_iso := EXTRACT(ISODOW FROM d); -- 1=Lun … 7=Dom

        IF EXISTS (
            SELECT 1 FROM horarios_medicos hm
            JOIN medicos m ON m.id_medico = hm.id_medico
            WHERE hm.dia_semana = dia_iso AND hm.activo = TRUE AND m.activo = TRUE
        ) THEN
            INSERT INTO fechas_disponibles (fecha, cupos_disponibles, activo)
            VALUES (d, 50, TRUE)
            ON CONFLICT (fecha) DO NOTHING;
            IF FOUND THEN
                insertadas := insertadas + 1;
            END IF;
        END IF;
    END LOOP;

    RETURN insertadas;
END;
$$ LANGUAGE plpgsql;

-- ---- Slots de 30 min disponibles de un médico para una fecha ---------------
CREATE OR REPLACE FUNCTION obtener_horarios_disponibles(
    p_id_medico INTEGER,
    p_fecha     DATE
)
RETURNS TABLE (hora TIME, disponible BOOLEAN)
LANGUAGE plpgsql AS $$
DECLARE
    v_dia_semana INTEGER;
BEGIN
    v_dia_semana := EXTRACT(ISODOW FROM p_fecha);

    RETURN QUERY
    WITH horarios_medico AS (
        SELECT hora_inicio, hora_fin
        FROM horarios_medicos
        WHERE id_medico = p_id_medico AND dia_semana = v_dia_semana AND activo = TRUE
    ),
    slots AS (
        SELECT generate_series(
            (SELECT hora_inicio FROM horarios_medico LIMIT 1),
            (SELECT hora_fin    FROM horarios_medico LIMIT 1) - INTERVAL '30 minutes',
            '30 minutes'::interval
        )::time AS hora_slot
    ),
    citas_ocupadas AS (
        SELECT hora_cita FROM citas
        WHERE id_medico = p_id_medico AND fecha_cita = p_fecha AND estado = 'agendada'
    )
    SELECT s.hora_slot, (co.hora_cita IS NULL)
    FROM slots s
    LEFT JOIN citas_ocupadas co ON s.hora_slot = co.hora_cita;
END;
$$;

-- ---- Vista: médicos con horarios activos -----------------------------------
CREATE OR REPLACE VIEW vista_medicos_disponibles AS
SELECT m.id_medico, m.nombres, m.apellidos, e.nombre AS especialidad,
       h.dia_semana, h.hora_inicio, h.hora_fin
FROM medicos m
JOIN especialidades e ON m.id_especialidad = e.id_especialidad
JOIN horarios_medicos h ON m.id_medico = h.id_medico
WHERE m.activo = TRUE AND h.activo = TRUE
ORDER BY e.nombre, m.apellidos;

-- ############################################################################
-- 5) DATOS SEMILLA  (idempotentes; no borran ni reordenan nada existente)
-- ############################################################################

-- ---- 5.1 Especialidades (22) ----------------------------------------------
INSERT INTO especialidades (nombre, descripcion) VALUES
('Anestesiologia',              'Anestesia y cuidados postoperatorios'),
('Cardiologia',                 'Enfermedades del corazón y sistema cardiovascular'),
('Cardiologia Pediatrica',      'Enfermedades del corazón en niños'),
('Cirugia General',             'Procedimientos quirúrgicos generales'),
('Cirugia Maxilofacial',        'Cirugía de la cara y maxilar'),
('Dermatologia',                'Enfermedades de la piel'),
('Dolor y Cuidados Paliativos', 'Manejo del dolor y cuidados paliativos'),
('Gastroenterologia',           'Sistema digestivo'),
('Ginecologia y Obstetricia',   'Salud de la mujer'),
('Medicina Interna',            'Diagnóstico y tratamiento de enfermedades complejas'),
('Nefrologia',                  'Enfermedades renales'),
('Neurocirugia',                'Cirugía de enfermedades del sistema nervioso'),
('Nutricion',                   'Nutrición y dietética'),
('Oftalmologia',                'Enfermedades de los ojos'),
('Ortopedia y Traumatologia',   'Lesiones y enfermedades del sistema musculoesquelético'),
('Otorrinolaringologia',        'Oído, nariz y garganta'),
('Pediatria',                   'Atención médica infantil y adolescentes'),
('Perinatologia',               'Atención médica de recién nacidos y embarazadas de alto riesgo'),
('Psicologia',                  'Salud mental y trastornos psicológicos'),
('Reumatologia',                'Enfermedades articulares y autoinmunes'),
('Urologia',                    'Sistema urinario y reproductor masculino'),
('Cirugia Vascular',            'Enfermedades de venas y arterias (sistema vascular)'),
('Pediatria Canguro',           'Programa madre canguro para recién nacidos'),
('Procedimientos',              'Procedimientos médicos diversos')
ON CONFLICT (nombre) DO NOTHING;

-- ---- 5.2 EPS (12) ----------------------------------------------------------
--   (nombre, requiere_orden, requiere_autorizacion, autorizacion_opcional)
INSERT INTO eps (nombre, requiere_orden, requiere_autorizacion, autorizacion_opcional) VALUES
('Nueva EPS',    TRUE,  TRUE,  TRUE),
('Sanitas',      TRUE,  TRUE,  FALSE),
('Sura',         TRUE,  TRUE,  FALSE),
('Salud Total',  TRUE,  TRUE,  FALSE),
('Coosalud',     TRUE,  TRUE,  FALSE),
('Emssanar',     TRUE,  TRUE,  FALSE),
('Cajacopi',     TRUE,  TRUE,  FALSE),
('Famisanar',    TRUE,  TRUE,  FALSE),
('Compensar',    TRUE,  TRUE,  FALSE),
('Mutual Ser',   TRUE,  TRUE,  FALSE),
('Asmet Salud',  TRUE,  TRUE,  FALSE),
('Particular',   TRUE,  FALSE, FALSE)
ON CONFLICT (nombre) DO NOTHING;

-- ---- 5.3 Médicos reales (tomados de Especialistas.xlsx) -------------------
--   Idempotente: NO EXISTS por (especialidad + nombres + apellidos). Los
--   registros médicos son placeholders únicos RM-001.. (no oficiales).
WITH nuevos(esp, nombres, apellidos, rm) AS (
    VALUES
        ('Ortopedia y Traumatologia','Robert Fidel','Paredes Reyes','RM-001'),
        ('Ortopedia y Traumatologia','Nayith Armando','Benavides España','RM-002'),
        ('Ortopedia y Traumatologia','Yonathan Samuel','Rueda Paez','RM-003'),
        ('Ortopedia y Traumatologia','John Ray Veira','Del Castillo','RM-004'),
        ('Ortopedia y Traumatologia','Maria Elisa','Novillo Betancourt','RM-005'),
        ('Anestesiologia','Yenny Lucia','Argoti Velasco','RM-006'),
        ('Anestesiologia','Omar Armando','Castro Arteaga','RM-007'),
        ('Anestesiologia','David Humberto','Guerrero Ordoñez','RM-008'),
        ('Anestesiologia','Jose Luis','Guerrero Ordoñez','RM-009'),
        ('Anestesiologia','Johana Andrea','Jimenez Arcos','RM-010'),
        ('Anestesiologia','Juan','Carlos Mafla','RM-011'),
        ('Anestesiologia','Angela Cristina','Montenegro Ibarra','RM-012'),
        ('Anestesiologia','Rosita Isela','Pazmiño Obando','RM-013'),
        ('Anestesiologia','Fredy Hernan','Taquez Cuastumal','RM-014'),
        ('Cardiologia','Servio','Alejandro Medina','RM-015'),
        ('Cardiologia Pediatrica','Luis Ernesto','Ponce Bravo','RM-016'),
        ('Cirugia General','Fernando Dario','Chamorro Quiroz','RM-017'),
        ('Cirugia General','Victor Hugo','Enriquez Garcia','RM-018'),
        ('Cirugia General','Henry Javier','Eraso Calvache','RM-019'),
        ('Cirugia General','Mike Alexander','Gaitan Molina','RM-020'),
        ('Cirugia General','Jose Luis','Velasco Ospino','RM-021'),
        ('Cirugia Maxilofacial','Claudia Patricia','Muñoz Chamorro','RM-022'),
        ('Cirugia Maxilofacial','Chamorro Guerrero','Santiago Nicolas','RM-023'),
        ('Cirugia Vascular','Jesus Efrain','Villareal Revelo','RM-024'),
        ('Dermatologia','Eduard','Jair Parra','RM-025'),
        ('Dolor y Cuidados Paliativos','Yenny Lucia','Argoti Velasco','RM-026'),
        ('Dolor y Cuidados Paliativos','Juan','Carlos Mafla','RM-027'),
        ('Dolor y Cuidados Paliativos','Oscar Andres','Sotelo Rosero','RM-028'),
        ('Gastroenterologia','Dario Fernando','Burbano Luna','RM-029'),
        ('Gastroenterologia','Juan Manuel','Campy Guerrero','RM-030'),
        ('Gastroenterologia','Valentina','Davila Ruales','RM-031'),
        ('Gastroenterologia','Carlos Augusto','Jaramillo Ruiz','RM-032'),
        ('Gastroenterologia','Gilberto','Jaramillo Trujillo','RM-033'),
        ('Gastroenterologia','Janer Nelson','Lozano Martinez','RM-034'),
        ('Gastroenterologia','Javier Alfredo','Perez Martinez','RM-035'),
        ('Gastroenterologia','Francisco Andres','Petano Romero','RM-036'),
        ('Gastroenterologia','Amilkar David','Rondon Hernandez','RM-037'),
        ('Gastroenterologia','Juan Camilo','Salgar Sarmiento','RM-038'),
        ('Gastroenterologia','Herney','Solarte Pineda','RM-039'),
        ('Gastroenterologia','Diego Alexander','Sotelo Moreno','RM-040'),
        ('Gastroenterologia','Arturo Jose','Viera Oliveros','RM-041'),
        ('Ginecologia y Obstetricia','Hector Fernando','Arcos Arcos','RM-042'),
        ('Ginecologia y Obstetricia','Katerine Daniela','Hernandez Chamorro','RM-043'),
        ('Ginecologia y Obstetricia','Edison Ferney','Jaramillo Grijalba','RM-044'),
        ('Ginecologia y Obstetricia','Gilzan Javier','Narvaez Ortega','RM-045'),
        ('Ginecologia y Obstetricia','Freddy Eduardo','Proaño Rengifo','RM-046'),
        ('Medicina Interna','Johanna Isabel','Arango Ramirez','RM-047'),
        ('Medicina Interna','Manuel Armando','Cuaspud Enriquez','RM-048'),
        ('Medicina Interna','Maria Mercedes','Ojeda Guerrero','RM-049'),
        ('Medicina Interna','Maria Elena','Pantoja Rosero','RM-050'),
        ('Medicina Interna','Carlos Eduardo','Yacelga Rosero','RM-051'),
        ('Nefrologia','Daniel','Pinzon Segura','RM-052'),
        ('Neurocirugia','Oscar Andres','Hernandez Baez','RM-053'),
        ('Neurocirugia','Jose Fernando','Rodriguez Ascuntar','RM-054'),
        ('Neurocirugia','Juan Carlos','Rosero Rosero','RM-055'),
        ('Nutricion','Vivianes Alejandra','Coral Guerrero','RM-056'),
        ('Nutricion','Veronica Tatiana','Salgar Solarte','RM-057'),
        ('Nutricion','Luis Uduardo','Santacruz Ordoñez','RM-058'),
        ('Oftalmologia','Ginna Marcela','Erazo Ortiz','RM-059'),
        ('Otorrinolaringologia','Servio','Steven Herrera','RM-060'),
        ('Pediatria Canguro','Carlos Guillermo','Burbano Ortiz','RM-061'),
        ('Pediatria Canguro','Andrea Judith','Melo Chaves','RM-062'),
        ('Pediatria','Gustavo Jair','Peña Guancha','RM-063'),
        ('Pediatria','Cesar Antonio','Peregueza Cuaical','RM-064'),
        ('Pediatria','Nubia Elizabeth','Quiroz Benavides','RM-065'),
        ('Pediatria','Alda Del Socorro','Toledo Criollo','RM-066'),
        ('Perinatologia','Alexandra Marisella','Coral Rosero','RM-067'),
        ('Psicologia','Jessica Alejandra','Arellano Portilla','RM-068'),
        ('Psicologia','Mayra Alejandra','Rojas Rivera','RM-069'),
        ('Reumatologia','Servio Antonio','Davila Jurado','RM-070'),
        ('Urologia','Diego Alfonso','Lucero Rosero','RM-071')
)
INSERT INTO medicos (id_especialidad, nombres, apellidos, registro_medico)
SELECT e.id_especialidad, n.nombres, n.apellidos, n.rm
FROM nuevos n
JOIN especialidades e ON e.nombre = n.esp
WHERE NOT EXISTS (
    SELECT 1 FROM medicos m
    WHERE m.id_especialidad = e.id_especialidad
      AND m.nombres = n.nombres AND m.apellidos = n.apellidos
);

-- ---- 5.4 Slots de agendamiento (tomados de esp_horarios.xlsx) --------------
--   Cada fila = un slot concreto ofrecido por el hospital. Idempotente:
--   ON CONFLICT (id_medico, fecha, hora) DO NOTHING. Resuelve id_medico por
--   (nombres, apellidos) del seed 5.3, para no depender de un id numérico.
WITH s(nombres, apellidos, f, h) AS (
    VALUES
        ('Arturo Jose','Viera Oliveros','2026-08-24'::date,'09:20'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-24'::date,'09:35'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-24'::date,'09:40'::time),
        ('Ginna Marcela','Erazo Ortiz','2026-08-24'::date,'10:10'::time),
        ('Ginna Marcela','Erazo Ortiz','2026-08-24'::date,'10:30'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-24'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-24'::date,'11:10'::time),
        ('Servio','Alejandro Medina','2026-08-24'::date,'14:15'::time),
        ('Servio','Alejandro Medina','2026-08-24'::date,'14:30'::time),
        ('Alda Del Socorro','Toledo Criollo','2026-08-24'::date,'14:45'::time),
        ('Alda Del Socorro','Toledo Criollo','2026-08-24'::date,'15:00'::time),
        ('Gustavo Jair','Peña Guancha','2026-08-24'::date,'15:15'::time),
        ('Freddy Eduardo','Proaño Rengifo','2026-08-24'::date,'16:00'::time),
        ('Freddy Eduardo','Proaño Rengifo','2026-08-24'::date,'16:20'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-24'::date,'16:20'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-24'::date,'16:30'::time),
        ('Ginna Marcela','Erazo Ortiz','2026-08-25'::date,'09:50'::time),
        ('Ginna Marcela','Erazo Ortiz','2026-08-25'::date,'10:10'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-25'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-25'::date,'11:10'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-25'::date,'13:15'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-25'::date,'13:30'::time),
        ('Servio','Alejandro Medina','2026-08-25'::date,'14:15'::time),
        ('Servio','Alejandro Medina','2026-08-25'::date,'14:30'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-25'::date,'15:30'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-25'::date,'15:40'::time),
        ('Carlos Eduardo','Yacelga Rosero','2026-08-26'::date,'07:45'::time),
        ('Jessica Alejandra','Arellano Portilla','2026-08-26'::date,'07:45'::time),
        ('Mayra Alejandra','Rojas Rivera','2026-08-26'::date,'07:45'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-26'::date,'08:40'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-26'::date,'09:00'::time),
        ('Servio','Steven Herrera','2026-08-26'::date,'10:45'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-26'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-26'::date,'11:10'::time),
        ('Andrea Judith','Melo Chaves','2026-08-26'::date,'12:15'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-26'::date,'14:00'::time),
        ('Servio','Steven Herrera','2026-08-26'::date,'14:00'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-26'::date,'14:10'::time),
        ('Servio','Alejandro Medina','2026-08-26'::date,'14:15'::time),
        ('Servio','Steven Herrera','2026-08-26'::date,'14:15'::time),
        ('Claudia Patricia','Muñoz Chamorro','2026-08-26'::date,'14:20'::time),
        ('Servio','Alejandro Medina','2026-08-26'::date,'14:30'::time),
        ('Claudia Patricia','Muñoz Chamorro','2026-08-26'::date,'14:40'::time),
        ('Nubia Elizabeth','Quiroz Benavides','2026-08-26'::date,'14:45'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-26'::date,'15:30'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-26'::date,'15:40'::time),
        ('Veronica Tatiana','Salgar Solarte','2026-08-26'::date,'15:50'::time),
        ('Veronica Tatiana','Salgar Solarte','2026-08-26'::date,'16:15'::time),
        ('Carlos Eduardo','Yacelga Rosero','2026-08-27'::date,'07:15'::time),
        ('Carlos Eduardo','Yacelga Rosero','2026-08-27'::date,'07:30'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-27'::date,'08:40'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-27'::date,'09:00'::time),
        ('Maria Mercedes','Ojeda Guerrero','2026-08-27'::date,'10:45'::time),
        ('Maria Mercedes','Ojeda Guerrero','2026-08-27'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-27'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-27'::date,'11:10'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-27'::date,'11:20'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-27'::date,'11:30'::time),
        ('Carlos Guillermo','Burbano Ortiz','2026-08-27'::date,'12:15'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-27'::date,'13:30'::time),
        ('Arturo Jose','Viera Oliveros','2026-08-27'::date,'13:45'::time),
        ('Servio','Alejandro Medina','2026-08-27'::date,'14:15'::time),
        ('Servio','Steven Herrera','2026-08-27'::date,'14:15'::time),
        ('Servio','Alejandro Medina','2026-08-27'::date,'14:30'::time),
        ('Servio','Steven Herrera','2026-08-27'::date,'14:30'::time),
        ('Alda Del Socorro','Toledo Criollo','2026-08-27'::date,'14:45'::time),
        ('Alda Del Socorro','Toledo Criollo','2026-08-27'::date,'15:00'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-27'::date,'15:30'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-27'::date,'15:40'::time),
        ('Alexandra Marisella','Coral Rosero','2026-08-28'::date,'08:00'::time),
        ('Maria Mercedes','Ojeda Guerrero','2026-08-28'::date,'10:45'::time),
        ('Maria Mercedes','Ojeda Guerrero','2026-08-28'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-28'::date,'11:00'::time),
        ('Robert Fidel','Paredes Reyes','2026-08-28'::date,'11:10'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-28'::date,'11:20'::time),
        ('Manuel Armando','Cuaspud Enriquez','2026-08-28'::date,'11:30'::time),
        ('Andrea Judith','Melo Chaves','2026-08-28'::date,'12:15'::time),
        ('Servio','Alejandro Medina','2026-08-28'::date,'12:15'::time),
        ('Freddy Eduardo','Proaño Rengifo','2026-08-28'::date,'14:40'::time),
        ('Freddy Eduardo','Proaño Rengifo','2026-08-28'::date,'15:00'::time),
        ('Gustavo Jair','Peña Guancha','2026-08-28'::date,'15:15'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-28'::date,'15:30'::time),
        ('Yonathan Samuel','Rueda Paez','2026-08-28'::date,'15:40'::time),
        ('Vivianes Alejandra','Coral Guerrero','2026-08-28'::date,'15:50'::time),
        ('Mike Alexander','Gaitan Molina','2026-08-28'::date,'16:10'::time),
        ('Vivianes Alejandra','Coral Guerrero','2026-08-28'::date,'16:15'::time),
        ('Mike Alexander','Gaitan Molina','2026-08-28'::date,'16:20'::time),
        ('Luis Ernesto','Ponce Bravo','2026-08-29'::date,'16:50'::time),
        ('Luis Ernesto','Ponce Bravo','2026-08-29'::date,'16:55'::time)
)
INSERT INTO slots_disponibles (id_medico, fecha, hora)
SELECT m.id_medico, s.f, s.h
FROM s
JOIN medicos m ON m.nombres = s.nombres AND m.apellidos = s.apellidos
ON CONFLICT (id_medico, fecha, hora) DO NOTHING;

-- ############################################################################
-- 6) REALINEAR SECUENCIAS SERIAL A MAX+1
--    Evita colisiones de clave primaria (UniqueViolation) tras un restore.
--    NOTA: `citas.id_cita` NO tiene secuencia (usa formato YYYYMMDDNNNN vía
--    `siguiente_id_cita()`), por eso no aparece aquí. Los INSERT calculan el
--    menor ID libre mediante `menor_id_libre()` para reciclar huecos, así que
--    estos setval solo son una red de seguridad tras un restore desde backup.
-- ############################################################################
SELECT setval(pg_get_serial_sequence('especialidades','id_especialidad'),   COALESCE((SELECT MAX(id_especialidad)   FROM especialidades),   0) + 1, false);
SELECT setval(pg_get_serial_sequence('medicos','id_medico'),                 COALESCE((SELECT MAX(id_medico)         FROM medicos),           0) + 1, false);
SELECT setval(pg_get_serial_sequence('horarios_medicos','id_horario'),       COALESCE((SELECT MAX(id_horario)        FROM horarios_medicos),  0) + 1, false);
SELECT setval(pg_get_serial_sequence('slots_disponibles','id_slot'),         COALESCE((SELECT MAX(id_slot)           FROM slots_disponibles), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('pacientes','id_paciente'),             COALESCE((SELECT MAX(id_paciente)       FROM pacientes),         0) + 1, false);
SELECT setval(pg_get_serial_sequence('fechas_disponibles','id_fecha'),       COALESCE((SELECT MAX(id_fecha)          FROM fechas_disponibles),0) + 1, false);
SELECT setval(pg_get_serial_sequence('sesiones_whatsapp','id_sesion'),       COALESCE((SELECT MAX(id_sesion)         FROM sesiones_whatsapp), 0) + 1, false);
SELECT setval(pg_get_serial_sequence('eps','id_eps'),                        COALESCE((SELECT MAX(id_eps)            FROM eps),               0) + 1, false);
SELECT setval(pg_get_serial_sequence('metricas_agendamiento','id'),          COALESCE((SELECT MAX(id)                FROM metricas_agendamiento), 0) + 1, false);

-- ---- 7) Renumeración final de registros médicos → RM-001, RM-002, … --------
--     Se ejecuta al final para captar los médicos recién sembrados en 5.3.
SELECT renumerar_registros_medicos();

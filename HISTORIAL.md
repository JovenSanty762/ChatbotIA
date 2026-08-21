# Historial del ChatBot — Hospital Civil de Ipiales

Registro de la construcción, desarrollo y evolución del sistema desde su
inicio hasta el día de hoy.

**Proyecto iniciado:** 1 de marzo de 2026
**Autor:** Ing. Javier Santiago Burbano
**Última actualización:** 20 de agosto de 2026

---

## 📑 Índice

1. [Origen y objetivo del proyecto](#1-origen-y-objetivo-del-proyecto)
2. [Arquitectura general](#2-arquitectura-general)
3. [Fase 1 · Fundación](#3-fase-1--fundación-marzo–julio-2026)
4. [Fase 2 · Consolidación y datos reales](#4-fase-2--consolidación-y-datos-reales-agosto-2026)
5. [Bitácora de mejoras (agosto 2026)](#5-bitácora-de-mejoras-agosto-2026)
6. [Estado actual del sistema](#6-estado-actual-del-sistema)
7. [Métricas del código](#7-métricas-del-código)
8. [Decisiones técnicas destacadas](#8-decisiones-técnicas-destacadas)

---

## 1. Origen y objetivo del proyecto

El ChatBot nace como respuesta a la necesidad del **Hospital Civil de
Ipiales** de ofrecer una vía de agendamiento de citas médicas más ágil para
sus pacientes, sin depender del canal telefónico ni de desplazamientos
físicos innecesarios.

Se eligió **WhatsApp** como canal principal porque:

- Es la plataforma de mensajería con mayor penetración en Colombia.
- Reduce las barreras de acceso (no requiere instalar una app adicional).
- Permite enviar y recibir fotos/PDF, lo que habilita la verificación de
  documentos por OCR.

El sistema **NO reemplaza** la validación del personal asistencial: las
citas quedan en estado `pendiente` hasta que un miembro del hospital las
confirma desde el panel administrativo. Esta decisión fue tomada
deliberadamente para mantener el control humano sobre la agenda.

---

## 2. Arquitectura general

```
                     Paciente (WhatsApp)
                            │
                     ┌──────▼──────┐
                     │   Meta API   │
                     └──────┬──────┘
                            │  HTTPS
                     ┌──────▼──────┐
                     │  Bot FastAPI │  ← OCR (Gemini/Ollama)
                     │   (Python)   │  ← IA texto (Groq/Claude)
                     └──────┬──────┘  ← Validación CUPS
                            │
                     ┌──────▼──────┐
                     │  PostgreSQL  │
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │ Panel Admin  │ ← Personal del hospital
                     │  (LAN interna)│    confirma manualmente
                     └──────────────┘
```

Un único proceso Python sirve **dos superficies** distintas:

- `/webhook` — público (Meta necesita alcanzarlo).
- `/admin` y todos los endpoints del panel — solo LAN interna del hospital.

Un middleware separa estos dos mundos: si el request llega por un host
público (ngrok, dominio internet), solo `/webhook` responde; el panel
queda invisible (404 opaco).

---

## 3. Fase 1 · Fundación (marzo – julio 2026)

Se construyeron los componentes esenciales del sistema:

- **Máquina de estados** para el flujo del chatbot en WhatsApp
  (verificación por cédula, registro de pacientes nuevos, navegación por
  botones y listas interactivas).
- **Modelo de datos** con SQLAlchemy: pacientes, especialidades, médicos,
  horarios, citas, sesiones, EPS, métricas.
- **Panel administrativo** en HTML/Tailwind con dashboard, gestión de
  citas, pacientes, médicos, especialidades, fechas, horarios y sistema.
- **Autenticación del panel** con cookie de sesión firmada y ADMIN_PASSWORD.
- **Motor OCR** con Google Gemini para verificar automáticamente:
  nombre, cédula, EPS, prestador, procedimiento, fecha vigente.
- **Integración con WhatsApp Business API** vía webhook y HTTP.
- **Sistema de EPS** con requisitos documentales configurables por EPS.
- **Túnel Ngrok** integrado para pruebas locales.
- **Métricas iniciales**: tiempo de agendamiento y satisfacción por
  encuesta de estrellas.

---

## 4. Fase 2 · Consolidación y datos reales (agosto 2026)

En agosto 2026 se ejecutó una iteración intensiva de mejoras estructurales
y de datos reales. Las diez mejoras se detallan en la siguiente sección.

Al comienzo de esta fase, el sistema tenía:
- Especialidades: 22 (base)
- Médicos: ficticios (semilla genérica)
- Slots: generados automáticamente de 30 min sobre rangos por día de semana
- 4 archivos SQL con solapamiento e inconsistencias
- 3 archivos README con contenido duplicado
- Sin validación de código CUPS
- Sin protección contra duplicados de citas
- Sin distinción entre primera vez y control

Al final de esta fase, el sistema quedó con datos reales del hospital,
consolidado en un único archivo SQL, con validaciones estrictas y flujo
rediseñado.

---

## 5. Bitácora de mejoras (agosto 2026)

Diez avances aplicados en secuencia; cada uno consolida el anterior.

### 01 · Segunda métrica de tiempo: confirmación por el personal

Se agregó un indicador que mide desde que el paciente crea la cita hasta
que el personal la confirma en el panel. Visible como tarjeta en el
dashboard y card en Métricas, con promedio / mín / máx y columna extra en
la tabla de recientes.

**Archivos:** `bot_models.py`, `admin_router.py`, `static/admin.html`

### 02 · Consolidación en un único archivo SQL

Los cuatro `.sql` anteriores (uno de ellos borraba tablas, otro tenía
referencias rotas) se fusionaron en `sql_db.sql`: esquema, migraciones
idempotentes, funciones/triggers y datos semilla. `bot_main.py` lo
ejecuta automáticamente al arrancar. Los `.md` también se unificaron en
un único README lineal.

**Archivos:** `sql_db.sql`, `bot_main.py`

### 03 · Clave única de agendamiento anti-duplicados

La tripleta `(No. orden · código CUPS · cédula)` impide agendar dos veces
el mismo procedimiento de la misma orden. Doble defensa: comprobación en
el bot con mensajes claros e índice único parcial en la base de datos
como garantía ante condiciones de carrera. Una orden con varios códigos
sí puede agendarse por separado; una cita cancelada libera la clave.

**Índice:** `uq_cita_orden_proc_paciente`

### 04 · Validación de código de procedimiento contra la tabla CUPS

El código extraído por OCR se verifica contra las 9 949 entradas
oficiales del catálogo CUPS (`TablaReferencia_CUPS__1.xlsx`). Si el
código no existe o el OCR no lo puede leer, la orden se rechaza y se
pide una foto o PDF más clara.

**Archivos:** `cups_referencia.py`, `cups_codigos.txt`

### 05 · Datos reales: 71 médicos con nombres y especialidades del hospital

Se eliminó el histórico de citas y todos los médicos ficticios. Se
sembraron los 71 médicos reales de `Especialistas.xlsx` (23
especialidades cubiertas), con corrección de mojibake, mapeo de typos
("Obtetricia" → Obstetricia, "Oftalmolgia" → Oftalmologia) y dos
especialidades adicionales (Cirugía Vascular, Pediatría Canguro).

### 06 · Rediseño del flujo de agendamiento

Se eliminaron los menús de "cita lo antes posible" y de jornada
(mañana/tarde). Nuevo orden tras los documentos:
**médico → fecha del médico → hora del médico → resumen**. Selección
centrada en la persona que atenderá, con auto-selección cuando solo hay
una opción disponible.

### 07 · Detección OCR del tipo de cita

El prompt de OCR de la orden ahora extrae también si el documento indica
"primera vez" o "control", combinando tres pistas: campo explícito del
modelo, palabras clave en el nombre del procedimiento, y patrón CUPS
(`8902xx` → primera vez, `8903xx` → control).

### 08 · Validación estricta del tipo de cita

Si el paciente elige "primera vez" pero la orden es de "control" (o
viceversa), el bot rechaza la orden con mensaje claro y pide un
documento del tipo correcto. Reemplaza la corrección silenciosa
anterior. Si no se puede confirmar el tipo, también se rechaza.

### 09 · Continuidad de atención en citas de control

Para las citas de control, el bot busca automáticamente al médico que
atendió antes al paciente en la misma especialidad (en `citas` y
`historico_citas`) y salta directo a sus fechas. Si no hay antecedente
o el médico ya no está activo, el paciente puede elegir uno con aviso
explicativo.

### 10 · Slots reales de agendamiento por médico + fecha + hora

Nueva tabla `slots_disponibles` semillada con los 89 slots concretos de
`esp_horarios.xlsx`. Reemplaza la generación automática de slots de
30 min. Un slot desaparece de la lista cuando existe una cita agendada
o pendiente para ese `(médico, fecha, hora)` y reaparece si esa cita
se cancela.

---

## 6. Ajustes posteriores

### Reciclado de identificadores y formato de cita

- Nueva función SQL `menor_id_libre(tabla, columna)` que devuelve el
  menor entero disponible ≥ 1. Se aplica en todos los INSERT del panel
  (médicos, pacientes, especialidades, EPS, fechas, horarios) para
  rellenar huecos antes de crecer.
- Nueva función SQL `siguiente_id_cita()` con formato `YYYYMMDDNNNN`
  (ejemplo: `202608200001`). Rellena huecos del día si se cancela una
  cita del mismo día.
- Nueva función SQL `renumerar_registros_medicos()` que reordena todos
  los `RM-001, RM-002, …` según `id_medico` ascendente. Se ejecuta al
  arrancar y tras cada alta/baja de médico.

### Blindaje del panel

- Middleware `RestringirPanelDesdeInternet` en `bot_main.py`: cuando el
  request llega por un host público (`ngrok`, `trycloudflare`,
  `localtunnel`, `serveo`), solo `/webhook` responde. El panel devuelve
  404 opaco — no confirma que existe.
- Variable `PUBLIC_HOST_PATTERN` en `.env` para ajustar el patrón.
- Script `chatbot.ps1` (definitivo) que unifica instalación y arranque
  en un solo comando: verifica Python/PostgreSQL, crea `venv`, instala
  dependencias, prepara `.env`, crea la BD, abre firewall restrictivo
  (solo LAN autorizada) y arranca el bot. Con modos `-SoloInstalar`,
  `-SoloArrancar` y `-Verificar` para reutilizar según la fase.

### Correcciones de flujo

- **Bug de `tipo_cita` sobreviviendo a "cancelar":** al volver al menú
  principal ahora se limpian los datos temporales del agendamiento
  (conservando solo `id_metrica` para la encuesta pendiente).
- **Bucle infinito cuando un médico único no tiene slots (caso
  Nefrología):** el bot ahora detecta la condición y muestra un
  mensaje claro con el teléfono del hospital.
- **Encuesta simplificada:** se eliminó el paso "¿deseas calificar?".
  Tras agendar, aparecen directamente las 5 estrellas.
- **Menú final unificado:** todos los caminos donde el flujo termina
  (rechazo, cancelación, sin horarios) pasan por un menú "Volver al
  menú / Terminar chat". Si el usuario termina sin haber agendado,
  también se le ofrece calificar (métrica huérfana).

---

## 7. Estado actual del sistema

Datos vigentes en la base de datos `hospital_chatbot`:

| Recurso | Cantidad |
|---|---|
| Especialidades activas | 24 (22 base + Cirugía Vascular + Pediatría Canguro) |
| Médicos reales | 71 (RM-001 a RM-071) |
| EPS registradas | 13 |
| Slots de agendamiento | 89 (6 fechas: 24-29 agosto 2026) |
| Médicos con cupo en la ventana | 23 |
| Códigos CUPS validados | 9 949 |
| Citas activas | 0 (tras el reset) |
| Pacientes registrados | 4 (de pruebas) |

---

## 8. Métricas del código

| Módulo | Rol | Líneas |
|---|---|---|
| `bot_handler.py` | Flujos WhatsApp · máquina de estados | ~2 950 |
| `static/admin.html` | Panel administrativo | ~2 030 |
| `admin_router.py` | API administrativa | ~1 140 |
| `README.md` + `HISTORIAL.md` + `IMPLEMENTACION_HOSPITAL.md` | Documentación | — |
| `sql_db.sql` | Esquema · migraciones · funciones · semilla | ~700 |
| `bot_main.py` | App FastAPI · lifespan · middleware | ~590 |
| `ocr_processor.py` | Motor OCR (Gemini / Ollama) | ~370 |
| `bot_models.py` | Modelos SQLAlchemy | ~200 |
| `cups_referencia.py` | Validación CUPS | ~120 |

---

## 9. Decisiones técnicas destacadas

### Un solo archivo SQL como fuente de verdad

Antes había 4 archivos `.sql` con contenido solapado (uno de ellos
borraba todas las tablas del schema `public`, otro referenciaba tablas
inexistentes por typo). Se consolidaron en `sql_db.sql`, que ahora
contiene tablas + índices + migraciones idempotentes + funciones +
datos semilla. `bot_main.py` lo ejecuta automáticamente al arrancar,
por lo que ninguna instalación requiere pasos manuales de SQL.

### Datos del hospital viven en Excel, no en código

Los tres archivos Excel (`Especialistas.xlsx`, `esp_horarios.xlsx`,
`TablaReferencia_CUPS__1.xlsx`) son la **fuente autoritativa**. El
script Python parsea, corrige mojibake, resuelve typos y produce los
INSERT que van a `sql_db.sql`. Cuando el hospital publique nuevos
horarios o cambien médicos, se actualiza el Excel y se re-siembra —
no hay que tocar código.

### Formato de ID de citas legible por humanos

`202608200001` = año 2026, mes 08, día 20, cita número 0001 del día.
Cuando el personal ve un ID de cita en el panel, sabe de inmediato de
qué día es. Si se cancela la cita 0002 del día, la próxima cita del
mismo día toma ese 0002 (los huecos se rellenan).

### OCR con dos proveedores

- **Gemini (nube)** por defecto — rápido, preciso, tier gratuito
  suficiente para uso moderado.
- **Ollama (local)** como alternativa — 100% offline, sin límites, para
  cuando la nube no es una opción (política de datos del hospital) o
  cuando se supera el cupo gratuito.

### Confirmación humana no negociable

Ninguna cita se agenda automáticamente. La cita se crea en estado
`pendiente` y el personal la valida en el panel. Esto:
- protege ante fallos de OCR (documento mal leído);
- da control operativo al hospital sobre su agenda;
- permite auditoría (queda registro de quién confirmó cada cita).

---

**Este archivo es un registro vivo del proyecto.** Cada iteración
significativa que se haga sobre el chatbot debe reflejarse aquí para
mantener trazabilidad de las decisiones.

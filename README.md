# ChatBot WhatsApp — Hospital Civil de Ipiales

Sistema de agendamiento de citas médicas por WhatsApp. Verifica documentos con
OCR, valida contra el catálogo CUPS oficial y deja las citas en estado
**pendiente** hasta que el personal las confirma manualmente desde el panel
administrativo.

**Proyecto iniciado:** 1 de marzo de 2026 · **Autor:** Ing. Javier Santiago Burbano

---

## 📑 Índice

1. [Especificaciones del sistema](#especificaciones-del-sistema)
2. [Requisitos previos](#requisitos-previos)
3. [Instalación](#instalación)
4. [Configuración (.env)](#configuración-env)
5. [Ejecución](#ejecución)
6. [Configuración del webhook en Meta](#configuración-del-webhook-en-meta)
7. [Estructura del proyecto](#estructura-del-proyecto)
8. [Documentación complementaria](#documentación-complementaria)

---

## Especificaciones del sistema

### Capacidades

- **24 especialidades médicas** activas, con 71 médicos reales del hospital.
- **89 slots concretos de agendamiento** para las próximas fechas
  (semillados desde `esp_horarios.xlsx`).
- **Verificación OCR** de orden médica y autorización, con Gemini (nube) u
  Ollama (local, offline). Contrasta nombre, cédula, EPS, prestador, fecha
  vigente y tipo de cita.
- **Validación CUPS** contra el catálogo oficial (9 949 códigos).
- **Clave única de agendamiento** (No. orden + código CUPS + cédula) que
  impide duplicados a nivel de bot y de base de datos.
- **Formato de ID de cita** `YYYYMMDDNNNN` con contador diario reciclable.
- **Reciclado automático de IDs** en todas las tablas (menor libre al insertar).
- **Panel administrativo web** con login, confirmación manual, gestión de
  médicos/pacientes/especialidades/EPS/fechas/horarios.
- **Métricas**: tiempo de agendamiento (chatbot), tiempo de confirmación
  (personal), satisfacción del usuario (1–5 estrellas).

### Requisitos técnicos

| Componente | Versión mínima |
|---|---|
| Python | 3.10 (recomendado 3.11) |
| PostgreSQL | 14+ (probado en 18) |
| WhatsApp Business API | cuenta con webhook configurado |
| ngrok (para pruebas) o dominio + SSL (producción) | — |

### Tecnologías

- **Backend**: FastAPI + SQLAlchemy + Uvicorn
- **Base de datos**: PostgreSQL
- **OCR**: Google Gemini (default) u Ollama con `llama3.2-vision`
- **IA de texto**: Groq (Llama 3.3) por defecto, con soporte para Claude
- **Panel web**: HTML + Tailwind CSS

---

## Requisitos previos

### 1. Software

- Python 3.10+ instalado
- PostgreSQL 14+ instalado y corriendo
- (Opcional) Ngrok — para pruebas y piloto en red interna

### 2. Cuentas externas

- **WhatsApp Business API** (Meta for Developers) — [developers.facebook.com](https://developers.facebook.com/)
- **Ngrok** (piloto/desarrollo) — [dashboard.ngrok.com](https://dashboard.ngrok.com/signup)
- **Google AI Studio** — para el token de Gemini (OCR)
- **Groq Console** — para el token de Groq (interpretación de texto)

---

## Instalación

```bash
# 1. Clonar el repositorio en la máquina destino
git clone <url-del-repo>
cd chatbot-whatsapp-hospital

# 2. Crear la base de datos PostgreSQL
psql -U postgres
CREATE DATABASE hospital_chatbot;
\q

# 3. Crear el entorno virtual
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 4. Instalar dependencias
pip install -r bot_requirements.txt

# 5. Copiar la plantilla de configuración
cp bot_.env.example .env
# Editar .env con los valores reales (siguiente sección)
```

> **Nota:** No es necesario cargar SQL manualmente. Al arrancar por primera
> vez, `bot_main.py` ejecuta automáticamente `sql_db.sql`, que crea todas
> las tablas, funciones e importa los datos iniciales (24 especialidades,
> 12 EPS, 71 médicos reales, 89 slots de horarios).

---

## Configuración (.env)

Valores mínimos obligatorios:

```env
# Base de datos
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hospital_chatbot
DB_USER=postgres
DB_PASSWORD=tu_password_postgresql

# WhatsApp Business API
WHATSAPP_TOKEN=tu_token_de_acceso
WHATSAPP_PHONE_NUMBER_ID=tu_phone_number_id
VERIFY_TOKEN=una_cadena_secreta_cualquiera

# Ngrok (pruebas/piloto)
NGROK_AUTH_TOKEN=tu_token_ngrok
NGROK_ENABLED=true

# Servidor
HOST=127.0.0.1
PORT=8000

# Panel administrativo (login)
ADMIN_USER=admin
ADMIN_PASSWORD=cambia-esta-clave
SECRET_KEY=<genera con python -c "import secrets;print(secrets.token_hex(32))">
COOKIE_SECURE=false

# Hospital
HOSPITAL_NOMBRE=Hospital Civil de Ipiales
HOSPITAL_TELEFONO=6027374008 o 6027332149

# OCR (Google Gemini)
GEMINI_AUTH_TOKEN=tu_clave_gemini
GEMINI_MODEL=gemini-flash-lite-latest
OCR_PROVIDER=gemini

# IA de texto (Groq)
GROQ_AUTH_TOKEN=tu_clave_groq
AI_PROVIDER=groq
```

Los demás valores tienen defaults sensatos en `bot_.env.example`.

---

## Ejecución

### Windows

```powershell
.\chatbot.ps1                # instala lo que falte + arranca
.\chatbot.ps1 -SoloInstalar  # solo instala, no arranca
.\chatbot.ps1 -SoloArrancar  # arranca (uso diario)
.\chatbot.ps1 -Verificar     # solo verifica el estado
```

### Linux (Ubuntu / Debian)

```bash
./chatbot.sh                 # instala lo que falte + arranca
./chatbot.sh --solo-instalar # solo instala, no arranca
./chatbot.sh --solo-arrancar # arranca (uso diario)
./chatbot.sh --verificar     # solo verifica el estado
```

Ambos scripts hacen en un solo comando: verificar Python/PostgreSQL,
crear `venv`, instalar dependencias, crear `.env`, crear la base de
datos, abrir el firewall solo a la LAN y arrancar el bot.

### Alternativa manual (multi-plataforma)

Si prefieres ejecutar directo (después de instalar `venv` y `.env`):

```bash
python bot_main.py
```

### Detener

Windows: `Ctrl + C` en la consola.
Linux/Mac: `Ctrl + C` o `./stop_bot.sh`.

---

## Configuración del webhook en Meta

1. Al arrancar el bot con `NGROK_ENABLED=true` verás una URL similar a
   `https://xxxx.ngrok-free.app` en la consola.

2. En [developers.facebook.com](https://developers.facebook.com/) → tu App →
   **WhatsApp → Configuration → Webhook**:
   - **Callback URL:** `https://xxxx.ngrok-free.app/webhook`
   - **Verify Token:** el mismo `VERIFY_TOKEN` de tu `.env`
   - Pulsa **Verify and Save**.

3. En **Manage**, suscríbete al evento `messages`.

4. En **API Setup**, agrega tu número de prueba (envía el código que aparece
   desde tu WhatsApp personal).

5. Envía "Hola" al número de WhatsApp — el bot te responderá.

---

## Estructura del proyecto

```
chatbot-whatsapp-hospital/
│
├── Código del bot
│   ├── bot_main.py               # App FastAPI · lifecycle · ngrok
│   ├── bot_handler.py            # Máquina de estados y flujos WhatsApp
│   ├── bot_models.py             # Modelos SQLAlchemy
│   ├── bot_config.py             # Configuración (lee .env)
│   ├── admin_router.py           # API del panel administrativo
│   ├── auth_admin.py             # Login del panel (cookie firmada)
│   ├── database.py               # Engine y sesión compartida
│   ├── ai_processor.py           # Interpretación de texto (Groq/Claude)
│   ├── ocr_processor.py          # OCR (Gemini/Ollama)
│   ├── cups_referencia.py        # Validación de códigos CUPS
│   ├── intent_detector.py        # Detección de intent por keywords
│   └── reset_sistema.py          # Reinicio protegido de citas
│
├── Base de datos y semillas
│   ├── sql_db.sql                # ÚNICO archivo SQL (esquema + migraciones + datos)
│   ├── cups_codigos.txt          # 9 949 códigos CUPS válidos
│   ├── Especialistas.xlsx        # Fuente de médicos reales
│   ├── esp_horarios.xlsx         # Fuente de slots de agendamiento
│   └── TablaReferencia_CUPS__1.xlsx  # Catálogo CUPS oficial (fuente)
│
├── Panel administrativo
│   ├── static/admin.html         # UI del panel
│   ├── static/tailwind.css       # CSS compilado
│   ├── tailwind-input.css        # Fuente para recompilar (opcional)
│   ├── tailwind.config.js
│   └── package.json              # Deps de Tailwind
│
├── Configuración e instalación
│   ├── bot_requirements.txt      # Dependencias Python
│   ├── bot_.env.example          # Plantilla de .env
│   ├── chatbot.ps1               # Script definitivo Windows (instala + arranca)
│   ├── chatbot.sh                # Script definitivo Linux (instala + arranca)
│   ├── stop_bot.sh               # Detener el bot en Linux
│   ├── Dockerfile.chatbot        # Imagen Docker
│   └── docker-compose.chatbot.yml
│
├── Herramientas
│   └── probar_ocr.py             # Prueba OCR sin pasar por WhatsApp
│
└── Documentación
    ├── README.md                 # Este archivo (instalación)
    ├── HISTORIAL.md               # Historia y desarrollo del proyecto
    ├── IMPLEMENTACION_HOSPITAL.md # Guía paso a paso para Windows
    └── IMPLEMENTACION_LINUX.md    # Guía paso a paso para Ubuntu / Linux
```

---

## Documentación complementaria

- **[HISTORIAL.md](HISTORIAL.md)** — Historia completa del desarrollo del
  chatbot: cuándo se inició, qué se ha construido, qué mejoras se han
  implementado y por qué. Ideal para entender el estado actual y las
  decisiones técnicas tomadas.

- **[IMPLEMENTACION_HOSPITAL.md](IMPLEMENTACION_HOSPITAL.md)** — Guía paso
  a paso para desplegar el chatbot **en Windows** (piloto). Pensada
  para personal técnico sin experiencia previa con el sistema.

- **[IMPLEMENTACION_LINUX.md](IMPLEMENTACION_LINUX.md)** — Guía paso a
  paso para desplegar el chatbot **en un servidor Ubuntu** de la
  intranet del hospital. Incluye configuración de systemd para arranque
  automático en producción.

---

## Solución de problemas rápida

| Síntoma | Causa probable | Solución |
|---|---|---|
| `relation does not exist` | El esquema no se aplicó | Ejecuta `psql -U postgres -d hospital_chatbot -f sql_db.sql` |
| `fe_sendauth: no password supplied` | Credenciales en `.env` | Verifica `DB_PASSWORD` |
| `PyngrokNgrokError` | Token de Ngrok inválido | Revisa `NGROK_AUTH_TOKEN` (sin espacios) |
| Webhook "Forbidden" | `VERIFY_TOKEN` no coincide | Mismo valor en `.env` y en Meta |
| Bot no responde | Múltiples causas | Revisa la consola del bot en busca de errores |

Para ver logs en tiempo real, mira la consola donde corre `bot_main.py`.

---

**Versión:** 2.1.0 · **Última actualización:** 20 de agosto 2026

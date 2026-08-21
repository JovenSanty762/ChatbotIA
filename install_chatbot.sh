#!/bin/bash

#############################################
# Script de Instalacion Automatica
# ChatBot WhatsApp Hospital
# Compatible con Git Bash / terminal VS Code en Windows
#############################################

# NO usar set -e: manejamos cada error manualmente para evitar
# salidas silenciosas en Git Bash sobre Windows.

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

ok()    { echo -e "${GREEN}[OK] $1${NC}"; }
error() { echo -e "${RED}[ERROR] $1${NC}"; echo ""; exit 1; }
aviso() { echo -e "${YELLOW}[AVISO] $1${NC}"; }
info()  { echo -e "${BLUE}[INFO] $1${NC}"; }

# Ruta de psql: primero intenta el que esta en PATH; si no, prueba versiones
# comunes de PostgreSQL en Windows (18, 17, 16, 15, 14). Ajusta manualmente
# si tu instalacion usa otra ruta.
PSQL=""
if command -v psql > /dev/null 2>&1; then
    PSQL="psql"
else
    for _ver in 18 17 16 15 14; do
        _ruta="/c/Program Files/PostgreSQL/$_ver/bin/psql.exe"
        if [ -f "$_ruta" ]; then
            PSQL="$_ruta"
            break
        fi
    done
    # Fallback Linux (si estas en un servidor real, no Git Bash)
    [ -z "$PSQL" ] && [ -x "/usr/bin/psql" ] && PSQL="/usr/bin/psql"
fi

echo ""
echo "============================================================"
echo "  CHATBOT WHATSAPP - INSTALACION AUTOMATICA"
echo "  Hospital - Sistema de Agendamiento de Citas"
echo "============================================================"
echo ""

# -------------------------------------------------------------
# Verificar Python
# -------------------------------------------------------------
info "Verificando requisitos..."

# Si ya estamos dentro de un venv, usar ese Python directamente
if [ -n "$VIRTUAL_ENV" ]; then
    if [ -f "$VIRTUAL_ENV/Scripts/python.exe" ]; then
        PYTHON="$VIRTUAL_ENV/Scripts/python.exe"
    else
        PYTHON="$VIRTUAL_ENV/bin/python"
    fi
    ok "Python del venv activo: $($PYTHON --version 2>&1)"
else
    # Buscar Python del sistema (Git Bash en Windows usa 'python', no 'python3')
    PYTHON=""

    for cmd in python python3; do
        # Verificar que el comando existe y no es el alias vacio del Store
        if command -v "$cmd" > /dev/null 2>&1; then
            _ver=$("$cmd" --version 2>&1) || continue
            if echo "$_ver" | grep -q "Python 3"; then
                PYTHON="$cmd"
                ok "Python encontrado: $_ver"
                break
            fi
        fi
    done

    # Fallback: rutas absolutas comunes en Windows
    if [ -z "$PYTHON" ]; then
        _user="${USERNAME:-$USER}"
        for ruta in \
            "/c/Users/$_user/AppData/Local/Programs/Python/Python312/python.exe" \
            "/c/Users/$_user/AppData/Local/Programs/Python/Python311/python.exe" \
            "/c/Users/$_user/AppData/Local/Programs/Python/Python310/python.exe" \
            "/c/Python312/python.exe" \
            "/c/Python311/python.exe"; do
            if [ -f "$ruta" ]; then
                _ver=$("$ruta" --version 2>&1)
                PYTHON="$ruta"
                ok "Python encontrado (ruta directa): $_ver"
                break
            fi
        done
    fi

    if [ -z "$PYTHON" ]; then
        error "Python 3 no encontrado.\nSolucion: deshabilita los alias en Configuracion > Aplicaciones > Alias de ejecucion de aplicaciones y desmarca las entradas de Python."
    fi
fi

# Verificar pip
"$PYTHON" -m pip --version > /dev/null 2>&1 || error "pip no esta disponible para $PYTHON"
ok "pip disponible"

# -------------------------------------------------------------
# Crear entorno virtual
# -------------------------------------------------------------
echo ""
info "Creando entorno virtual..."

if [ ! -d "venv" ]; then
    "$PYTHON" -m venv venv
    if [ $? -ne 0 ]; then
        error "No se pudo crear el entorno virtual"
    fi
    ok "Entorno virtual creado"
else
    ok "Entorno virtual ya existe"
fi

# -------------------------------------------------------------
# Definir rutas del venv (independiente de si ya estaba activo)
# -------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/venv/Scripts/python.exe" ]; then
    PYTHON="$SCRIPT_DIR/venv/Scripts/python.exe"
    PIP="$SCRIPT_DIR/venv/Scripts/pip.exe"
    ACTIVATE="$SCRIPT_DIR/venv/Scripts/activate"
else
    PYTHON="$SCRIPT_DIR/venv/bin/python"
    PIP="$SCRIPT_DIR/venv/bin/pip"
    ACTIVATE="$SCRIPT_DIR/venv/bin/activate"
fi

# Activar (si no estaba ya activo)
if [ -z "$VIRTUAL_ENV" ]; then
    info "Activando entorno virtual..."
    source "$ACTIVATE" || error "No se pudo activar el entorno virtual"
fi

# Confirmar que el ejecutable responde
_venv_ver=$("$PYTHON" --version 2>&1) || error "El Python del venv no responde: $PYTHON"
ok "Entorno virtual listo — $PYTHON ($( echo $_venv_ver))"

# -------------------------------------------------------------
# Actualizar pip
# -------------------------------------------------------------
info "Actualizando pip..."
"$PYTHON" -m pip install --upgrade pip --quiet
ok "pip actualizado"

# -------------------------------------------------------------
# Instalar dependencias
# -------------------------------------------------------------
echo ""
info "Instalando dependencias (puede tardar varios minutos)..."
"$PIP" install -r bot_requirements.txt
if [ $? -ne 0 ]; then
    error "Error al instalar dependencias"
fi
ok "Dependencias instaladas correctamente"

# -------------------------------------------------------------
# Configurar .env
# -------------------------------------------------------------
echo ""
info "Configurando variables de entorno..."
if [ ! -f ".env" ]; then
    cp bot_.env.example .env
    aviso "Archivo .env creado desde plantilla"
    aviso "IMPORTANTE: Debes editar .env con tus credenciales"
    echo ""
    info "Abriendo .env en el Bloc de notas... (cierra el editor cuando termines)"
    notepad.exe .env &
    sleep 2
    info "Presiona Enter cuando hayas guardado y cerrado el editor..."
    read -r
else
    ok "Archivo .env ya existe"
fi

# -------------------------------------------------------------
# Configurar base de datos PostgreSQL
# -------------------------------------------------------------
echo ""
info "Configurando base de datos PostgreSQL..."
echo ""
read -rp "Deseas crear la base de datos ahora? (s/n): " crear_db

if [[ "${crear_db,,}" == "s" ]]; then

    read -rp "Usuario PostgreSQL (por defecto: postgres): " pg_user
    pg_user="${pg_user:-postgres}"

    read -rp "Nombre de la base de datos (por defecto: hospital_chatbot): " db_name
    db_name="${db_name:-hospital_chatbot}"

    if [ -z "$PSQL" ] || { [ "$PSQL" != "psql" ] && [ ! -f "$PSQL" ]; }; then
        aviso "psql no encontrado. Instala PostgreSQL o ajusta la variable PSQL"
        aviso "https://www.postgresql.org/download/"
    else
        # Pedir contraseña una sola vez y exportarla para todos los comandos psql
        read -rsp "Contrasena de PostgreSQL para el usuario '$pg_user': " pg_pass
        echo ""
        export PGPASSWORD="$pg_pass"

        # Verificar credenciales antes de intentar crear la BD
        "$PSQL" -U "$pg_user" -c "SELECT 1" > /dev/null 2>&1
        if [ $? -ne 0 ]; then
            unset PGPASSWORD
            error "Credenciales incorrectas para el usuario '$pg_user'. Verifica la contrasena."
        fi

        # Comprobar si la BD ya existe (idempotente)
        _exists=$("$PSQL" -U "$pg_user" -tAc \
            "SELECT 1 FROM pg_database WHERE datname='$db_name'" 2>/dev/null)
        if [ "$_exists" = "1" ]; then
            ok "Base de datos '$db_name' ya existe"
        else
            info "Creando base de datos '$db_name' con codificacion UTF8..."
            # Locale portable: UTF-8 en Linux, C en Windows (evita errores de locale)
            "$PSQL" -U "$pg_user" -c \
                "CREATE DATABASE $db_name ENCODING 'UTF8' TEMPLATE template0;" \
                > /dev/null 2>&1
            if [ $? -ne 0 ]; then
                unset PGPASSWORD
                error "No se pudo crear la base de datos"
            fi
            ok "Base de datos '$db_name' creada"
        fi

        info "Aplicando sql_db.sql (esquema + migraciones + funciones + semilla)..."
        if [ -f "sql_db.sql" ]; then
            "$PSQL" -U "$pg_user" -d "$db_name" -f "sql_db.sql" > /dev/null 2>&1
            if [ $? -ne 0 ]; then
                unset PGPASSWORD
                error "Error al ejecutar sql_db.sql (ejecutalo manualmente para ver el detalle)"
            fi
            ok "sql_db.sql aplicado (o el bot lo hara al arrancar)"
        else
            unset PGPASSWORD
            error "No se encontro sql_db.sql en la carpeta actual"
        fi

        # Limpiar la contraseña de la memoria del proceso
        unset PGPASSWORD

        ok "Base de datos configurada correctamente"
    fi
fi

# -------------------------------------------------------------
# Verificar Ngrok
# -------------------------------------------------------------
echo ""
info "Verificando Ngrok..."
if command -v ngrok > /dev/null 2>&1; then
    ok "Ngrok encontrado: $(ngrok --version 2>&1)"
else
    aviso "Ngrok no esta instalado globalmente"
    info "El sistema usara pyngrok (instalado via pip)"
fi

# -------------------------------------------------------------
# Verificar configuracion de .env
# -------------------------------------------------------------
echo ""
info "Verificando configuracion del archivo .env..."

_env_ok=true

# Cada verificacion: patron que detecta el valor "sin configurar" del .env.example
# y el nombre + hint para el usuario si aparece.
_check_env() {
    local var="$1" patron="$2" hint="$3"
    if grep -qE "^${var}=(${patron})\s*$" .env 2>/dev/null; then
        aviso "$var sin configurar en .env — $hint"
        _env_ok=false
    fi
}
_check_env "DB_PASSWORD"        "tu_password_postgresql_aqui"                             "contrasena de PostgreSQL"
_check_env "WHATSAPP_TOKEN"     "tu_token_de_acceso_permanente_aqui|tu_token_de_acceso"   "https://developers.facebook.com"
_check_env "NGROK_AUTH_TOKEN"   "tu_token_de_ngrok_aqui|tu_token_ngrok_aqui"              "https://dashboard.ngrok.com"
_check_env "GEMINI_AUTH_TOKEN"  "tu_api_key_de_gemini_aqui"                               "https://aistudio.google.com/app/apikey"
_check_env "GROQ_AUTH_TOKEN"    "tu_api_key_de_groq_aqui"                                 "https://console.groq.com/keys"
_check_env "ADMIN_PASSWORD"     "cambia-esta-clave-ahora"                                 "contrasena del panel admin"
_check_env "SECRET_KEY"         "CAMBIA-esta-clave-por-una-larga-y-aleatoria"             'generala con: python -c "import secrets; print(secrets.token_hex(32))"'

if [ "$_env_ok" = true ]; then
    ok "Configuracion verificada correctamente"
else
    aviso "Configura los valores pendientes en .env antes de iniciar el bot"
fi

# -------------------------------------------------------------
# Mensaje final
# -------------------------------------------------------------
echo ""
echo "============================================================"
echo "  INSTALACION COMPLETADA"
echo "============================================================"
echo ""
info "Para iniciar el ChatBot en el futuro:"
echo "  1. Abre Git Bash en la carpeta del proyecto"
echo "  2. Ejecuta: source venv/Scripts/activate"
echo "  3. Ejecuta: python bot_main.py"
echo ""
aviso "IMPORTANTE:"
echo "  - Configura el webhook en WhatsApp Business API"
echo "  - La URL del webhook se mostrara al iniciar el servidor"
echo "  - Usa el VERIFY_TOKEN configurado en .env"
echo ""

# -------------------------------------------------------------
# Ejecutar chatbot
# -------------------------------------------------------------
read -rp "Deseas iniciar el ChatBot ahora? (s/n): " ejecutar

if [[ "${ejecutar,,}" == "s" ]]; then
    echo ""
    info "Iniciando ChatBot..."
    "$PYTHON" bot_main.py
fi

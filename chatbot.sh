#!/usr/bin/env bash
# ============================================================================
# chatbot.sh — Script definitivo del ChatBot Hospital para Ubuntu / Debian.
#
# Un solo comando hace todo: verifica requisitos, crea el entorno virtual,
# instala dependencias, configura .env, crea la BD, abre firewall a la LAN
# y arranca el bot. Equivalente Linux de `chatbot.ps1` (Windows).
#
# Uso:
#   ./chatbot.sh                 Modo automatico (instala lo que falte + arranca)
#   ./chatbot.sh --solo-instalar Solo instala, no arranca
#   ./chatbot.sh --solo-arrancar Solo arranca (uso diario)
#   ./chatbot.sh --verificar     Solo verifica el estado, no modifica nada
#   ./chatbot.sh --lan-cidr CIDR CIDR de la LAN autorizada al panel
#                                (default: se deduce de la IP LAN detectada)
#   ./chatbot.sh --skip-firewall No toca el firewall (si lo gestiona IT)
#   ./chatbot.sh --help          Ayuda
# ============================================================================

set -u                                    # Detectar variables no definidas.

# --- UI helpers -------------------------------------------------------------
if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YLW=$'\033[1;33m'
    BLU=$'\033[0;34m'; CYA=$'\033[0;36m'; DIM=$'\033[2m'; NC=$'\033[0m'
else
    RED=''; GRN=''; YLW=''; BLU=''; CYA=''; DIM=''; NC=''
fi
section() { printf "\n%s-- %s %s%s\n" "$CYA" "$1" "$(printf '%.0s-' $(seq 1 $((72 - ${#1}))))" "$NC"; }
ok()      { printf "  %s[OK]%s   %s\n"   "$GRN" "$NC" "$1"; }
warn()    { printf "  %s[!]%s    %s\n"   "$YLW" "$NC" "$1"; }
err()     { printf "  %s[FAIL]%s %s\n"   "$RED" "$NC" "$1"; }
info()    { printf "         %s%s%s\n"   "$DIM" "$1" "$NC"; }
do_()     { printf "  %s[...]%s  %s\n"   "$BLU" "$NC" "$1"; }
abort()   { err "$1"; echo ""; echo "${YLW}PROCESO DETENIDO. Corrige el problema y vuelve a ejecutar.${NC}"; exit 1; }

# --- Argumentos -------------------------------------------------------------
MODO_INSTALAR=1
MODO_ARRANCAR=1
VERIFICAR=0
LAN_CIDR=""
SKIP_FIREWALL=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --solo-instalar)  MODO_ARRANCAR=0; shift ;;
        --solo-arrancar)  MODO_INSTALAR=0; shift ;;
        --verificar)      VERIFICAR=1; MODO_INSTALAR=0; MODO_ARRANCAR=0; shift ;;
        --lan-cidr)       LAN_CIDR="${2:-}"; shift 2 ;;
        --skip-firewall)  SKIP_FIREWALL=1; shift ;;
        --help|-h)
            grep -E "^#" "$0" | sed -E "s/^#\s?//" | head -25
            exit 0 ;;
        *)
            err "Opcion desconocida: $1"
            echo "Usa --help para ver las opciones disponibles."
            exit 1 ;;
    esac
done

# --- Ubicarse en el directorio del script -----------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
printf "%s===============================================================================%s\n" "$CYA" "$NC"
echo "  ChatBot WhatsApp - Hospital Civil de Ipiales"
printf "  %sScript de instalacion + arranque (Linux)%s\n" "$DIM" "$NC"
printf "%s===============================================================================%s\n" "$CYA" "$NC"

# ============================================================================
# FASE 1: Requisitos del sistema
# ============================================================================
section "1. Requisitos del sistema"

for f in bot_main.py sql_db.sql bot_requirements.txt bot_.env.example; do
    if [[ -f "$f" ]]; then
        ok "$f"
    else
        abort "Falta '$f'. Esta la carpeta del proyecto completa?"
    fi
done

# Python 3.10+
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        ver=$("$cmd" --version 2>&1 | awk '{print $2}')
        maj=$(echo "$ver" | cut -d. -f1)
        min=$(echo "$ver" | cut -d. -f2)
        if [[ "$maj" -eq 3 && "$min" -ge 10 ]]; then
            PYTHON="$cmd"
            ok "Python: $ver ($cmd)"
            break
        fi
    fi
done
if [[ -z "$PYTHON" ]]; then
    err "Python 3.10 o superior no encontrado."
    info "Instalalo con: sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
    abort "Instala Python y vuelve a ejecutar."
fi

# python3-venv (necesario para crear el venv en Ubuntu)
if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
    warn "El modulo 'venv' no esta disponible."
    info "Instalalo con: sudo apt install -y python3-venv"
    abort "Instala python3-venv y vuelve a ejecutar."
fi

# PostgreSQL - psql
if command -v psql >/dev/null 2>&1; then
    ok "psql en PATH: $(command -v psql)"
    PSQL="psql"
else
    warn "psql no encontrado. La creacion de la BD requerira intervencion manual."
    info "Instala PostgreSQL con: sudo apt install -y postgresql postgresql-contrib"
    PSQL=""
fi

# PostgreSQL responde en 5432?
PG_CORRIENDO=0
if timeout 2 bash -c 'cat </dev/null >/dev/tcp/localhost/5432' 2>/dev/null; then
    PG_CORRIENDO=1
    ok "PostgreSQL responde en localhost:5432"
else
    warn "PostgreSQL no responde en localhost:5432 (aun no arranca o no esta instalado)"
    if [[ $MODO_ARRANCAR -eq 1 && $MODO_INSTALAR -eq 0 ]]; then
        abort "Arrancalo con: sudo systemctl start postgresql"
    fi
fi

# ============================================================================
# FASE 2: Entorno virtual (venv)
# ============================================================================
if [[ $MODO_INSTALAR -eq 1 ]]; then
    section "2. Entorno virtual Python (venv)"

    if [[ -x "venv/bin/python" ]]; then
        ok "venv ya existe"
    else
        do_ "Creando entorno virtual..."
        "$PYTHON" -m venv venv || abort "No se pudo crear el entorno virtual."
        ok "venv creado"
    fi
    VENV_PY="$SCRIPT_DIR/venv/bin/python"

    # ------------------------------------------------------------------------
    # FASE 3: Dependencias (con marcador de cache)
    # ------------------------------------------------------------------------
    section "3. Dependencias Python"
    marker="venv/.install_ok"
    if [[ -f "$marker" && "$marker" -nt "bot_requirements.txt" ]]; then
        ok "Dependencias ya instaladas (marcador reciente). Salta reinstalacion."
        info "Para forzar reinstalacion: rm venv/.install_ok"
    else
        do_ "Actualizando pip..."
        "$VENV_PY" -m pip install --upgrade pip --quiet
        do_ "Instalando dependencias (tarda 3-5 min la primera vez)..."
        if ! "$VENV_PY" -m pip install -r bot_requirements.txt --quiet; then
            abort "Error al instalar dependencias. Revisa la conexion a Internet."
        fi
        date > "$marker"
        ok "Dependencias instaladas"
    fi
fi

# ============================================================================
# FASE 4: Archivo .env
# ============================================================================
if [[ $MODO_INSTALAR -eq 1 || $MODO_ARRANCAR -eq 1 || $VERIFICAR -eq 1 ]]; then
    section "4. Configuracion (.env)"

    if [[ ! -f ".env" ]]; then
        if [[ $MODO_INSTALAR -eq 0 ]]; then
            abort ".env no existe. Ejecuta con --solo-instalar o modo automatico primero."
        fi
        warn ".env no existe. Creando desde plantilla..."
        cp bot_.env.example .env
        ok "Plantilla .env creada"
        EDITOR_BIN="${EDITOR:-nano}"
        info "Voy a abrir '$EDITOR_BIN'. Rellena TODAS las claves marcadas con 'tu_'."
        info "Guarda y cierra el editor cuando termines. (Ctrl+O, Enter, Ctrl+X en nano)"
        read -rp "Enter para abrir el editor..." _
        "$EDITOR_BIN" .env || warn "El editor devolvio un codigo de error, revisa el .env manualmente."
    else
        ok ".env existe"
    fi

    # Leer .env sin exportar (evitar contaminar el entorno)
    _read_env() {
        local key="$1"
        awk -F= -v k="$key" '
            /^[[:space:]]*#/ {next}
            /^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*=/ {
                split($0, a, "=")
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", a[1])
                if (a[1] == k) {
                    v=$0; sub(/^[^=]*=/, "", v)
                    gsub(/^[[:space:]]+|[[:space:]"'\'']+$/, "", v)
                    print v; exit
                }
            }' .env
    }
    PORT="$(_read_env PORT)"; PORT="${PORT:-8000}"
    BOT_HOST="$(_read_env HOST)"; BOT_HOST="${BOT_HOST:-127.0.0.1}"
    DB_HOST="$(_read_env DB_HOST)"; DB_HOST="${DB_HOST:-localhost}"
    DB_PORT="$(_read_env DB_PORT)"; DB_PORT="${DB_PORT:-5432}"
    DB_NAME="$(_read_env DB_NAME)"; DB_NAME="${DB_NAME:-hospital_chatbot}"
    DB_USER="$(_read_env DB_USER)"; DB_USER="${DB_USER:-postgres}"
    DB_PASS="$(_read_env DB_PASSWORD)"
    NGROK="$(_read_env NGROK_ENABLED)"; NGROK="${NGROK:-true}"
    ADMIN_PWD="$(_read_env ADMIN_PASSWORD)"
    SECRET_KEY="$(_read_env SECRET_KEY)"

    # Validar claves criticas
    faltantes=()
    for pair in \
        "DB_PASSWORD:contrasena de PostgreSQL" \
        "WHATSAPP_TOKEN:token de WhatsApp Business API" \
        "WHATSAPP_PHONE_NUMBER_ID:Phone Number ID de WhatsApp" \
        "NGROK_AUTH_TOKEN:token de Ngrok" \
        "ADMIN_PASSWORD:contrasena del panel admin" \
        "SECRET_KEY:clave de firma de cookies"
    do
        k="${pair%%:*}"; d="${pair#*:}"
        v="$(_read_env "$k")"
        if [[ -z "$v" || "$v" =~ ^(tu_|cambia|CAMBIA|\<) ]]; then
            faltantes+=("$k ($d)")
        fi
    done
    if [[ ${#faltantes[@]} -gt 0 ]]; then
        warn "Las siguientes variables NO estan configuradas en .env:"
        for f in "${faltantes[@]}"; do info "  * $f"; done
        if [[ $MODO_ARRANCAR -eq 1 ]]; then
            abort "Configura .env y vuelve a ejecutar. Ver IMPLEMENTACION_LINUX.md para el paso a paso."
        fi
    else
        ok "Claves criticas del .env configuradas"
    fi
fi

# ============================================================================
# FASE 5: Base de datos
# ============================================================================
if [[ $MODO_INSTALAR -eq 1 && -n "$PSQL" && $PG_CORRIENDO -eq 1 ]]; then
    section "5. Base de datos PostgreSQL"

    export PGPASSWORD="$DB_PASS"

    # Verificar credenciales
    if ! "$PSQL" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -c "SELECT 1" >/dev/null 2>&1; then
        unset PGPASSWORD
        warn "No pude autenticarme con el usuario '$DB_USER'."
        info "Verifica DB_USER y DB_PASSWORD en .env. Si es la primera vez que"
        info "usas PostgreSQL en Ubuntu, quiza necesitas fijar la contrasena:"
        info "  sudo -u postgres psql -c \"ALTER USER $DB_USER PASSWORD 'tu_clave';\""
        abort "Corrige credenciales y vuelve a ejecutar."
    fi

    # BD existe?
    existe=$("$PSQL" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -tAc \
             "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null)
    if [[ "$existe" == "1" ]]; then
        ok "Base de datos '$DB_NAME' existe"
    else
        do_ "Creando base de datos '$DB_NAME'..."
        if ! "$PSQL" -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
             -c "CREATE DATABASE $DB_NAME ENCODING 'UTF8' TEMPLATE template0;" >/dev/null 2>&1; then
            unset PGPASSWORD
            abort "No se pudo crear la BD. Revisa permisos del usuario."
        fi
        ok "Base de datos '$DB_NAME' creada"
    fi

    unset PGPASSWORD
    info "sql_db.sql se aplicara automaticamente al arrancar bot_main.py."
fi

# ============================================================================
# Salir aqui si es --solo-instalar
# ============================================================================
if [[ $MODO_INSTALAR -eq 1 && $MODO_ARRANCAR -eq 0 && $VERIFICAR -eq 0 ]]; then
    section "Instalacion completa"
    ok "El sistema esta listo para arrancar."
    info "Para arrancarlo ahora ejecuta:  ./chatbot.sh --solo-arrancar"
    exit 0
fi

# ============================================================================
# FASE 6: HOST=0.0.0.0
# ============================================================================
if [[ $MODO_ARRANCAR -eq 1 ]]; then
    section "6. HOST=0.0.0.0 (exponer a la LAN)"
    if [[ "$BOT_HOST" == "0.0.0.0" ]]; then
        ok "HOST=0.0.0.0 -> el bot escuchara en todas las interfaces"
    else
        warn "HOST=$BOT_HOST -> reescribiendo a 0.0.0.0 en .env"
        # Reemplaza in-place. Backup con extension .bak por seguridad.
        if grep -qE "^HOST=" .env; then
            sed -i.bak -E 's/^HOST=.*/HOST=0.0.0.0/' .env
        else
            printf "\nHOST=0.0.0.0\n" >> .env
        fi
        rm -f .env.bak
        BOT_HOST="0.0.0.0"
        ok "HOST actualizado en .env"
    fi
fi

# ============================================================================
# FASE 7: IP LAN + firewall (ufw)
# ============================================================================
LAN_IP=""
if [[ $MODO_ARRANCAR -eq 1 || $VERIFICAR -eq 1 ]]; then
    section "7. IP LAN y firewall (ufw)"

    # Detectar IP LAN — preferir la de la ruta por defecto
    LAN_IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '/src/ {for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n1)
    if [[ -z "$LAN_IP" ]]; then
        LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    fi
    if [[ -z "$LAN_IP" ]]; then
        abort "No se detecto ninguna IP LAN. El equipo esta conectado a la red?"
    fi
    ok "IP LAN detectada: $LAN_IP"

    # CIDR
    if [[ -z "$LAN_CIDR" ]]; then
        IFS='.' read -r a b c _ <<< "$LAN_IP"
        LAN_CIDR="${a}.${b}.${c}.0/24"
        info "CIDR deducido: $LAN_CIDR (usa --lan-cidr para cambiarlo)"
    else
        info "CIDR autorizado: $LAN_CIDR (parametro)"
    fi

    # Firewall
    if [[ $SKIP_FIREWALL -eq 1 ]]; then
        warn "Firewall omitido (--skip-firewall). Asegurate que IT autorizo el puerto $PORT."
    elif [[ $MODO_ARRANCAR -eq 1 ]]; then
        if ! command -v ufw >/dev/null 2>&1; then
            warn "ufw no esta instalado."
            info "Instalalo con: sudo apt install -y ufw"
            info "Luego habilita la regla manualmente:"
            info "  sudo ufw allow from $LAN_CIDR to any port $PORT proto tcp"
        else
            # ufw requiere sudo. Si no somos root ni tenemos sudo, avisar.
            if [[ "$EUID" -ne 0 ]] && ! sudo -n true 2>/dev/null; then
                warn "Se necesita sudo para gestionar el firewall automaticamente."
                info "Ejecuta manualmente:"
                info "  sudo ufw allow from $LAN_CIDR to any port $PORT proto tcp comment 'ChatBot Hospital'"
            else
                # Eliminar regla previa con el mismo comentario (si existe)
                sudo ufw --force delete allow "$PORT"/tcp 2>/dev/null || true
                if sudo ufw allow from "$LAN_CIDR" to any port "$PORT" proto tcp \
                   comment "ChatBot Hospital LAN" >/dev/null 2>&1; then
                    ok "Regla de firewall creada/actualizada (puerto $PORT, origen $LAN_CIDR)"
                    # Recordar activar ufw si esta inactivo
                    if sudo ufw status | grep -q "Status: inactive"; then
                        warn "ufw esta inactivo. Actívalo con: sudo ufw enable"
                    fi
                else
                    warn "No se pudo crear la regla de firewall automaticamente."
                fi
            fi
        fi
    fi
fi

# ============================================================================
# Salir aqui si es --verificar
# ============================================================================
if [[ $VERIFICAR -eq 1 ]]; then
    section "Verificacion completa"
    ok "El sistema esta en condiciones de arrancar."
    info "Para arrancarlo ejecuta:  ./chatbot.sh"
    exit 0
fi

# ============================================================================
# FASE 8: Arrancar
# ============================================================================
section "8. Arrancar el chatbot"
echo ""
printf "  %sPanel administrativo (solo desde la LAN del hospital):%s\n" "$NC" "$NC"
printf "     %shttp://%s:%s/admin%s\n" "$GRN" "$LAN_IP" "$PORT" "$NC"
echo ""
printf "  %sLocal (esta misma maquina):%s\n" "$NC" "$NC"
printf "     %shttp://127.0.0.1:%s/admin%s\n" "$GRN" "$PORT" "$NC"
echo ""
if [[ "$NGROK" == "true" ]]; then
    echo "  Webhook de WhatsApp:"
    info "     La URL de ngrok se mostrara abajo cuando arranque."
    info "     Copiala + '/webhook' a Meta > WhatsApp > Configuration."
else
    warn "NGROK_ENABLED=false -> el webhook no se expone por Internet."
    info "Activalo en .env si quieres recibir mensajes reales por WhatsApp."
fi
echo ""
info "Detener el bot: Ctrl+C"
echo ""
section "Salida del bot"
echo ""

VENV_PY="$SCRIPT_DIR/venv/bin/python"
exec "$VENV_PY" "$SCRIPT_DIR/bot_main.py"

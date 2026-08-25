#!/usr/bin/env bash
# ============================================================================
# stop_bot.sh — Detiene SOLO el chatbot (proceso que escucha en su puerto) y
# el túnel ngrok que ese proceso haya lanzado. NO toca otros procesos.
#
# Uso:
#   ./stop_bot.sh           # usa el puerto 8000 (por defecto del .env)
#   ./stop_bot.sh 8001      # otro puerto si cambiaste PORT en .env
#
# Requiere: lsof O ss (Ubuntu 22.04+ trae iproute2 con ss por defecto).
# ============================================================================

set -u
PORT="${1:-8000}"

# ---- Detectar PIDs que ESCUCHAN en el puerto ------------------------------
PIDS=""
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | sort -u)
elif command -v ss >/dev/null 2>&1; then
    # Formato: users:(("python",pid=1234,fd=7))
    PIDS=$(ss -lntp "sport = :$PORT" 2>/dev/null \
           | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u)
elif command -v fuser >/dev/null 2>&1; then
    PIDS=$(fuser -n tcp "$PORT" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$' | sort -u)
else
    echo "❌ No hay lsof, ss ni fuser en este sistema."
    echo "   Instala uno con:  sudo apt install -y lsof   (o iproute2)"
    exit 1
fi

if [[ -z "$PIDS" ]]; then
    echo "ℹ️  Ningún proceso escucha en el puerto $PORT. El bot ya está detenido."
    # Aun así intenta cerrar ngrok huérfano por si acaso.
    pkill -x ngrok 2>/dev/null && echo "   · limpiado ngrok huérfano"
    exit 0
fi

# ---- Detener el chatbot ---------------------------------------------------
for PID in $PIDS; do
    echo "🛑 Deteniendo el chatbot (PID $PID, puerto $PORT)…"

    # Cerrar ngrok que sea HIJO de este proceso (no otros ngrok del sistema)
    HIJOS=$(pgrep -P "$PID" -x ngrok 2>/dev/null)
    for NG in $HIJOS; do
        echo "   · cerrando su túnel ngrok (PID $NG)"
        kill -TERM "$NG" 2>/dev/null
    done

    # Señal de cierre limpio, luego forzada si no responde
    if kill -TERM "$PID" 2>/dev/null; then
        # Esperar hasta 10 s a que salga limpio
        for _ in $(seq 1 10); do
            kill -0 "$PID" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$PID" 2>/dev/null; then
            echo "   · no respondió, forzando (KILL)…"
            kill -KILL "$PID" 2>/dev/null
        fi
        echo "   ✅ Bot detenido."
    else
        echo "   ⚠️  No se pudo enviar señal al PID $PID (¿permisos?)"
    fi
done

# ---- Barrido final de ngrok huérfano --------------------------------------
# Cierra cualquier ngrok que el chatbot haya arrancado y no fuera hijo directo
# (ej. pyngrok relanzado). Solo mata procesos llamados exactamente "ngrok".
if pgrep -x ngrok >/dev/null 2>&1; then
    pkill -x ngrok 2>/dev/null && echo "🧹 Ngrok(s) huérfano(s) cerrado(s)"
fi

echo "👍 Listo. Los demás servicios de la máquina siguen intactos."

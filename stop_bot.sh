#!/bin/bash
#############################################
# Detiene SOLO el chatbot (el proceso que escucha en su puerto) y el túnel
# ngrok que ese proceso haya lanzado. NO toca otros proyectos Python/ngrok
# que tengas corriendo.
#
# Uso:   ./stop_bot.sh           # usa el puerto 8000 (por defecto)
#        ./stop_bot.sh 8001      # otro puerto si cambiaste PORT en .env
#############################################

PORT="${1:-8000}"

# PID(s) que ESCUCHAN en el puerto del bot (columna local address termina en :PORT)
PIDS=$(netstat -ano | awk '$4=="LISTENING" && $2 ~ /:'"$PORT"'$/ {print $5}' | sort -u)

if [ -z "$PIDS" ]; then
  echo "ℹ️  No hay ningún proceso escuchando en el puerto $PORT. El bot ya está detenido."
  exit 0
fi

for PID in $PIDS; do
  echo "🛑 Deteniendo el chatbot (PID $PID, puerto $PORT)…"

  # Cerrar SOLO el/los ngrok.exe que sean HIJOS de este proceso (no otros ngrok)
  HIJOS_NGROK=$(powershell -NoProfile -Command \
    "Get-CimInstance Win32_Process -Filter \"ParentProcessId=$PID and Name='ngrok.exe'\" | Select-Object -ExpandProperty ProcessId" \
    2>/dev/null | tr -d '\r')

  for NG in $HIJOS_NGROK; do
    [ -n "$NG" ] && { echo "   · cerrando su túnel ngrok (PID $NG)"; taskkill //F //PID "$NG" >/dev/null 2>&1; }
  done

  taskkill //F //PID "$PID" >/dev/null 2>&1 && echo "   ✅ Bot detenido."
done

echo "👍 Listo. Tus otros proyectos (otros puertos) siguen conectados."

#requires -Version 5.1
<#
.SYNOPSIS
    Script definitivo del ChatBot Hospital: instalacion + arranque en un solo comando.

.DESCRIPTION
    Automatiza TODO lo necesario para instalar y arrancar el chatbot en un PC
    del hospital. Es idempotente: puedes ejecutarlo varias veces sin efectos
    secundarios. Cada fase verifica el estado y solo actua si algo falta.

    Fases:
      1. Verifica requisitos del sistema (Python 3.10+, PostgreSQL).
      2. Crea el entorno virtual (venv) si no existe.
      3. Instala las dependencias Python.
      4. Copia .env desde la plantilla si no existe y abre el editor.
      5. Crea la base de datos si no existe (y ejecuta sql_db.sql).
      6. Corrige HOST=0.0.0.0 en .env para exponer a la LAN.
      7. Configura el firewall (puerto 8000 solo a la LAN).
      8. Arranca el chatbot y muestra las URLs de acceso.

    El panel administrativo quedara accesible desde la LAN en:
        http://<IP-LAN>:<PORT>/admin
    El resto de la red queda bloqueado por firewall.

.PARAMETER SoloInstalar
    Ejecuta solo las fases 1-5 (instalacion) y sale. Util para preparar la
    maquina sin arrancar todavia.

.PARAMETER SoloArrancar
    Salta las fases de instalacion y va directo al arranque. Util para
    reinicios cotidianos cuando ya todo esta instalado.

.PARAMETER Verificar
    Solo verifica el estado del sistema (sin instalar, sin arrancar).

.PARAMETER LanCidr
    Rango CIDR de la LAN autorizada al panel. Por defecto se deduce de la IP
    LAN detectada (ej. 192.168.1.10/24 -> 192.168.1.0/24). Si tu LAN usa otro
    rango, pasalo explicito (ej. -LanCidr "10.10.0.0/16").

.PARAMETER SkipFirewall
    No toca el firewall (util si no eres administrador o ya lo gestiona IT).

.EXAMPLE
    .\chatbot.ps1
    Modo automatico: verifica, instala lo que falte y arranca el bot.

.EXAMPLE
    .\chatbot.ps1 -SoloInstalar
    Solo instala y prepara todo, sin arrancar el bot.

.EXAMPLE
    .\chatbot.ps1 -SoloArrancar
    Solo arranca (uso diario, cuando ya esta instalado).

.EXAMPLE
    .\chatbot.ps1 -Verificar
    Solo verifica el estado sin modificar nada.

.EXAMPLE
    .\chatbot.ps1 -LanCidr "10.10.0.0/16"
    Arranca autorizando el rango 10.10.x.x en el firewall.
#>

param(
    [switch]$SoloInstalar,
    [switch]$SoloArrancar,
    [switch]$Verificar,
    [string]$LanCidr,
    [switch]$SkipFirewall
)

$ErrorActionPreference = 'Stop'
$RuleName = "ChatBot Hospital LAN"

# ============================================================================
# UI helpers
# ============================================================================
function Write-Section([string]$title) {
    Write-Host ""
    Write-Host "-- $title " -ForegroundColor Cyan -NoNewline
    Write-Host ("-" * ([Math]::Max(0, 74 - $title.Length))) -ForegroundColor DarkCyan
}
function Write-Ok([string]$msg)   { Write-Host "  [OK]   " -ForegroundColor Green  -NoNewline; Write-Host $msg }
function Write-Warn([string]$msg) { Write-Host "  [!]    " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Err([string]$msg)  { Write-Host "  [FAIL] " -ForegroundColor Red    -NoNewline; Write-Host $msg }
function Write-Info([string]$msg) { Write-Host "         $msg" -ForegroundColor DarkGray }
function Write-Do([string]$msg)   { Write-Host "  [...]  " -ForegroundColor Blue   -NoNewline; Write-Host $msg }
function Abort([string]$msg) {
    Write-Err $msg
    Write-Host ""
    Write-Host "PROCESO DETENIDO. Corrige el problema y vuelve a ejecutar." -ForegroundColor Yellow
    exit 1
}

# ============================================================================
# Ubicarse en el directorio del script
# ============================================================================
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  ChatBot WhatsApp - Hospital Civil de Ipiales" -ForegroundColor White
Write-Host "  Script de instalacion + arranque" -ForegroundColor DarkGray
Write-Host "===============================================================================" -ForegroundColor Cyan

# Determinar modo
$ModoInstalar = $true
$ModoArrancar = $true
if ($SoloInstalar) { $ModoArrancar = $false }
if ($SoloArrancar) { $ModoInstalar = $false }
if ($Verificar)    { $ModoInstalar = $false; $ModoArrancar = $false }

# ============================================================================
# FASE 1: Verificar requisitos del sistema (Python, PostgreSQL, archivos)
# ============================================================================
Write-Section "1. Requisitos del sistema"

# --- Archivos del proyecto ---
foreach ($f in @('bot_main.py','sql_db.sql','bot_requirements.txt','bot_.env.example')) {
    if (Test-Path -LiteralPath $f) {
        Write-Ok $f
    } else {
        Abort "Falta '$f'. Esta la carpeta del proyecto completa?"
    }
}

# --- Python ---
$PythonExe = $null
try {
    $ver = & python --version 2>&1
    if ($ver -match "Python 3\.(1[0-9]|[2-9][0-9])") {
        $PythonExe = "python"
        Write-Ok "Python en PATH: $ver"
    }
} catch {}

if (-not $PythonExe) {
    # Buscar en ubicaciones tipicas de Windows
    $usuario = $env:USERNAME
    foreach ($v in @('312','311','310')) {
        $ruta = "C:\Users\$usuario\AppData\Local\Programs\Python\Python$v\python.exe"
        if (Test-Path -LiteralPath $ruta) {
            $PythonExe = $ruta
            $ver = & $ruta --version 2>&1
            Write-Ok "Python encontrado: $ver ($ruta)"
            break
        }
    }
}

if (-not $PythonExe) {
    Write-Err "Python 3.10+ no encontrado."
    Write-Info "Descargalo desde: https://www.python.org/downloads/"
    Write-Info "IMPORTANTE al instalar: marca la casilla 'Add Python to PATH'"
    Abort "Instala Python y vuelve a ejecutar."
}

# --- PostgreSQL (buscar psql para operaciones de BD) ---
$PsqlExe = $null
$Psql = Get-Command psql -ErrorAction SilentlyContinue
if ($Psql) {
    $PsqlExe = $Psql.Source
    Write-Ok "psql en PATH: $PsqlExe"
} else {
    foreach ($v in 18,17,16,15,14) {
        $p = "C:\Program Files\PostgreSQL\$v\bin\psql.exe"
        if (Test-Path -LiteralPath $p) { $PsqlExe = $p; Write-Ok "psql encontrado: v$v"; break }
    }
}
if (-not $PsqlExe) {
    Write-Warn "psql no encontrado. La creacion de la BD requerira intervencion manual."
    Write-Info "Descarga PostgreSQL desde: https://www.postgresql.org/download/windows/"
}

# --- Ping a PostgreSQL para saber si esta corriendo ---
$PgCorriendo = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect('localhost', 5432)
    $tcp.Close()
    $PgCorriendo = $true
    Write-Ok "PostgreSQL responde en localhost:5432"
} catch {
    Write-Warn "PostgreSQL no responde en localhost:5432 (aun no arranca o no esta instalado)"
    if ($ModoArrancar -and -not $ModoInstalar) {
        Abort "PostgreSQL debe estar corriendo. Abre 'Servicios' de Windows e inicia 'postgresql-x64-XX'."
    }
}

# ============================================================================
# FASE 2: Entorno virtual (venv)
# ============================================================================
if ($ModoInstalar) {
    Write-Section "2. Entorno virtual Python (venv)"

    if (Test-Path -LiteralPath 'venv\Scripts\python.exe') {
        Write-Ok "venv ya existe"
    } else {
        Write-Do "Creando entorno virtual..."
        & $PythonExe -m venv venv
        if (-not (Test-Path -LiteralPath 'venv\Scripts\python.exe')) {
            Abort "No se pudo crear el entorno virtual."
        }
        Write-Ok "venv creado"
    }

    $VenvPy = Join-Path $ScriptDir 'venv\Scripts\python.exe'

    # ========================================================================
    # FASE 3: Dependencias
    # ========================================================================
    Write-Section "3. Dependencias Python"

    # Marcador: si existe .venv_install_ok con fecha reciente, saltar reinstalacion
    $marker = 'venv\.install_ok'
    $bot_reqs_mtime = (Get-Item bot_requirements.txt).LastWriteTime
    $marker_mtime = if (Test-Path $marker) { (Get-Item $marker).LastWriteTime } else { [DateTime]::MinValue }

    if ($marker_mtime -gt $bot_reqs_mtime) {
        Write-Ok "Dependencias ya instaladas (marcador reciente). Salta reinstalacion."
        Write-Info "Para forzar reinstalacion: borra 'venv\.install_ok'"
    } else {
        Write-Do "Actualizando pip..."
        & $VenvPy -m pip install --upgrade pip --quiet 2>&1 | Out-Null

        Write-Do "Instalando dependencias (tarda 3-5 min la primera vez)..."
        & $VenvPy -m pip install -r bot_requirements.txt --quiet 2>&1 | ForEach-Object { $_ }
        if ($LASTEXITCODE -ne 0) {
            Abort "Error al instalar dependencias. Revisa la conexion a Internet."
        }
        Set-Content -LiteralPath $marker -Value (Get-Date).ToString() -Encoding UTF8
        Write-Ok "Dependencias instaladas"
    }
}

# ============================================================================
# FASE 4: Archivo .env
# ============================================================================
if ($ModoInstalar -or $ModoArrancar -or $Verificar) {
    Write-Section "4. Configuracion (.env)"

    if (-not (Test-Path -LiteralPath '.env')) {
        if (-not $ModoInstalar) {
            Abort ".env no existe. Ejecuta con -SoloInstalar o modo automatico primero."
        }
        Write-Warn ".env no existe. Creando desde plantilla..."
        Copy-Item -LiteralPath 'bot_.env.example' -Destination '.env'
        Write-Ok "Plantilla .env creada"
        Write-Info "Voy a abrir el editor. Rellena TODAS las claves marcadas con 'tu_'."
        Write-Info "Guarda y cierra el editor cuando termines."
        Start-Process notepad.exe -ArgumentList '.env' -Wait
    } else {
        Write-Ok ".env existe"
    }

    # Leer el .env
    $env_kv = @{}
    foreach ($line in Get-Content -LiteralPath '.env') {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' -and $line -notmatch '^\s*#') {
            $env_kv[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }

    # Validar claves criticas
    $criticas = @{
        'DB_PASSWORD'              = 'Contrasena de PostgreSQL'
        'WHATSAPP_TOKEN'           = 'Token de WhatsApp Business API (Meta)'
        'WHATSAPP_PHONE_NUMBER_ID' = 'Phone Number ID de WhatsApp'
        'NGROK_AUTH_TOKEN'         = 'Token de Ngrok'
        'ADMIN_PASSWORD'           = 'Contrasena del panel admin'
        'SECRET_KEY'               = 'Clave de firma de cookies'
    }
    $faltantes = @()
    foreach ($k in $criticas.Keys) {
        $v = $env_kv[$k]
        if ([string]::IsNullOrWhiteSpace($v) -or $v -match '^(tu_|cambia|CAMBIA|<)') {
            $faltantes += "$k ($($criticas[$k]))"
        }
    }
    if ($faltantes.Count -gt 0) {
        Write-Warn "Las siguientes variables NO estan configuradas:"
        foreach ($f in $faltantes) { Write-Info "  * $f" }
        if ($ModoArrancar) {
            Abort "Configura .env y vuelve a ejecutar. Ver IMPLEMENTACION_HOSPITAL.md para el paso a paso."
        }
    } else {
        Write-Ok "Claves criticas del .env configuradas"
    }

    # Extraer valores para uso posterior
    $Port     = if ($env_kv.ContainsKey('PORT')) { [int]$env_kv['PORT'] } else { 8000 }
    $BotHost  = if ($env_kv.ContainsKey('HOST')) { $env_kv['HOST'] } else { '127.0.0.1' }
    $DbHost   = if ($env_kv.ContainsKey('DB_HOST')) { $env_kv['DB_HOST'] } else { 'localhost' }
    $DbPort   = if ($env_kv.ContainsKey('DB_PORT')) { [int]$env_kv['DB_PORT'] } else { 5432 }
    $DbName   = if ($env_kv.ContainsKey('DB_NAME')) { $env_kv['DB_NAME'] } else { 'hospital_chatbot' }
    $DbUser   = if ($env_kv.ContainsKey('DB_USER')) { $env_kv['DB_USER'] } else { 'postgres' }
    $DbPass   = if ($env_kv.ContainsKey('DB_PASSWORD')) { $env_kv['DB_PASSWORD'] } else { '' }
    $Ngrok    = if ($env_kv.ContainsKey('NGROK_ENABLED')) { $env_kv['NGROK_ENABLED'] } else { 'true' }
}

# ============================================================================
# FASE 5: Base de datos
# ============================================================================
if ($ModoInstalar -and $PsqlExe -and $PgCorriendo) {
    Write-Section "5. Base de datos PostgreSQL"

    $env:PGPASSWORD = $DbPass
    try {
        # Comprobar si la BD existe
        $existe = & $PsqlExe -h $DbHost -p $DbPort -U $DbUser -tAc "SELECT 1 FROM pg_database WHERE datname='$DbName'" 2>&1
        if ($existe -eq '1') {
            Write-Ok "Base de datos '$DbName' existe"
        } else {
            Write-Do "Creando base de datos '$DbName'..."
            $creada = & $PsqlExe -h $DbHost -p $DbPort -U $DbUser -c "CREATE DATABASE $DbName ENCODING 'UTF8' TEMPLATE template0;" 2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Err "No se pudo crear la BD. Verifica DB_USER y DB_PASSWORD en .env."
                Write-Info "Detalle: $creada"
                Abort "Corrige credenciales y vuelve a ejecutar."
            }
            Write-Ok "Base de datos '$DbName' creada"
        }

        # sql_db.sql se ejecutara al arrancar el bot (idempotente).
        Write-Info "sql_db.sql se aplicara automaticamente al arrancar bot_main.py."
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

# ============================================================================
# Salir aqui si es -SoloInstalar
# ============================================================================
if ($SoloInstalar) {
    Write-Section "Instalacion completa"
    Write-Ok "El sistema esta listo para arrancar."
    Write-Info "Para arrancarlo ahora ejecuta:  .\chatbot.ps1 -SoloArrancar"
    exit 0
}

# ============================================================================
# FASE 6: HOST=0.0.0.0 (necesario para la LAN)
# ============================================================================
if ($ModoArrancar) {
    Write-Section "6. HOST=0.0.0.0 (exponer a la LAN)"

    if ($BotHost -eq '0.0.0.0') {
        Write-Ok "HOST=0.0.0.0 -> el bot escuchara en todas las interfaces"
    } else {
        Write-Warn "HOST=$BotHost -> se reescribira a 0.0.0.0 en .env"
        $content = Get-Content -LiteralPath '.env' -Raw
        if ($content -match "(?m)^HOST\s*=.*$") {
            $content = [regex]::Replace($content, "(?m)^HOST\s*=.*$", "HOST=0.0.0.0")
        } else {
            $content += "`nHOST=0.0.0.0"
        }
        Set-Content -LiteralPath '.env' -Value $content -Encoding UTF8 -NoNewline
        $BotHost = '0.0.0.0'
        Write-Ok "HOST actualizado en .env"
    }
}

# ============================================================================
# FASE 7: IP LAN + firewall
# ============================================================================
$LanIp = $null
if ($ModoArrancar -or $Verificar) {
    Write-Section "7. IP LAN y firewall"

    $candidates = Get-NetIPAddress -AddressFamily IPv4 -PrefixOrigin Dhcp,Manual -ErrorAction SilentlyContinue |
                  Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixLength -lt 32 } |
                  Sort-Object -Property InterfaceMetric
    if (-not $candidates) {
        Abort "No se detecto ninguna IP LAN. El equipo esta conectado a la red?"
    }
    $primary = $candidates | Select-Object -First 1
    $LanIp   = $primary.IPAddress
    Write-Ok "IP LAN: $LanIp (interfaz: $($primary.InterfaceAlias))"
    if ($candidates.Count -gt 1) {
        Write-Info "Otras interfaces detectadas:"
        $candidates | Select-Object -Skip 1 | ForEach-Object {
            Write-Info "  - $($_.IPAddress) ($($_.InterfaceAlias))"
        }
    }

    # Deducir CIDR si no lo pasaron
    if (-not $LanCidr) {
        $octets = $LanIp.Split('.')
        $LanCidr = "$($octets[0]).$($octets[1]).$($octets[2]).0/24"
        Write-Info "CIDR autorizado: $LanCidr (deducido, usa -LanCidr para cambiarlo)"
    } else {
        Write-Info "CIDR autorizado: $LanCidr (parametro)"
    }

    # Firewall
    if ($SkipFirewall) {
        Write-Warn "Firewall omitido (-SkipFirewall). Asegurate que IT autorizo el puerto $Port."
    } elseif ($ModoArrancar) {
        $isAdmin = ([Security.Principal.WindowsPrincipal] `
                    [Security.Principal.WindowsIdentity]::GetCurrent() `
                  ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

        if (-not $isAdmin) {
            Write-Warn "Ejecuta PowerShell como Administrador para gestionar el firewall automaticamente."
            Write-Info "O ejecuta manualmente en una consola admin:"
            Write-Info "  netsh advfirewall firewall add rule name=`"$RuleName`" dir=in action=allow protocol=TCP localport=$Port remoteip=$LanCidr"
        } else {
            $existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
            if ($existing) {
                Set-NetFirewallRule -DisplayName $RuleName -LocalPort $Port -RemoteAddress $LanCidr -Enabled True | Out-Null
                Write-Ok "Regla de firewall actualizada (puerto $Port, origen $LanCidr)"
            } else {
                New-NetFirewallRule -DisplayName $RuleName `
                    -Direction Inbound -Action Allow -Protocol TCP `
                    -LocalPort $Port -RemoteAddress $LanCidr `
                    -Profile Any -Enabled True | Out-Null
                Write-Ok "Regla de firewall creada (puerto $Port, origen $LanCidr)"
            }
        }
    }
}

# ============================================================================
# Salir aqui si es -Verificar
# ============================================================================
if ($Verificar) {
    Write-Section "Verificacion completa"
    Write-Ok "El sistema esta en condiciones de arrancar."
    Write-Info "Para arrancarlo ejecuta:  .\chatbot.ps1"
    exit 0
}

# ============================================================================
# FASE 8: Arrancar el bot
# ============================================================================
Write-Section "8. Arrancar el chatbot"
Write-Host ""
Write-Host "  Panel administrativo (solo desde la LAN del hospital):" -ForegroundColor White
Write-Host "     http://${LanIp}:${Port}/admin" -ForegroundColor Green
Write-Host ""
Write-Host "  Local (esta misma maquina):" -ForegroundColor White
Write-Host "     http://127.0.0.1:${Port}/admin" -ForegroundColor Green
Write-Host ""
if ($Ngrok -eq 'true') {
    Write-Host "  Webhook de WhatsApp:" -ForegroundColor White
    Write-Host "     La URL de ngrok se mostrara abajo cuando arranque." -ForegroundColor DarkGray
    Write-Host "     Copiala + '/webhook' a Meta > WhatsApp > Configuration." -ForegroundColor DarkGray
} else {
    Write-Warn "NGROK_ENABLED=false -> el webhook no se expone por Internet."
    Write-Info "Activalo en .env si quieres recibir mensajes reales por WhatsApp."
}
Write-Host ""
Write-Host "  Detener el bot: Ctrl+C" -ForegroundColor DarkGray
Write-Host ""
Write-Section "Salida del bot"
Write-Host ""

& "$ScriptDir\venv\Scripts\python.exe" "$ScriptDir\bot_main.py"
$exit = $LASTEXITCODE

Write-Host ""
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  El bot se detuvo (exit code: $exit)" -ForegroundColor White
Write-Host "===============================================================================" -ForegroundColor Cyan
exit $exit

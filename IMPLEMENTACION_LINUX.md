# Guía de implementación del ChatBot en Linux (Ubuntu)

Guía paso a paso para desplegar el chatbot en un servidor **Ubuntu** de la
intranet del hospital. Escrita para personal técnico con experiencia básica
en Linux — incluye copiar-pegar exacto de cada comando.

**Distribución objetivo:** Ubuntu Server 22.04 LTS o 24.04 LTS (Debian 12
también funciona con cambios mínimos).

**Tiempo estimado:** 1-2 horas la primera vez.

---

## 📑 Antes de empezar

Necesitas:

- ✅ Un **servidor con Ubuntu Server 22.04+** ya instalado y accesible por SSH.
- ✅ **Usuario con permisos sudo** (no uses root directamente).
- ✅ **IP fija** en la LAN del hospital (que IT te la reserve por DHCP o la
  configures en `/etc/netplan`).
- ✅ **Conexión a Internet** para descargar dependencias.
- ✅ Los mismos tokens externos que en la guía de Windows:
  Meta (WhatsApp), Ngrok (para piloto), Gemini y Groq.

---

## 📑 Índice

1. [Preparar el servidor](#paso-1--preparar-el-servidor)
2. [Instalar Python, PostgreSQL y utilidades](#paso-2--instalar-python-postgresql-y-utilidades)
3. [Configurar el usuario de PostgreSQL](#paso-3--configurar-el-usuario-de-postgresql)
4. [Copiar el proyecto al servidor](#paso-4--copiar-el-proyecto-al-servidor)
5. [Ejecutar el script de instalación (`chatbot.sh`)](#paso-5--ejecutar-el-script-de-instalación)
6. [Configurar el `.env`](#paso-6--configurar-el-env)
7. [Arrancar el chatbot en modo piloto](#paso-7--arrancar-el-chatbot-en-modo-piloto)
8. [Configurar el webhook en Meta](#paso-8--configurar-el-webhook-en-meta)
9. [Verificación final](#paso-9--verificación-final)
10. [Modo producción — arranque automático con systemd](#paso-10--modo-producción--arranque-automático-con-systemd)
11. [Operación diaria](#operación-diaria)
12. [Solución de problemas](#solución-de-problemas)

---

## PASO 1 · Preparar el servidor

### 1.1 Conectarse por SSH

Desde tu PC, abre una terminal y conéctate al servidor:

```bash
ssh usuario@IP-DEL-SERVIDOR
```

**Anota en tu cuaderno:**
- Nombre de usuario en el servidor: _____________
- Dirección IP del servidor: _____________

### 1.2 Actualizar el sistema

Buena práctica antes de instalar nada nuevo:

```bash
sudo apt update && sudo apt upgrade -y
```

### 1.3 Ajustar la zona horaria

El bot registra fechas y horas con la hora local del servidor. **Es
imprescindible que la zona horaria sea Colombia:**

```bash
sudo timedatectl set-timezone America/Bogota
timedatectl                 # verifica que diga "Time zone: America/Bogota"
```

---

## PASO 2 · Instalar Python, PostgreSQL y utilidades

Un solo comando instala todo lo necesario:

```bash
sudo apt install -y \
    python3 python3-venv python3-pip \
    postgresql postgresql-contrib \
    ufw \
    nano git curl
```

**Verifica:**

```bash
python3 --version           # debe ser 3.10 o superior
psql --version              # debe mostrar PostgreSQL 14+
```

Si Ubuntu instaló una versión de Python menor a 3.10, instala una más nueva:

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
```

Y usa `python3.12` en lugar de `python3` en los siguientes pasos.

---

## PASO 3 · Configurar el usuario de PostgreSQL

Ubuntu instala PostgreSQL con un usuario `postgres` que **no tiene
contraseña** por defecto (solo se accede desde el propio usuario del
sistema). Vamos a fijarle una contraseña para que el chatbot pueda
conectarse.

### 3.1 Ponerle contraseña al usuario `postgres`

```bash
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'CAMBIA_ESTA_CLAVE';"
```

⚠️ **CAMBIA `CAMBIA_ESTA_CLAVE`** por una contraseña fuerte (letras,
números, símbolos). **Anótala en tu cuaderno** — la vas a poner en el
`.env` más adelante.

### 3.2 Verificar que puedes conectarte con esa contraseña

```bash
PGPASSWORD='TU_CLAVE' psql -h localhost -U postgres -c "SELECT version();"
```

Debe mostrar la versión de PostgreSQL. Si dice "authentication failed",
la contraseña está mal escrita.

> **Nota sobre `pg_hba.conf`:** en Ubuntu la autenticación por defecto es
> `peer` para conexiones locales del usuario `postgres` y `md5` para
> conexiones TCP. Como el chatbot se conecta a `localhost:5432` (TCP), el
> `md5` con contraseña funciona sin más cambios.

---

## PASO 4 · Copiar el proyecto al servidor

Tienes 3 opciones. Elige la que te resulte más cómoda:

### Opción A · Clonar desde Git (si el proyecto está en un repositorio)

```bash
cd ~
git clone <URL_DEL_REPOSITORIO> chatbot-hospital
cd chatbot-hospital
```

### Opción B · Copiar con `scp` desde tu PC

Desde tu PC (Windows/Mac/Linux):

```bash
scp -r ruta/local/chatbot-whatsapp-hospital usuario@IP-SERVIDOR:~/chatbot-hospital
```

Luego en el servidor:

```bash
cd ~/chatbot-hospital
```

### Opción C · Copiar con `rsync` (más rápido si vas a repetir)

```bash
rsync -avz --exclude venv --exclude __pycache__ \
      ./chatbot-whatsapp-hospital/  usuario@IP-SERVIDOR:~/chatbot-hospital/
```

**En cualquier caso, verifica:**

```bash
ls -la ~/chatbot-hospital
```

Debes ver `bot_main.py`, `sql_db.sql`, `chatbot.sh`, `bot_.env.example`,
y las demás.

---

## PASO 5 · Ejecutar el script de instalación

El proyecto trae **`chatbot.sh`** que automatiza todo. Solo lo ejecutas:

```bash
cd ~/chatbot-hospital
chmod +x chatbot.sh          # solo la primera vez
./chatbot.sh --solo-instalar
```

**El script hará automáticamente:**

1. ✅ Verifica que Python, PostgreSQL y todos los archivos estén en su
   sitio.
2. ✅ Crea el entorno virtual `venv/` con Python.
3. ✅ Instala todas las dependencias (~50 paquetes, tarda 3-5 min la
   primera vez).
4. ✅ Copia `bot_.env.example` a `.env` y **abre el editor `nano`**
   para que lo configures.
5. ✅ Verifica que las claves críticas del `.env` estén rellenas.
6. ✅ Crea la base de datos `hospital_chatbot` en PostgreSQL.

Cuando el script abra `nano` con el `.env`, sigue al **PASO 6** antes de
guardar.

---

## PASO 6 · Configurar el `.env`

Estás editando `~/chatbot-hospital/.env` en nano. Rellena estos valores
(los tokens los obtienes igual que en la guía de Windows —
[IMPLEMENTACION_HOSPITAL.md](IMPLEMENTACION_HOSPITAL.md) pasos 7-10):

```env
# Base de datos (usa la contraseña del PASO 3)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=hospital_chatbot
DB_USER=postgres
DB_PASSWORD=CAMBIA_ESTA_CLAVE

# WhatsApp Business API (Meta for Developers)
WHATSAPP_TOKEN=EAA...
WHATSAPP_PHONE_NUMBER_ID=1234567890
VERIFY_TOKEN=HospitalIpiales2026

# Ngrok (para el piloto)
NGROK_AUTH_TOKEN=xxx
NGROK_ENABLED=true

# Servidor — HOST se cambia automáticamente al arrancar
HOST=0.0.0.0
PORT=8000

# Panel administrativo
ADMIN_USER=admin
ADMIN_PASSWORD=una-contraseña-larga-para-el-panel
SECRET_KEY=  # ← generalo abajo
COOKIE_SECURE=false

# OCR (Gemini) e IA (Groq)
GEMINI_AUTH_TOKEN=xxx
GEMINI_MODEL=gemini-flash-lite-latest
OCR_PROVIDER=gemini
GROQ_AUTH_TOKEN=xxx
AI_PROVIDER=groq

# Hospital
HOSPITAL_NOMBRE=Hospital Civil de Ipiales
HOSPITAL_TELEFONO=6027374008 o 6027332149
```

### Generar la `SECRET_KEY`

En **otra terminal** conectada al servidor, ejecuta:

```bash
cd ~/chatbot-hospital
./venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
```

Copia la cadena hexadecimal larga y pégala en `SECRET_KEY=` en el `.env`.

### Guardar y salir de nano

- Presiona `Ctrl + O` (letra O, no cero) → confirma con `Enter`.
- Presiona `Ctrl + X` para salir.

El script continuará su ejecución y terminará mostrando:

```
-- Instalacion completa ---------------------------------------------
  [OK]   El sistema esta listo para arrancar.
```

---

## PASO 7 · Arrancar el chatbot en modo piloto

Ahora arrancamos por primera vez. Este comando hace TODO en uno
(instalación + firewall + arranque):

```bash
./chatbot.sh
```

**El script:**

1. ✅ Verifica que todo esté OK (rápido, salta lo ya hecho).
2. ✅ Cambia `HOST=127.0.0.1` a `HOST=0.0.0.0` en `.env` para que el
   panel sea visible desde la LAN.
3. ✅ Detecta la IP LAN del servidor.
4. ✅ Configura el firewall `ufw` para permitir el puerto 8000
   **SOLO desde la LAN del hospital** (regla restrictiva, no expone a
   Internet).
5. ✅ Arranca el bot con `python bot_main.py`.

**Verás en pantalla:**

```
Panel administrativo (solo desde la LAN del hospital):
   http://172.16.28.50:8000/admin

Webhook de WhatsApp:
   La URL de ngrok se mostrara abajo cuando arranque.

...

✅ Tablas verificadas
✅ Esquema y datos base sincronizados (sql_db.sql)
🌐 Ngrok activo: https://xxxx-yy.ngrok-free.app
🚀 Servidor listo
```

**⚠️ COPIA la URL de Ngrok.** La necesitas en el siguiente paso.

Deja esta terminal abierta. Si la cierras, el bot se detiene.

> **Consejo:** para no depender de la sesión SSH, usa **`tmux`** o
> **`screen`**:
>
> ```bash
> sudo apt install -y tmux
> tmux new -s chatbot           # crea una sesión
> cd ~/chatbot-hospital
> ./chatbot.sh                  # arranca dentro de tmux
> # Ctrl+B, luego D              → salir sin detener el bot
> tmux attach -t chatbot        # volver a la sesión más tarde
> ```
>
> Para producción real, usa `systemd` (PASO 10).

---

## PASO 8 · Configurar el webhook en Meta

Idéntico al PASO 13 de la guía Windows (
[IMPLEMENTACION_HOSPITAL.md](IMPLEMENTACION_HOSPITAL.md)):

1. Ve a **https://developers.facebook.com/** → tu app.
2. **WhatsApp → Configuration → Webhook → Edit**.
3. **Callback URL:** `https://xxxx-yy.ngrok-free.app/webhook`
   (la URL de Ngrok + `/webhook`).
4. **Verify Token:** el mismo `VERIFY_TOKEN` de tu `.env`.
5. **Verify and Save** → debe aparecer ✅ verde.
6. En **Webhook fields**, suscríbete a `messages`.
7. **API Setup → To:** agrega tu número personal de pruebas.
8. Desde tu WhatsApp envía `Hola`. El bot debe responder.

---

## PASO 9 · Verificación final

Prueba end-to-end. Desde otra PC de la LAN del hospital:

1. Abre el navegador y ve a `http://IP-DEL-SERVIDOR:8000/admin`.
2. Debe aparecer el login. Entra con `admin` y la contraseña que pusiste.
3. Deberías ver el dashboard.
4. Desde tu WhatsApp, intenta agendar una cita completa.
5. Vuelve al panel → sección Citas → verás la nueva solicitud en estado
   "Pendiente".
6. Presiona **✅ Confirmar** → el paciente recibe el mensaje de cita
   agendada por WhatsApp.

Si los 6 pasos funcionaron, **el piloto está listo**. 🎉

---

## PASO 10 · Modo producción — arranque automático con systemd

Para que el bot **arranque solo al reiniciar el servidor** y se
reinicie si crashea, configúralo como servicio de systemd.

### 10.1 Crear el archivo del servicio

```bash
sudo nano /etc/systemd/system/chatbot-hospital.service
```

Copia y pega esto (ajusta las 3 rutas marcadas con `# CAMBIA`):

```ini
[Unit]
Description=ChatBot WhatsApp - Hospital Civil de Ipiales
After=network-online.target postgresql.service
Wants=network-online.target postgresql.service

[Service]
Type=simple
User=USUARIO_LINUX                    # CAMBIA: tu usuario del servidor
WorkingDirectory=/home/USUARIO_LINUX/chatbot-hospital   # CAMBIA
ExecStart=/home/USUARIO_LINUX/chatbot-hospital/venv/bin/python bot_main.py  # CAMBIA
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

# Cierre limpio: 30 s para procesar mensajes en curso antes de matar.
KillMode=mixed
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

Guarda con `Ctrl+O`, `Enter`, `Ctrl+X`.

### 10.2 Activar y arrancar el servicio

```bash
sudo systemctl daemon-reload
sudo systemctl enable chatbot-hospital       # arranque automático al reiniciar
sudo systemctl start chatbot-hospital        # arranca ahora
sudo systemctl status chatbot-hospital       # verifica que dice "active (running)"
```

### 10.3 Ver los logs

```bash
sudo journalctl -u chatbot-hospital -f       # logs en tiempo real
sudo journalctl -u chatbot-hospital --since "10 min ago"
```

### 10.4 Detener / reiniciar

```bash
sudo systemctl stop chatbot-hospital         # detener
sudo systemctl restart chatbot-hospital      # reiniciar
sudo systemctl disable chatbot-hospital      # desactivar arranque automático
```

⚠️ **Cuando uses systemd**, ya no ejecutes `./chatbot.sh` en la terminal
— habría dos instancias del bot corriendo. Usa `systemctl` para todo.

---

## Operación diaria

### Todos los días al abrir el hospital

- Verifica que el bot esté corriendo:
  ```bash
  sudo systemctl status chatbot-hospital
  ```
  o (sin systemd):
  ```bash
  ps aux | grep bot_main.py
  ```
- Si el token de WhatsApp caducó (versión temporal de 24 h), regenera en
  Meta, edita el `.env` y reinicia:
  ```bash
  nano ~/chatbot-hospital/.env      # actualizar WHATSAPP_TOKEN
  sudo systemctl restart chatbot-hospital
  ```

### Cada semana

Cargar los horarios de la próxima semana:
1. Panel → Fechas → **📤 Cargar horarios**.
2. Elige el lunes de la próxima semana.
3. Sube el Excel del hospital con columnas Lunes/Martes/…
4. Revisa el preview y guarda.

### Cada mes

Revisa las métricas del panel para ver:
- Tiempos de agendamiento y de confirmación.
- Satisfacción de los pacientes.
- Volumen semanal.

### Respaldo de la base de datos (recomendado)

Configura un backup diario automático:

```bash
sudo crontab -e
# Añade esta línea (respaldo diario 2 a.m., conserva 14 días):
0 2 * * * PGPASSWORD='TU_CLAVE' pg_dump -U postgres -h localhost hospital_chatbot | gzip > /var/backups/hospital_$(date +\%F).sql.gz
0 3 * * * find /var/backups -name 'hospital_*.sql.gz' -mtime +14 -delete
```

Asegúrate de que `/var/backups` exista y tenga permisos:

```bash
sudo mkdir -p /var/backups
sudo chown $USER: /var/backups
```

---

## Solución de problemas

### El bot no arranca — error de conexión a PostgreSQL

```bash
sudo systemctl status postgresql              # ¿está corriendo?
sudo systemctl start postgresql               # arrancarlo
sudo -u postgres psql -c "\l"                 # ¿existe hospital_chatbot?
```

Si el error es `authentication failed`, la contraseña del `.env` no
coincide con la del usuario `postgres`:

```bash
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'nueva_clave';"
nano ~/chatbot-hospital/.env                  # actualizar DB_PASSWORD
sudo systemctl restart chatbot-hospital
```

### El panel no es accesible desde otras PC de la LAN

1. Verifica que `HOST=0.0.0.0` en el `.env` (no `127.0.0.1`).
2. Verifica el firewall:
   ```bash
   sudo ufw status verbose
   ```
   Debe mostrar una regla de tipo `ALLOW  <PORT>/tcp  FROM  <TU_LAN>/24`.
3. Si `ufw` está inactivo (`Status: inactive`), activalo:
   ```bash
   sudo ufw allow ssh                         # ⚠️ IMPRESCINDIBLE antes de enable
   sudo ufw enable
   ```

### Ngrok da un error `ERR_NGROK_...`

- **`ERR_NGROK_108`**: el token de Ngrok es inválido. Regenera en
  dashboard.ngrok.com y actualiza `NGROK_AUTH_TOKEN` en el `.env`.
- **`ERR_NGROK_334`**: dominio ocupado. Reinicia el servicio:
  ```bash
  sudo systemctl restart chatbot-hospital
  ```
- **La URL de Ngrok cambia en cada reinicio** (con plan gratuito). Cada
  vez que reinicies, actualiza la Callback URL en Meta.

### Ver qué versiones de Python están disponibles

```bash
ls /usr/bin/python*
apt list --installed 2>/dev/null | grep python3
```

### El bot está lento o consume mucha RAM

```bash
top -p $(pgrep -d, -f bot_main.py)          # ver CPU/RAM del bot
sudo journalctl -u chatbot-hospital --since "1 hour ago" | tail -50
```

### Volver a instalar todo desde cero

```bash
sudo systemctl stop chatbot-hospital 2>/dev/null || true
cd ~/chatbot-hospital
rm -rf venv/                                # elimina el entorno virtual
rm -f venv/.install_ok                      # (por si acaso)
./chatbot.sh --solo-instalar                # reinstala
```

**No borra el `.env`** ni la base de datos. Si quieres eliminar la BD
también:

```bash
sudo -u postgres psql -c "DROP DATABASE hospital_chatbot;"
```

Luego `chatbot.sh --solo-instalar` la volverá a crear vacía.

---

## Siguientes pasos (opcional, para producción real)

Cuando quieras dejar Ngrok atrás y operar con dominio propio:

1. **Comprar un dominio** para el hospital (~$10 USD/año).
2. **Instalar Nginx** como reverse proxy:
   ```bash
   sudo apt install -y nginx certbot python3-certbot-nginx
   ```
3. **Configurar Nginx** para exponer `/webhook` públicamente y `/admin`
   solo a la LAN. Ejemplo mínimo en `/etc/nginx/sites-available/chatbot`:
   ```nginx
   server {
       listen 80;
       server_name chatbot.tudominio.co;

       location /webhook {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
       location / {
           allow 172.16.28.0/24;   # ← ajusta a tu LAN
           deny  all;
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
       }
   }
   ```
4. **Certificado SSL** gratis con Let's Encrypt:
   ```bash
   sudo certbot --nginx -d chatbot.tudominio.co
   ```
5. **Poner `NGROK_ENABLED=false`** en el `.env` (ya no lo necesitas).
6. **Rotar todas las credenciales** del `.env` (el que se usó para
   piloto queda comprometido).
7. **Generar un token permanente** de WhatsApp Business (System User) en
   `business.facebook.com` para que no caduque cada 24 horas.

---

**Autor:** Ing. Javier Santiago Burbano
**Última actualización:** 21 de agosto de 2026

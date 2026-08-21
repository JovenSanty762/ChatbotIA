# Guía de implementación del ChatBot en la red del hospital

**Esta guía está escrita para alguien que nunca ha instalado un sistema
como este.** Si sigues los pasos en orden y con cuidado, al final del
día tendrás el chatbot funcionando en la red interna del hospital.

**Tiempo estimado:** entre 3 y 5 horas la primera vez.

**Prerrequisito:** ser el administrador del PC donde se va a instalar
(necesitas hacer clic derecho → *Ejecutar como administrador*).

---

## 📑 Antes de empezar — Chequeo de requisitos

Vas a necesitar:

- ✅ Un **PC con Windows 10 u 11** que esté encendido durante horario
  de atención del hospital, con conexión a la red interna del hospital y
  conexión a Internet.
- ✅ Una **cuenta de Meta for Developers** con acceso a la API de WhatsApp
  Business del hospital.
- ✅ Una **cuenta de Ngrok** gratuita.
- ✅ El **teléfono del personal de IT** del hospital (por si necesitas
  ayuda con la red).
- ✅ Un **cuaderno o archivo de notas** — a lo largo del proceso vas a
  copiar y pegar contraseñas y tokens que no debes olvidar.

Si algo de esto no lo tienes, resuélvelo primero. No sigas hasta tener
los 5 puntos.

---

## 📑 Índice

1. [Instalar Python](#paso-1-instalar-python)
2. [Instalar PostgreSQL](#paso-2-instalar-postgresql)
3. [Copiar el proyecto al PC](#paso-3-copiar-el-proyecto-al-pc)
4. [Crear la base de datos](#paso-4-crear-la-base-de-datos)
5. [Preparar el entorno Python](#paso-5-preparar-el-entorno-python-venv)
6. [Configurar el archivo .env](#paso-6-configurar-el-archivo-env)
7. [Obtener el token de Ngrok](#paso-7-obtener-el-token-de-ngrok)
8. [Obtener credenciales de WhatsApp](#paso-8-obtener-credenciales-de-whatsapp-business)
9. [Obtener token de Gemini (OCR)](#paso-9-obtener-el-token-de-gemini-ocr)
10. [Obtener token de Groq (IA de texto)](#paso-10-obtener-el-token-de-groq)
11. [Averiguar la IP del PC en la LAN del hospital](#paso-11-averiguar-la-ip-del-pc-en-la-lan-del-hospital)
12. [Arrancar el chatbot](#paso-12-arrancar-el-chatbot)
13. [Configurar el webhook en Meta](#paso-13-configurar-el-webhook-en-meta)
14. [Compartir el panel con el personal](#paso-14-compartir-el-panel-administrativo-con-el-personal)
15. [Verificar que todo funciona](#paso-15-verificación-final)
16. [Operación diaria](#operación-diaria)
17. [Solución de problemas](#solución-de-problemas-comunes)

---

## PASO 1 · Instalar Python

Python es el lenguaje en el que está escrito el chatbot.

1. Abre tu navegador web.
2. Ve a: **https://www.python.org/downloads/**
3. Haz clic en el botón amarillo grande que dice **"Download Python 3.11.x"**
   (o superior, siempre que sea 3.11).
4. Cuando termine la descarga, haz **doble clic** en el archivo
   descargado (algo como `python-3.11.7-amd64.exe`).
5. **⚠️ MUY IMPORTANTE:** en la primera ventana que aparece, antes de
   hacer clic en "Install", **marca la casilla que dice
   `Add Python 3.11 to PATH`** (está en la parte de abajo). Si no la
   marcas, los pasos siguientes no van a funcionar.
6. Haz clic en **"Install Now"** y espera a que termine (2-3 minutos).
7. Cuando termine, cierra el instalador.

**Verificación:**

- Presiona la tecla **Windows** + escribe `cmd`, y abre la aplicación
  "Símbolo del sistema".
- Escribe: `python --version` y presiona Enter.
- Debe aparecer algo como: `Python 3.11.7`.
- Si aparece un error, vuelve al paso 5 (probablemente no marcaste la
  casilla del PATH — reinstala).

---

## PASO 2 · Instalar PostgreSQL

PostgreSQL es la base de datos donde se guardan los pacientes, citas, etc.

1. Ve a: **https://www.postgresql.org/download/windows/**
2. Haz clic en **"Download the installer"** (te lleva a EDB).
3. Descarga la versión **17 o 18** (la más reciente disponible), 64-bit.
4. Haz doble clic en el archivo descargado.
5. Sigue el asistente:
   - Directorio de instalación: deja el que sugiere (por defecto).
   - Componentes: deja todos marcados (PostgreSQL Server, pgAdmin,
     Stack Builder, Command Line Tools).
   - Directorio de datos: deja el que sugiere.
   - **Contraseña del superusuario "postgres":** aquí debes escribir una
     contraseña. **⚠️ ANÓTALA EN TU CUADERNO** — la vas a necesitar
     varias veces. Por ejemplo: `Hospital2026#`.
   - Puerto: deja `5432`.
   - Locale: deja "Default locale".
6. Haz clic en **"Next"** hasta que empiece la instalación (5-10 minutos).
7. Al terminar, **DESMARCA** "Launch Stack Builder at exit" y clic en
   "Finish".

**Verificación:**

- Presiona **Windows** + escribe "SQL Shell" → abre "SQL Shell (psql)".
- Presiona Enter 4 veces (para aceptar los valores por defecto de
  Server, Database, Port, Username).
- Cuando te pida "Password for user postgres:", escribe la contraseña
  que anotaste. **⚠️ Al escribir la contraseña no verás nada — es
  normal, así funciona.** Presiona Enter.
- Si ves un prompt como `postgres=#`, ¡PostgreSQL está funcionando!
- Escribe `\q` y Enter para salir.

---

## PASO 3 · Copiar el proyecto al PC

Copia toda la carpeta del proyecto (`chatbot-whatsapp-hospital`) al PC
donde vas a hacer la instalación. Puedes usar:

- Una **memoria USB**
- Un **disco duro externo**
- **Google Drive / OneDrive**
- **Git** (si tienes acceso al repositorio)

Guarda la carpeta en un lugar fácil de encontrar, por ejemplo:

```
C:\HospitalChatBot\chatbot-whatsapp-hospital
```

**⚠️ NO GUARDES LA CARPETA DENTRO DE:**
- El Escritorio (a veces genera problemas de permisos)
- La carpeta "Descargas"
- OneDrive sincronizado (puede intentar subir archivos temporales grandes)

---

## PASO 4 · Crear la base de datos y preparar el entorno

> **💡 Buenas noticias:** los pasos 4 y 5 se automatizan con el script
> `chatbot.ps1` (paso 12). Puedes saltar directamente al paso 6 si prefieres
> que el script haga todo por ti. Este paso 4 y 5 quedan como referencia
> manual por si prefieres hacerlo tú mismo o si algo falla en el script.

Si prefieres hacerlo manualmente:

1. Presiona **Windows** + escribe "SQL Shell" → abre "SQL Shell (psql)".
2. Presiona Enter 4 veces y escribe tu contraseña de postgres.
3. Copia y pega este comando exactamente y presiona Enter:

```sql
CREATE DATABASE hospital_chatbot;
```

4. Debe aparecer: `CREATE DATABASE`.
5. Escribe `\q` y Enter para salir.

---

## PASO 5 · Preparar el entorno Python (venv) — opcional

Si prefieres hacerlo manualmente (el script del paso 12 lo hace solo):

1. Presiona **Windows** + escribe "cmd" → clic derecho en "Símbolo del
   sistema" → **"Ejecutar como administrador"**.
2. Navega hasta la carpeta del proyecto:

```bash
cd C:\HospitalChatBot\chatbot-whatsapp-hospital
```

(Ajusta la ruta si la copiaste en otro lugar.)

3. Crea el entorno virtual:

```bash
python -m venv venv
```

Espera 30 segundos. Se creará una carpeta llamada `venv`.

4. Activa el entorno:

```bash
venv\Scripts\activate
```

Notarás que ahora la línea de comandos empieza con `(venv)`.

5. Instala las librerías (esto tarda 3-5 minutos, verás mucho texto en
   pantalla):

```bash
pip install -r bot_requirements.txt
```

6. Cuando termine, deja esa ventana de `cmd` abierta — la vas a
   necesitar más adelante.

---

## PASO 6 · Configurar el archivo `.env`

El archivo `.env` es donde el chatbot lee todas sus contraseñas y
tokens. **Es el archivo más importante de configurar bien.**

1. Abre el **Explorador de archivos** y ve a la carpeta del proyecto.
2. Vas a ver un archivo llamado `bot_.env.example`.
3. Haz clic derecho → **Copiar**. Luego pegar en la misma carpeta.
4. Renombra la copia a exactamente `.env` (con el punto al principio,
   sin nada más).
   - Si Windows no te deja poner un archivo que empieza con punto,
     abre el Bloc de Notas → Archivo → Guardar como → escribe
     `".env"` (con las comillas) en la carpeta del proyecto.
5. Haz doble clic en `.env` para abrirlo con el Bloc de Notas.

Vas a ver muchas variables. Los siguientes valores tienes que cambiar
por los reales:

```env
DB_PASSWORD=aquí_va_la_contraseña_de_postgres_del_paso_2
WHATSAPP_TOKEN=              (lo obtendrás en el paso 8)
WHATSAPP_PHONE_NUMBER_ID=    (lo obtendrás en el paso 8)
VERIFY_TOKEN=elige_una_palabra_secreta_como_HospitalIpiales2026
NGROK_AUTH_TOKEN=            (lo obtendrás en el paso 7)
ADMIN_USER=admin
ADMIN_PASSWORD=elige_una_contraseña_larga_para_el_panel
SECRET_KEY=                  (más abajo te enseño a generarla)
GEMINI_AUTH_TOKEN=           (lo obtendrás en el paso 9)
GROQ_AUTH_TOKEN=             (lo obtendrás en el paso 10)
HOSPITAL_NOMBRE=Hospital Civil de Ipiales
HOSPITAL_TELEFONO=6027374008 o 6027332149
```

**Cómo generar la SECRET_KEY:**

En la ventana `cmd` con `(venv)` que dejaste abierta, escribe:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Copia el texto largo que aparece (algo como
`a3b2c1d4e5f6...`) y pégalo en `SECRET_KEY=` en el archivo `.env`.

Guarda el `.env` (Archivo → Guardar) y ciérralo.

---

## PASO 7 · Obtener el token de Ngrok

Ngrok es lo que permite que Meta (WhatsApp) pueda enviarle mensajes al
chatbot que está corriendo en tu PC del hospital.

1. Ve a: **https://dashboard.ngrok.com/signup**
2. Crea una cuenta con tu correo (es gratis).
3. Cuando entres, en el menú de la izquierda haz clic en
   **"Your Authtoken"**.
4. Vas a ver un token largo. Haz clic en el ícono de copiar.
5. Abre el archivo `.env` de nuevo y pega ese token en:

```env
NGROK_AUTH_TOKEN=aquí_pegas_el_token_de_ngrok
```

6. Guarda y cierra.

---

## PASO 8 · Obtener credenciales de WhatsApp Business

1. Ve a: **https://developers.facebook.com/**
2. Inicia sesión con tu cuenta de Facebook (o crea una).
3. En la esquina superior derecha, clic en **"My Apps"** → **"Create App"**.
4. Elige **"Business"** → clic en "Next".
5. Nombre de la app: `Hospital Civil Ipiales ChatBot` (o similar).
6. Correo: el tuyo.
7. Cuenta de negocio: usa la del hospital si ya existe, o crea una nueva.
8. Clic en **"Create App"**.
9. Ya dentro de la app, busca en la lista de productos "**WhatsApp**" y
   clic en **"Set up"**.
10. Ve a la sección **"API Setup"** (menú izquierdo).

Ahí vas a ver dos cosas importantes:

**Phone number ID:**
- Aparece como un número largo debajo de "From".
- Cópialo y pégalo en el `.env`:
  ```env
  WHATSAPP_PHONE_NUMBER_ID=aquí_va_el_phone_number_id
  ```

**Access Token (temporal):**
- Es un token largo que empieza por "EAA...".
- Cópialo y pégalo en el `.env`:
  ```env
  WHATSAPP_TOKEN=aquí_va_el_token
  ```
- **⚠️ Este token caduca a las 24 horas.** Sirve para hacer pruebas.
  Para dejar el bot funcionando en producción de forma permanente,
  necesitas generar un **token permanente** de "System User" — pero
  eso puede esperar al despliegue definitivo. Para el piloto, con
  este token es suficiente y lo renuevas cada día.

Guarda y cierra el `.env`.

---

## PASO 9 · Obtener el token de Gemini (OCR)

Gemini es el motor de inteligencia artificial que "lee" las fotos de la
orden médica y la autorización.

1. Ve a: **https://aistudio.google.com/app/apikey**
2. Inicia sesión con una cuenta de Google.
3. Clic en **"Create API key"**.
4. Elige el proyecto (o crea uno nuevo).
5. Copia el token que aparece.
6. Pégalo en el `.env`:

```env
GEMINI_AUTH_TOKEN=aquí_pegas_la_clave
```

El tier gratuito de Gemini alcanza para varios cientos de documentos
por día — suficiente para el piloto.

---

## PASO 10 · Obtener token de Groq

Groq entiende cuando el paciente escribe algo como "quiero una cita con
cardiología para el viernes en la tarde".

1. Ve a: **https://console.groq.com/keys**
2. Inicia sesión con Google o correo.
3. Clic en **"Create API Key"**.
4. Dale un nombre: `ChatBot Hospital`.
5. Copia el token que aparece.
6. Pégalo en el `.env`:

```env
GROQ_AUTH_TOKEN=aquí_pegas_la_clave
```

Guarda y cierra el `.env`.

**En este punto, todos los tokens y contraseñas del `.env` deben estar
llenos.**

---

## PASO 11 · Averiguar la IP del PC en la LAN del hospital

Necesitamos saber la dirección IP que este PC tiene en la red interna
del hospital, para que el personal pueda acceder al panel desde otras
computadoras.

1. Abre `cmd` (Windows + escribir `cmd`).
2. Escribe: `ipconfig` y presiona Enter.
3. Busca la sección **"Adaptador de Ethernet"** (o "Adaptador WiFi" si
   estás conectado por WiFi).
4. Dentro de esa sección, busca la línea **"Dirección IPv4"**.
5. Anota esa dirección. Se ve algo como: `172.16.28.50` o
   `192.168.1.100`.

**⚠️ Anótala en el cuaderno.** Es la que el personal usará para
acceder al panel.

**Recomendación importante:** pide al personal de IT del hospital que
te asigne esa IP de forma **fija** (reservada por DHCP). Si mañana la
IP cambia, el personal no podrá acceder al panel.

---

## PASO 12 · Arrancar el chatbot

Ya tienes todo configurado. Ahora arrancamos por primera vez.

1. Abre `cmd` **como administrador** (clic derecho → "Ejecutar como
   administrador").
2. Navega a la carpeta:

```bash
cd C:\HospitalChatBot\chatbot-whatsapp-hospital
```

3. Ejecuta el script definitivo (instala lo que falte y arranca):

```bash
powershell.exe -ExecutionPolicy Bypass -File .\chatbot.ps1
```

**El script hace todo esto automáticamente:**

- ✅ Verifica Python 3.10+ y PostgreSQL
- ✅ Crea el entorno virtual `venv` si no existe
- ✅ Instala todas las dependencias Python
- ✅ Crea el `.env` desde la plantilla si no existe y abre el editor
- ✅ Verifica que las claves críticas del `.env` estén configuradas
- ✅ Crea la base de datos `hospital_chatbot` si no existe
- ✅ Cambia `HOST=127.0.0.1` a `HOST=0.0.0.0` para que el panel sea
  visible en la LAN
- ✅ Detecta la IP LAN del PC
- ✅ Abre el puerto 8000 en el firewall **SOLO** para la LAN del hospital
- ✅ Arranca el chatbot

Espera a que aparezca en la consola:

```
✅ Tablas verificadas
✅ Esquema y datos base sincronizados (sql_db.sql)
🌐 Ngrok activo: https://xxxx-yy-zz.ngrok-free.app
🚀 Servidor listo
```

**⚠️ COPIA LA URL DE NGROK.** La necesitas para el siguiente paso.
Se ve algo como: `https://a1b2-c3d4.ngrok-free.app`.

**No cierres esta ventana.** Si la cierras, el chatbot se detiene.

---

## PASO 13 · Configurar el webhook en Meta

Vamos a decirle a Meta (WhatsApp) dónde enviar los mensajes que reciba.

1. Ve a **https://developers.facebook.com/** → tu app.
2. En el menú izquierdo: **WhatsApp → Configuration**.
3. En la sección **"Webhook"**, clic en **"Edit"**.
4. Rellena:
   - **Callback URL:** la URL de Ngrok que copiaste + `/webhook`.
     Ejemplo completo: `https://a1b2-c3d4.ngrok-free.app/webhook`
   - **Verify Token:** exactamente el mismo texto que pusiste en el
     `.env` en `VERIFY_TOKEN=`. Ejemplo: `HospitalIpiales2026`.
5. Clic en **"Verify and Save"**.

Si aparece ✅ verde, ¡funcionó!

Si aparece ❌ rojo:
- Verifica que la URL termine exactamente en `/webhook`.
- Verifica que el Verify Token sea idéntico al del `.env` (sin espacios).
- Verifica que el bot esté corriendo en el PC (la ventana de `cmd`).

6. Después, en la misma pantalla, más abajo en **"Webhook fields"**,
   busca **`messages`** y clic en **"Subscribe"**.

7. Ahora ve a **WhatsApp → API Setup**.
8. En la sección **"To"**, agrega tu número personal para pruebas.
9. Envía al bot un mensaje de prueba desde tu WhatsApp:
   - Escribe: `Hola`
   - Debe responder saludándote y pidiéndote tu cédula.

**Si respondió, ¡el bot está funcionando!** 🎉

---

## PASO 14 · Compartir el panel administrativo con el personal

Ahora el personal del hospital puede empezar a usar el panel.

**Redacta un mensaje para enviar por correo/Teams al personal:**

```
Buenos días,

Ya está disponible el nuevo Panel del ChatBot de citas médicas.

  🔗 Dirección:  http://[IP-QUE-ANOTASTE]:8000/admin
                (ejemplo: http://172.16.28.50:8000/admin)

  👤 Usuario:    admin
  🔑 Contraseña: [la contraseña que pusiste en ADMIN_PASSWORD]

Notas:
  • Solo funciona desde una PC dentro de la red del hospital.
  • Si estás en casa o con datos móviles, NO podrás acceder.
  • Cuando entres, verás las citas pendientes de confirmar en la
    parte superior del dashboard.
  • Para confirmar una cita, revisa la orden y la autorización con
    el botón "🔎 Datos", y luego "✅ Confirmar cita".

Cualquier problema me avisan.
```

---

## PASO 15 · Verificación final

Para confirmar que TODO funciona, haz esta prueba completa:

### Desde tu WhatsApp personal:

1. Envía `Hola` al número de prueba.
2. Sigue el flujo hasta agendar una cita (usa tu cédula real o inventa
   una).
3. Sube fotos de una orden médica y autorización (puedes usar imágenes
   de prueba que tengas guardadas).
4. Al final, deberías recibir un mensaje que dice: *"📨 SOLICITUD DE
   CITA RECIBIDA · Esperando confirmación del hospital..."*.

### Desde otra PC de la LAN del hospital:

1. Abre un navegador web.
2. Ve a `http://[IP-DEL-PC]:8000/admin`.
3. Debe aparecer el login. Entra con `admin` y tu contraseña.
4. En el dashboard verás la cita que acabas de crear con badge de
   "Pendiente".
5. Clic en el botón "🔎 Datos" → revisa que los datos de OCR sean
   coherentes con la foto.
6. Clic en "✅ Confirmar cita".
7. **De vuelta en tu WhatsApp**, debes recibir el mensaje: *"✅ ¡CITA
   CONFIRMADA!"*.

Si los 7 pasos funcionaron, **estás listo para el piloto**. 🎉

---

## Operación diaria

### Todos los días al abrir el hospital

- Verifica que el PC del chatbot esté encendido.
- Verifica que la ventana de `cmd` con el bot esté abierta y sin errores.
- Si el "Access Token" de WhatsApp caducó (24 horas), regenéralo en Meta
  y actualiza el `.env` + reinicia el bot.

### Todos los días al cerrar

- **No apagues el PC** si el bot debe seguir recibiendo mensajes en la
  noche/madrugada. Si quieres detenerlo intencionalmente, presiona
  `Ctrl+C` en la ventana del bot.

### Cada semana

- Actualiza el archivo `esp_horarios.xlsx` con los slots nuevos y
  reinicia el bot para que se recarguen.

### Cada mes

- Revisa el panel → sección **Métricas** para ver:
  - Cuántas citas se están confirmando.
  - Cuánto tarda el personal en confirmar en promedio.
  - Cuál es la satisfacción de los pacientes.

---

## Solución de problemas comunes

### El bot no responde a mensajes

1. Mira la ventana `cmd` — ¿hay mensajes de error rojos?
2. Revisa que la URL de Ngrok siga siendo la misma que configuraste en
   Meta. **La URL de Ngrok gratuito CAMBIA cada vez que reinicias el
   bot.** Cada vez que reinicies, tienes que actualizar la Callback
   URL en Meta.
3. Revisa que el "Access Token" de WhatsApp no haya caducado (dura
   24 horas en la versión temporal).

### El personal no puede abrir el panel

1. Verifica que su PC esté conectada a la red del hospital (no a WiFi
   de invitados ni con datos móviles).
2. Verifica que le pasaste la IP correcta.
3. Verifica que el firewall del PC del bot esté abierto para el
   puerto 8000. Si ejecutaste `chatbot.ps1` como administrador, debe
   estar OK.
4. Pídele que abra `cmd` y escriba `ping [IP-DEL-BOT]`. Si no
   responde, es problema de red — llama al IT.

### Aparece "PostgreSQL no responde"

1. Presiona Windows + escribe "Servicios" → abre "Servicios".
2. Busca "postgresql-x64-17" (o el número de tu versión).
3. Clic derecho → "Iniciar".

### El OCR rechaza todas las órdenes

1. Verifica que el `GEMINI_AUTH_TOKEN` esté bien copiado en `.env`.
2. Ve a `https://aistudio.google.com/app/apikey` y confirma que la
   clave sigue activa y con cupo.
3. Si se agotó el cupo gratuito, puedes:
   - Esperar al día siguiente (el cupo se renueva).
   - Habilitar facturación en aistudio.google.com (costo: fracciones
     de centavo por documento).
   - Cambiar a Ollama local (requiere instalación adicional — pide
     ayuda al desarrollador).

### Necesito reiniciar el bot

En la ventana `cmd` donde corre el bot:
- Presiona `Ctrl + C` para detenerlo.
- Luego escribe:
  ```
  powershell.exe -ExecutionPolicy Bypass -File .\chatbot.ps1 -SoloArrancar
  ```
  para arrancarlo de nuevo rápido (salta las verificaciones de instalación).

**⚠️ Recuerda actualizar la Callback URL en Meta** si Ngrok te da una
nueva URL.

---

## Siguientes pasos (después del piloto)

Cuando el piloto se estabilice y el hospital decida operar 24/7:

1. **Reemplazar Ngrok por un dominio propio.** Ngrok es útil para
   piloto, pero para producción real conviene:
   - Comprar un dominio (~10 USD/año).
   - Instalar Nginx como reverse proxy.
   - Obtener certificado SSL de Let's Encrypt.

2. **Mover el bot a un servidor Linux dedicado.** Un servidor pequeño
   (VM) es más estable que un PC de escritorio y permite arranque
   automático con `systemd`.

3. **Generar un Access Token permanente de WhatsApp** (System User) que
   no caduque cada 24 horas.

4. **Configurar respaldos automáticos** de la base de datos
   (`pg_dump` diario a un disco externo o servidor de respaldo).

Cuando llegue ese momento, contacta al desarrollador — cada uno de esos
pasos merece su propia sesión de trabajo.

---

**Autor:** Ing. Javier Santiago Burbano
**Contacto:** [poner correo del hospital o del desarrollador]

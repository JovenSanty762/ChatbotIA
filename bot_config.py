"""
Configuración del ChatBot WhatsApp
Con soporte para Ngrok
"""
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Base de Datos PostgreSQL
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "hospital_chatbot"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "51573m45"
    
    # WhatsApp Business API
    WHATSAPP_TOKEN: str
    WHATSAPP_PHONE_NUMBER_ID: str
    VERIFY_TOKEN: str = "H2C0I2i4A"
    
    # Inteligencia Artificial
    # Proveedor activo: "claude" | "gemini" | "groq"
    AI_PROVIDER: str = "groq"

    # Claude (Anthropic) — https://console.anthropic.com/
    ANTHROPIC_API_KEY: str = ""

    # Google Gemini — https://aistudio.google.com/app/apikey  (tier gratuito disponible)
    GEMINI_AUTH_TOKEN: str = ""
    GEMINI_MODEL: str = "gemini-flash-lite-latest"

    # Groq (Llama 3.3) — https://console.groq.com/  (tier gratuito disponible)
    GROQ_AUTH_TOKEN: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # ── OCR / Visión (lectura de documentos) ─────────────────────────────────
    # Proveedor del OCR, independiente del de texto:
    #   "gemini"  → nube, rápido y preciso (tope diario en el plan gratuito)
    #   "ollama"  → modelo de visión LOCAL, sin límites, 100% offline
    OCR_PROVIDER: str = "gemini"
    # Ollama (OCR local sin límite). Requiere Ollama instalado y un modelo de visión.
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2-vision"   # p. ej. qwen2.5vl:7b, minicpm-v, llava
    OLLAMA_TIMEOUT: int = 120               # segundos (en CPU la lectura puede tardar)

    # Ngrok
    NGROK_AUTH_TOKEN: str  # Token de tu cuenta de Ngrok
    NGROK_ENABLED: bool = True
    # Regex (case-insensitive) que identifica hosts PÚBLICOS (accesibles desde
    # Internet). Cuando el request llega por uno de esos hosts, el middleware
    # solo deja pasar /webhook — el panel administrativo y demás endpoints
    # quedan invisibles (404 opaco) aunque alguien descubra la URL pública.
    # Default: patrones típicos de túneles temporales (ngrok, cloudflared,
    # localtunnel, serveo). Añade el dominio propio del hospital si un día se
    # despliega detrás de un dominio público y quieres el mismo blindaje.
    PUBLIC_HOST_PATTERN: str = r"ngrok|trycloudflare|localtunnel|serveo"
    
    # Servidor
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    # Recarga automática al editar código (solo desarrollo). En Windows el
    # reloader reimporta todo en un subproceso y duplica el tiempo de arranque,
    # por eso viene DESACTIVADO por defecto para que el bot conecte más rápido.
    RELOAD: bool = False
    
    # Sesiones
    SESSION_TIMEOUT_MINUTES: int = 15

    # Contraseña que protege el botón de "Reiniciar sistema" del panel web.
    # Cámbiala en .env (ADMIN_RESET_PASSWORD) por una segura.
    ADMIN_RESET_PASSWORD: str = "RESET-HOSPITAL"

    # ── Autenticación del panel administrativo (login del dashboard) ──────────
    # Usuario y contraseña para entrar al panel web. Cámbialos en .env.
    ADMIN_USER: str = "admin"
    ADMIN_PASSWORD: str = "cambia-esta-clave"
    # Clave para FIRMAR las cookies de sesión. DEBE cambiarse en .env por una
    # cadena larga y aleatoria (p. ej. `python -c "import secrets;print(secrets.token_hex(32))"`).
    SECRET_KEY: str = "CAMBIA-esta-clave-por-una-larga-y-aleatoria"
    # Horas que dura la sesión iniciada antes de pedir login de nuevo.
    ADMIN_SESSION_HORAS: int = 8
    # En producción (HTTPS detrás de Nginx) ponlo en true para que la cookie
    # solo viaje por conexiones seguras. En pruebas locales por http déjalo false.
    COOKIE_SECURE: bool = False
    
    # Hospital
    HOSPITAL_NOMBRE: str = "Hospital Civil de Ipiales"
    HOSPITAL_DIRECCION: str = "Carrera 1 No. 4A - 142 Este, Ipiales, Nariño"
    # Números del hospital que se muestran al paciente cuando debe hablar con
    # un asesor humano (sin cupos, servicio manual, etc.). Se muestran ambos
    # separados por " o ". Si algún día cambian, se actualizan en el .env.
    HOSPITAL_TELEFONO: str = "6027374008 o 6027332149"
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

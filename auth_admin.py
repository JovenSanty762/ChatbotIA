"""
Autenticación del panel administrativo.

Login por usuario + contraseña con cookie de sesión firmada mediante HMAC-SHA256.
No usa dependencias externas: todo se resuelve con la librería estándar de Python.

Flujo:
    1. POST /admin/login  → valida credenciales y entrega una cookie firmada.
    2. Cada ruta protegida depende de `requerir_auth`, que valida la cookie.
    3. POST /admin/logout → borra la cookie.

La cookie es HttpOnly (no accesible por JavaScript) y, en producción (HTTPS),
debe marcarse Secure con COOKIE_SECURE=true en el .env.
"""
import base64
import hashlib
import hmac
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Response, status

from bot_config import get_settings

settings = get_settings()

# Nombre de la cookie de sesión del panel.
COOKIE_NAME = "hospital_admin_session"


def _firmar(payload_b64: str) -> str:
    """Firma HMAC-SHA256 del payload usando la SECRET_KEY del servidor."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256,
    ).hexdigest()


def crear_token(usuario: str) -> str:
    """Crea un token firmado 'payload.firma' con caducidad embebida."""
    exp = int(time.time()) + settings.ADMIN_SESSION_HORAS * 3600
    payload = f"{usuario}|{exp}"
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{payload_b64}.{_firmar(payload_b64)}"


def verificar_token(token: Optional[str]) -> Optional[str]:
    """
    Devuelve el usuario si el token es válido y no ha caducado; None en caso
    contrario. La comparación de la firma es de tiempo constante.
    """
    if not token:
        return None
    try:
        payload_b64, firma = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(firma, _firmar(payload_b64)):
        return None
    try:
        payload = base64.urlsafe_b64decode(payload_b64).decode()
        usuario, exp = payload.split("|")
        if int(exp) < int(time.time()):
            return None
        return usuario
    except (ValueError, UnicodeDecodeError):
        return None


def credenciales_validas(usuario: str, password: str) -> bool:
    """Compara usuario y contraseña contra el .env en tiempo constante."""
    u_ok = hmac.compare_digest(usuario or "", settings.ADMIN_USER)
    p_ok = hmac.compare_digest(password or "", settings.ADMIN_PASSWORD)
    return u_ok and p_ok


def establecer_cookie(response: Response, usuario: str) -> None:
    """Adjunta la cookie de sesión firmada a la respuesta."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=crear_token(usuario),
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.ADMIN_SESSION_HORAS * 3600,
        path="/",
    )


def limpiar_cookie(response: Response) -> None:
    """Elimina la cookie de sesión (logout)."""
    response.delete_cookie(COOKIE_NAME, path="/")


def requerir_auth(
    hospital_admin_session: Optional[str] = Cookie(default=None),
) -> str:
    """
    Dependencia FastAPI: exige una cookie de sesión válida.
    Lanza 401 si no hay sesión o caducó. Devuelve el usuario autenticado.
    """
    usuario = verificar_token(hospital_admin_session)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Inicia sesión.",
        )
    return usuario

"""Excepciones especializadas para el módulo de autenticación."""

import re


def mask_tokens(text: str) -> str:
    """Oculta tokens JWT y claves sensibles en un texto o payload de error."""
    if not text:
        return ""
    # Patrón común de JWT (header.payload.signature)
    masked = re.sub(r'eyJ[a-zA-Z0-9_-]{10,}\.eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+', '[TOKEN_CENSURADO]', text)
    # Patrones clave-valor
    masked = re.sub(r'(access_token|refresh_token|id_token)["\']?\s*[:=]\s*["\']?[a-zA-Z0-9_.-]+["\']?', r'\1: [CENSURADO]', masked, flags=re.IGNORECASE)
    return masked


class FantasyAuthError(Exception):
    """Excepción base para errores de autenticación."""
    pass


class AuthConfigMissing(FantasyAuthError):
    """Lanzada cuando falta una variable de entorno o configuración requerida."""

    def __init__(self, var_name: str, hint: str = ""):
        self.var_name = var_name
        message = f"Falta la variable de configuración requerida '{var_name}'."
        if hint:
            message += f" {hint}"
        else:
            message += " Por favor, configúrala en tu archivo .env o en las variables de entorno."
        super().__init__(message)


class AuthExpired(FantasyAuthError):
    """Lanzada cuando el refresh_token ha caducado o ha sido revocado."""

    def __init__(self, details: str = ""):
        message = (
            "El refresh_token ha caducado o fue revocado por el servidor de autenticación. "
            "Repite la captura manual: ver README §Captura de token."
        )
        if details:
            message += f" Detalle: {details}"
        super().__init__(message)


class AuthBackendChanged(FantasyAuthError):
    """Lanzada cuando la respuesta de Azure B2C tiene un formato inesperado (HTML, 404, etc.)."""

    def __init__(self, raw_body: str = "", status_code: int | None = None):
        sanitized = mask_tokens(raw_body)[:500] if raw_body else "(cuerpo vacío)"
        code_str = f" [HTTP {status_code}]" if status_code is not None else ""
        message = (
            f"El backend de B2C respondió algo inesperado{code_str}. "
            "Probablemente LaLiga cambió el flujo o los endpoints; revisar github.com/Externoak/LaLigaApp.\n"
            f"Primeros 500 caracteres de la respuesta (tokens censurados):\n{sanitized}"
        )
        super().__init__(message)

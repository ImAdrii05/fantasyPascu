"""Módulo de autenticación aislado para LaLiga Fantasy."""

import logging
from fantasy.auth.b2c import refresh_access_token
from fantasy.auth.errors import AuthExpired, AuthBackendChanged, AuthConfigMissing
from fantasy.auth.store import get_token_store
from fantasy.auth.tokens import TokenSet

logger = logging.getLogger(__name__)

__all__ = ["get_access_token", "AuthExpired", "AuthBackendChanged", "AuthConfigMissing"]


def get_access_token(force_refresh: bool = False) -> str:
    """Devuelve un token de acceso válido (JWT Bearer) para interactuar con la API.

    Si el token almacenado está expirado o a punto de expirar (margen de 5 minutos),
    o si se solicita explícitamente mediante `force_refresh=True`, se refresca
    automáticamente contra Azure AD B2C y se persiste el nuevo conjunto de tokens.

    Returns:
        str: El access_token válido listo para el header Authorization: Bearer <token>.

    Raises:
        AuthExpired: Si no hay tokens o el refresh_token ha caducado/sido revocado.
        AuthBackendChanged: Si el backend B2C respondió un formato inesperado.
    """
    store = get_token_store()
    current_tokens = store.load()

    if not current_tokens or not current_tokens.access_token:
        raise AuthExpired(
            "No se encontró ningún token configurado. Coloca el token capturado en secrets/token.json "
            "o define FANTASY_TOKEN_JSON en las variables de entorno. Ver README §Captura de token."
        )

    # Verificar si es necesario refrescar
    if force_refresh or current_tokens.is_expired():
        logger.info("El token ha expirado o se ha forzado el refresco. Contactando con Azure B2C...")
        if not current_tokens.refresh_token:
            raise AuthExpired(
                "El token de acceso ha expirado y no existe un refresh_token disponible para renovarlo. "
                "Repite la captura manual: ver README §Captura de token."
            )

        new_tokens = refresh_access_token(
            refresh_token=current_tokens.refresh_token,
            client_id=current_tokens.client_id,
        )

        # Si el refresh no trajo nuevo refresh_token, conservar el anterior
        if not new_tokens.refresh_token:
            new_tokens.refresh_token = current_tokens.refresh_token

        store.save(new_tokens)
        logger.info("Token renovado exitosamente.")
        return new_tokens.access_token

    return current_tokens.access_token

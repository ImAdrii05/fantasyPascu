"""Cliente directo para el endpoint de tokens de Azure AD B2C."""

import json
import requests

from fantasy.auth.errors import AuthBackendChanged, AuthExpired
from fantasy.auth.tokens import TokenSet
from fantasy import config


def get_token_endpoint() -> str:
    """Construye la URL del endpoint de token de Azure B2C según la configuración."""
    tenant = config.B2C_TENANT
    policy = config.B2C_POLICY

    if tenant.startswith("http://") or tenant.startswith("https://"):
        base = tenant.rstrip("/")
        return f"{base}?p={policy}" if "?p=" not in base else base
    elif "." in tenant:
        # Dominio personalizado (el caso real de LaLiga: login.laliga.es).
        # El dominio del tenant sale de config para poder parchearlo sin tocar código.
        return f"https://{tenant}/{config.B2C_TENANT_DOMAIN}/oauth2/v2.0/token?p={policy}"
    else:
        # Tenant estándar B2C
        return f"https://{tenant}.b2clogin.com/{tenant}.onmicrosoft.com/{policy}/oauth2/v2.0/token"


def get_authorize_endpoint() -> str:
    """URL del endpoint de autorización (login interactivo). Es la de token cambiando el final."""
    base, sep, query = get_token_endpoint().partition("?")
    return base.removesuffix("/token") + "/authorize" + sep + query


def default_scope_for_client(client_id: str | None) -> str:
    """Scope con el que se pidió el token según el cliente que lo emitió.

    Cada cliente tiene el suyo: el web lleva su propio client_id como recurso y el de la
    app móvil no. Refrescar un token del login interactivo con el scope del cliente web
    pediría un recurso ajeno y B2C lo rechazaría.
    """
    if client_id and client_id == config.B2C_LOGIN_CLIENT_ID:
        return config.B2C_LOGIN_SCOPE
    return config.B2C_SCOPE


def refresh_access_token(
    refresh_token: str,
    client_id: str | None = None,
    scope: str | None = None,
    timeout: int = 15,
) -> TokenSet:
    """Envía una petición a Azure B2C para refrescar el conjunto de tokens.

    Args:
        refresh_token: El refresh token emitido previamente.
        client_id: Opcional, identificador de cliente OAuth2 (usa config por defecto).
        scope: Opcional, scopes solicitados (usa config por defecto).
        timeout: Timeout en segundos para la llamada HTTP.

    Returns:
        TokenSet con los tokens actualizados.

    Raises:
        AuthExpired: Si el refresh_token es inválido, caducó o fue revocado (HTTP 400/401).
        AuthBackendChanged: Si la respuesta no es JSON o no incluye tokens válidos.
    """
    if not refresh_token:
        raise AuthExpired("No se proporcionó ningún refresh_token.")

    used_client_id = client_id or config.B2C_CLIENT_ID
    payload = {
        "grant_type": "refresh_token",
        "client_id": used_client_id,
        "scope": scope or default_scope_for_client(used_client_id),
        "refresh_token": refresh_token,
    }
    return request_tokens(payload, timeout=timeout)


def exchange_code_for_tokens(
    code: str,
    code_verifier: str,
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scope: str | None = None,
    timeout: int = 15,
) -> TokenSet:
    """Canjea el código de autorización del login interactivo (PKCE) por tokens.

    Raises:
        AuthExpired: Si B2C rechaza el código (caducado, ya usado o verifier incorrecto).
        AuthBackendChanged: Si la respuesta no es JSON o no incluye tokens válidos.
    """
    used_client_id = client_id or config.B2C_LOGIN_CLIENT_ID
    payload = {
        "grant_type": "authorization_code",
        "client_id": used_client_id,
        "code": code,
        "redirect_uri": redirect_uri or config.B2C_LOGIN_REDIRECT_URI,
        "code_verifier": code_verifier,
        "scope": scope or default_scope_for_client(used_client_id),
    }
    return request_tokens(payload, timeout=timeout)


def request_tokens(payload: dict[str, str], timeout: int = 15) -> TokenSet:
    """POST al endpoint de token de B2C con discriminación de errores.

    Común al refresco y al canje del código: los dos hablan con el mismo endpoint y
    fallan de las mismas maneras.
    """
    url = get_token_endpoint()
    used_client_id = payload["client_id"]

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise AuthBackendChanged(f"Error de conexión al endpoint de B2C: {e}") from e

    # Manejo de respuestas HTTP 400/401 con discriminación de error
    if response.status_code in (400, 401):
        err_code = ""
        err_desc = response.text
        try:
            err_data = response.json()
            err_code = str(err_data.get("error") or "")
            err_desc = str(err_data.get("error_description") or err_code or response.text)
        except Exception:
            pass

        # Error en el cliente OAuth2 (client_id inválido o no autorizado)
        if err_code in ("invalid_client", "unauthorized_client"):
            raise AuthBackendChanged(
                f"Error de configuración de cliente OAuth2 ({err_code}). "
                f"El B2C_CLIENT_ID ('{used_client_id}') no es válido o no está autorizado. "
                f"Detalle: {err_desc}",
                status_code=response.status_code,
            )

        # Error de parámetros en la petición
        if err_code == "invalid_request":
            raise AuthBackendChanged(
                f"Petición rechazada por B2C ({err_code}). "
                f"Verifica B2C_POLICY y B2C_SCOPE en tu .env. Detalle: {err_desc}",
                status_code=response.status_code,
            )

        # Token expirado o revocado (invalid_grant o 401)
        raise AuthExpired(f"HTTP {response.status_code} ({err_code or 'error'}): {err_desc}")

    # Respuestas de error HTTP 404, 500, etc.
    if not response.ok:
        raise AuthBackendChanged(response.text, status_code=response.status_code)

    # Validar que la respuesta sea JSON
    try:
        data = response.json()
    except Exception as e:
        raise AuthBackendChanged(
            f"La respuesta no es JSON válido (error: {e}). Contenido: {response.text}",
            status_code=response.status_code,
        ) from e

    if not isinstance(data, dict):
        raise AuthBackendChanged(f"Respuesta inesperada (no es un objeto JSON): {data}", status_code=response.status_code)

    # Validar que contenga access_token o id_token
    token_val = data.get("access_token") or data.get("id_token")
    if not token_val:
        raise AuthBackendChanged(
            f"El JSON de respuesta no contiene access_token ni id_token. Claves recibidas: {list(data.keys())}",
            status_code=response.status_code,
        )

    # Guardar el client_id con el que se emitió
    data.setdefault("client_id", used_client_id)
    return TokenSet.from_dict(data)

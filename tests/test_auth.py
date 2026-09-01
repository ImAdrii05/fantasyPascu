"""Tests unitarios para el módulo de autenticación (sin red real, usando responses)."""

import json
import time
import pytest
import responses

from fantasy.auth import get_access_token
from fantasy.auth.b2c import get_token_endpoint, refresh_access_token
from fantasy.auth.errors import AuthBackendChanged, AuthExpired
from fantasy.auth.store import BaseTokenStore, set_token_store, FileTokenStore, EnvTokenStore
from fantasy.auth.tokens import TokenSet


class MemoryTokenStore(BaseTokenStore):
    """Almacén en memoria para aislar los tests."""
    def __init__(self, initial_tokens: TokenSet | None = None):
        self._tokens = initial_tokens

    def load(self) -> TokenSet | None:
        return self._tokens

    def save(self, tokens: TokenSet) -> None:
        self._tokens = tokens


def test_token_expiration_logic():
    """Valida el cálculo de expiración con el margen de 5 minutos."""
    now = int(time.time())

    # Token con 10 minutos de vida: no expirado
    t_valid = TokenSet(access_token="valid_tok", expires_at=now + 600)
    assert not t_valid.is_expired()

    # Token con 4 minutos de vida: dentro del margen de 5 min (300s), debe considerarse expirado
    t_expiring_soon = TokenSet(access_token="soon_tok", expires_at=now + 240)
    assert t_expiring_soon.is_expired()

    # Token ya expirado en el pasado
    t_expired = TokenSet(access_token="old_tok", expires_at=now - 60)
    assert t_expired.is_expired()

    # Token sin fecha de expiración: se asume expirado
    t_no_date = TokenSet(access_token="no_date_tok", expires_at=None)
    assert t_no_date.is_expired()


def test_token_set_serialization():
    """Valida conversión a/desde diccionario."""
    data = {
        "access_token": "acc_123",
        "id_token": "id_123",
        "refresh_token": "ref_123",
        "expires_in": 3600,
        "token_type": "Bearer",
        "client_id": "client_abc",
    }
    tokens = TokenSet.from_dict(data)
    assert tokens.access_token == "acc_123"
    assert tokens.id_token == "id_123"
    assert tokens.refresh_token == "ref_123"
    assert tokens.expires_at is not None
    assert tokens.expires_at > time.time()

    d = tokens.to_dict()
    assert d["access_token"] == "acc_123"
    assert d["refresh_token"] == "ref_123"


def test_get_access_token_when_valid_no_network():
    """Si el token almacenado es válido y no está caducado, no debe llamar a B2C."""
    valid_tokens = TokenSet(
        access_token="current_valid_token",
        refresh_token="some_refresh",
        expires_at=int(time.time()) + 1000,
    )
    store = MemoryTokenStore(valid_tokens)
    set_token_store(store)

    token = get_access_token(force_refresh=False)
    assert token == "current_valid_token"


@responses.activate
def test_refresh_success():
    """Prueba el flujo exitoso de refresco contra el endpoint de B2C."""
    endpoint = get_token_endpoint()
    responses.add(
        responses.POST,
        endpoint,
        json={
            "access_token": "new_access_token_123",
            "id_token": "new_id_token_123",
            "refresh_token": "new_rotated_refresh_token_456",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
        status=200,
    )

    expired_tokens = TokenSet(
        access_token="expired_token",
        refresh_token="old_refresh_token",
        expires_at=int(time.time()) - 10,
    )
    store = MemoryTokenStore(expired_tokens)
    set_token_store(store)

    new_token = get_access_token()
    assert new_token == "new_access_token_123"

    # Verificar que se actualizó el almacén
    saved = store.load()
    assert saved is not None
    assert saved.access_token == "new_access_token_123"
    assert saved.refresh_token == "new_rotated_refresh_token_456"


@responses.activate
def test_refresh_401_raises_auth_expired():
    """Un HTTP 401 o 400 en el endpoint de token debe lanzar AuthExpired con mensaje claro."""
    endpoint = get_token_endpoint()
    responses.add(
        responses.POST,
        endpoint,
        json={"error": "invalid_grant", "error_description": "AADB2C90080: The provided grant has expired."},
        status=400,
    )

    expired_tokens = TokenSet(
        access_token="expired_token",
        refresh_token="revoked_refresh_token",
        expires_at=int(time.time()) - 10,
    )
    set_token_store(MemoryTokenStore(expired_tokens))

    with pytest.raises(AuthExpired) as exc_info:
        get_access_token()
    assert "caducado o fue revocado" in str(exc_info.value)


@responses.activate
def test_refresh_html_or_bad_response_raises_auth_backend_changed():
    """Si B2C devuelve HTML o algo no esperado, se lanza AuthBackendChanged censurando tokens."""
    endpoint = get_token_endpoint()
    responses.add(
        responses.POST,
        endpoint,
        body="<html><body>Bad Gateway or Cloudflare block. access_token=secret12345</body></html>",
        status=502,
    )

    expired_tokens = TokenSet(
        access_token="expired_token",
        refresh_token="valid_refresh_token",
        expires_at=int(time.time()) - 10,
    )
    set_token_store(MemoryTokenStore(expired_tokens))

    with pytest.raises(AuthBackendChanged) as exc_info:
        get_access_token()
    err_msg = str(exc_info.value)
    assert "El backend de B2C respondió algo inesperado" in err_msg
    assert "secret12345" not in err_msg

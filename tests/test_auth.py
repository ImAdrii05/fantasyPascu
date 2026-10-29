"""Tests unitarios para el módulo de autenticación (sin red real, usando responses)."""

from pathlib import Path
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


@responses.activate
def test_refresh_invalid_client_raises_auth_backend_changed():
    """Un error invalid_client en B2C debe señalar problema de configuración de client_id."""
    endpoint = get_token_endpoint()
    responses.add(
        responses.POST,
        endpoint,
        json={"error": "invalid_client", "error_description": "The client id is not valid."},
        status=400,
    )

    expired_tokens = TokenSet(
        access_token="expired_token",
        refresh_token="valid_refresh_token",
        expires_at=int(time.time()) - 10,
    )
    set_token_store(MemoryTokenStore(expired_tokens))

    with pytest.raises(AuthBackendChanged) as exc_info:
        get_access_token()
    assert "B2C_CLIENT_ID" in str(exc_info.value)



def test_token_se_cachea_y_no_relee_el_almacen():
    """El almacén solo debe leerse una vez: con Supabase, cada lectura es un viaje a la BD."""
    from fantasy.auth import get_access_token
    from fantasy.auth.store import BaseTokenStore, set_token_store
    from fantasy.auth.tokens import TokenSet

    class CountingStore(BaseTokenStore):
        def __init__(self):
            self.loads = 0

        def load(self):
            self.loads += 1
            return TokenSet(access_token="tok", expires_at=9999999999)

        def save(self, tokens):
            pass

    store = CountingStore()
    set_token_store(store)

    for _ in range(50):
        assert get_access_token() == "tok"

    assert store.loads == 1, f"El almacén se leyó {store.loads} veces; debería ser 1"


def test_token_de_fichero_se_siembra_en_supabase(monkeypatch):
    """Cargar del fichero local debe propagar el token a Supabase.

    Regresión: `save()` solo se llamaba al refrescar. Con un access_token de 24 h,
    una ejecución local recién capturado el token no refrescaba nada y dejaba
    `auth_state` vacía; GitHub Actions, que no tiene el fichero, fallaba con
    AuthMissing. Es un fallo invisible en local y solo detectable en CI.
    """
    from fantasy import config
    from fantasy.auth.store import HybridTokenStore, FileTokenStore, EnvTokenStore, SupabaseTokenStore
    from fantasy.auth.tokens import TokenSet

    monkeypatch.setattr(config, "SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "fake-key")

    token = TokenSet(access_token="del-fichero", refresh_token="rt", expires_at=9999999999)

    class FileStub(FileTokenStore):
        def __init__(self):
            self.file_path = Path("secrets/token.json")

        def load(self):
            return token

    class SupabaseSpy(SupabaseTokenStore):
        def __init__(self):
            self.saved = None

        def load(self):
            return None  # tabla vacía, como en el fallo real

        def save(self, tokens):
            self.saved = tokens

    spy = SupabaseSpy()
    store = HybridTokenStore(file_store=FileStub(), env_store=EnvTokenStore(raw_json=None), supabase_store=spy)

    assert store.load().access_token == "del-fichero"
    assert spy.saved is not None, "El token del fichero no se sembró en Supabase"
    assert spy.saved.access_token == "del-fichero"


def test_sin_token_en_ningun_almacen_lanza_authmissing():
    """El mensaje debe decir que NO hay token, no que haya caducado."""
    import pytest
    from fantasy.auth import get_access_token
    from fantasy.auth.errors import AuthMissing
    from fantasy.auth.store import BaseTokenStore, set_token_store

    class EmptyStore(BaseTokenStore):
        def load(self):
            return None

        def save(self, tokens):
            pass

    set_token_store(EmptyStore())
    with pytest.raises(AuthMissing) as exc:
        get_access_token()

    assert "No hay ningún token almacenado" in str(exc.value)
    assert "caducado" not in str(exc.value).split("Detalle")[0]


@responses.activate
def test_app_despierta_recoge_el_token_que_renovo_el_job():
    """La app (Streamlit) y el job diario comparten el token en Supabase.

    Si el job lo renueva mientras la app tiene el viejo en memoria, la app no debe
    usar su refresh_token viejo (puede estar ya rotado): al caducar el de memoria
    relee el almacén y se queda con el del job, sin llamar a B2C.
    """
    ahora = int(time.time())
    store = MemoryTokenStore(TokenSet(access_token="viejo", refresh_token="rt_viejo", expires_at=ahora + 1000))
    set_token_store(store)
    assert get_access_token() == "viejo"

    # Pasa el tiempo: el de memoria caduca y, entre tanto, el job dejó uno nuevo.
    import fantasy.auth as auth_mod
    auth_mod._cached_tokens.expires_at = ahora - 10
    store.save(TokenSet(access_token="del_job", refresh_token="rt_nuevo", expires_at=ahora + 80_000))

    assert get_access_token() == "del_job"
    assert len(responses.calls) == 0  # ni una llamada a B2C con el refresh_token viejo


@responses.activate
def test_si_el_token_del_almacen_tambien_caduco_renueva_con_el_refresh_mas_reciente():
    """Arranque en frío (la app despierta tras dormir): se renueva con el último refresh_token."""
    responses.add(
        responses.POST, get_token_endpoint(),
        json={"access_token": "renovado", "refresh_token": "rt_3", "expires_in": 3600}, status=200,
    )
    store = MemoryTokenStore(TokenSet(access_token="caducado", refresh_token="rt_2", expires_at=int(time.time()) - 60))
    set_token_store(store)

    assert get_access_token() == "renovado"
    assert "refresh_token=rt_2" in responses.calls[0].request.body
    assert store.load().refresh_token == "rt_3"

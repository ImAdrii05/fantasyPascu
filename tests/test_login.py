"""Tests del login interactivo (PKCE + canje de código), sin navegador ni red real."""

from urllib.parse import parse_qs, urlencode, urlsplit
import json

import pytest
import responses

from fantasy import config
from fantasy.auth import login as login_mod
from fantasy.auth.b2c import exchange_code_for_tokens, get_authorize_endpoint, get_token_endpoint, refresh_access_token
from fantasy.auth.errors import AuthExpired, LoginFailed
from fantasy.auth.login import code_from_redirect, login, new_login_request, pkce_challenge, save_login_tokens
from fantasy.auth.tokens import TokenSet

REDIRECT = "authredirect://com.lfp.laligafantasy"


def _form(call) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(call.request.body).items()}


def test_pkce_challenge_vector_rfc7636():
    """Vector de ejemplo del RFC 7636 (apéndice B): si esto falla, B2C rechazaría el canje."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_authorize_endpoint_derivado_del_de_token():
    assert get_token_endpoint().startswith("https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0/token")
    assert get_authorize_endpoint() == (
        "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0/authorize"
        "?p=B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
    )


def test_url_de_login_usa_el_cliente_de_la_app_movil_con_pkce():
    req = new_login_request()
    parts = urlsplit(req.url)
    params = {k: v[0] for k, v in parse_qs(parts.query).items()}

    assert parts.netloc == "login.laliga.es"
    assert parts.path.endswith("/oauth2/v2.0/authorize")
    assert params["p"] == "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
    assert params["client_id"] == "af88bcff-1157-40a0-b579-030728aacf0b"
    assert params["redirect_uri"] == REDIRECT
    assert params["response_type"] == "code"
    assert params["scope"] == "openid offline_access"
    assert params["code_challenge_method"] == "S256"
    assert params["code_challenge"] == pkce_challenge(req.code_verifier)
    assert params["state"] == req.state
    # La política de LaLiga puede rechazar prompt=login.
    assert "prompt" not in params


def test_cada_login_genera_verifier_y_state_nuevos():
    a, b = new_login_request(), new_login_request()
    assert a.code_verifier != b.code_verifier
    assert a.state != b.state
    assert 43 <= len(a.code_verifier) <= 128


def test_code_from_redirect_url_completa():
    url = f"{REDIRECT}?code=abc.def-123&state=st4te"
    assert code_from_redirect(url, expected_state="st4te") == "abc.def-123"


def test_code_from_redirect_tolera_comillas_y_solo_query():
    assert code_from_redirect(f"'{REDIRECT}?state=s&code=c0de'", expected_state="s") == "c0de"
    assert code_from_redirect("code=c0de&state=s", expected_state="s") == "c0de"


def test_code_from_redirect_codigo_a_secas():
    assert code_from_redirect("  eyJraWQiOiJjcGltY29yZV8wOTI1MjAxNSIsInZlciI6IjEuMCJ9.x-y_z  ", expected_state="s") == (
        "eyJraWQiOiJjcGltY29yZV8wOTI1MjAxNSIsInZlciI6IjEuMCJ9.x-y_z"
    )


def test_code_from_redirect_state_distinto():
    with pytest.raises(LoginFailed, match="state"):
        code_from_redirect(f"{REDIRECT}?code=c0de&state=otro", expected_state="mio")


def test_code_from_redirect_error_de_b2c():
    url = f"{REDIRECT}?" + urlencode(
        {"error": "access_denied", "error_description": "AADB2C90091: The user has cancelled.", "state": "s"}
    )
    with pytest.raises(LoginFailed, match="AADB2C90091"):
        code_from_redirect(url, expected_state="s")


def test_code_from_redirect_sin_codigo():
    with pytest.raises(LoginFailed):
        code_from_redirect(f"{REDIRECT}?state=s", expected_state="s")
    with pytest.raises(LoginFailed):
        code_from_redirect("   ", expected_state="s")


@responses.activate
def test_exchange_code_envia_pkce_y_usa_id_token_como_bearer():
    """Con scope `openid offline_access` B2C devuelve id_token y no access_token."""
    responses.add(
        responses.POST,
        get_token_endpoint(),
        json={"id_token": "id.tok.en", "id_token_expires_in": 86400, "refresh_token": "ref", "token_type": "Bearer"},
        status=200,
    )

    tokens = exchange_code_for_tokens(code="c0de", code_verifier="verif")

    body = _form(responses.calls[0])
    assert body == {
        "grant_type": "authorization_code",
        "client_id": "af88bcff-1157-40a0-b579-030728aacf0b",
        "code": "c0de",
        "redirect_uri": REDIRECT,
        "code_verifier": "verif",
        "scope": "openid offline_access",
    }
    assert tokens.access_token == "id.tok.en"
    assert tokens.refresh_token == "ref"
    # El client_id queda guardado: el refresco tiene que hacerse con el mismo cliente.
    assert tokens.client_id == "af88bcff-1157-40a0-b579-030728aacf0b"
    assert not tokens.is_expired()


@responses.activate
def test_refresh_de_token_del_login_usa_su_propio_scope():
    responses.add(responses.POST, get_token_endpoint(), json={"id_token": "nuevo", "expires_in": 3600}, status=200)
    refresh_access_token("ref", client_id=config.B2C_LOGIN_CLIENT_ID)
    body = _form(responses.calls[0])
    assert body["client_id"] == config.B2C_LOGIN_CLIENT_ID
    assert body["scope"] == "openid offline_access"


@responses.activate
def test_refresh_de_token_web_mantiene_el_scope_de_siempre():
    responses.add(responses.POST, get_token_endpoint(), json={"access_token": "nuevo", "expires_in": 3600}, status=200)
    refresh_access_token("ref")
    body = _form(responses.calls[0])
    assert body["client_id"] == config.B2C_CLIENT_ID
    assert body["scope"] == config.B2C_SCOPE


@responses.activate
def test_login_manual_de_principio_a_fin(monkeypatch):
    monkeypatch.setattr(login_mod.webbrowser, "open", lambda url: None)
    responses.add(
        responses.POST,
        get_token_endpoint(),
        json={"id_token": "id.tok.en", "expires_in": 86400, "refresh_token": "ref"},
        status=200,
    )

    printed: list[str] = []

    def fake_input(prompt: str) -> str:
        # Lo que haría el usuario: abrir la URL mostrada, iniciar sesión y pegar la vuelta.
        url = next(line.strip() for text in printed for line in text.splitlines() if "/authorize?" in line)
        state = parse_qs(urlsplit(url).query)["state"][0]
        return f"{REDIRECT}?code=c0de&state={state}"

    tokens = login(manual=True, input_fn=fake_input, print_fn=printed.append)

    assert tokens.access_token == "id.tok.en"
    body = _form(responses.calls[0])
    assert body["code"] == "c0de"
    assert body["code_verifier"]


@responses.activate
def test_login_con_codigo_rechazado_lanza_login_failed(monkeypatch):
    monkeypatch.setattr(login_mod.webbrowser, "open", lambda url: None)
    responses.add(
        responses.POST,
        get_token_endpoint(),
        json={"error": "invalid_grant", "error_description": "AADB2C90088: The provided grant has not been issued."},
        status=400,
    )

    with pytest.raises(LoginFailed, match="AADB2C90088") as exc_info:
        login(manual=True, input_fn=lambda prompt: "c0de", print_fn=lambda text: None)
    assert isinstance(exc_info.value.__cause__, AuthExpired)


def test_save_login_tokens_en_fichero_sin_supabase(tmp_path, monkeypatch):
    token_path = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(config, "FANTASY_TOKEN_PATH", str(token_path))
    monkeypatch.setattr(config, "SUPABASE_URL", "")
    monkeypatch.setattr(config, "SUPABASE_SERVICE_KEY", "")

    tokens = TokenSet(access_token="tok", refresh_token="ref", expires_at=2_000_000_000, client_id="cli")
    destinations = save_login_tokens(tokens)

    assert destinations == [str(token_path)]
    saved = json.loads(token_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "tok"
    assert saved["client_id"] == "cli"

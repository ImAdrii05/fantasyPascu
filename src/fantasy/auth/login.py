"""Login interactivo contra LaLiga (Azure AD B2C): Apple, Google o email.

CÓMO FUNCIONA
-------------
No se habla con Apple ni con Google directamente. Se abre la página de login de LaLiga
(la misma que usa la app móvil) y es ella la que ofrece "Continuar con Apple/Google" y
hace todo el baile con el proveedor. Al terminar, B2C redirige a la `redirect_uri` de la
app móvil con un código de un solo uso, y ese código se canjea por tokens (PKCE).

La `redirect_uri` es un esquema propio, `authredirect://com.lfp.laligafantasy`, que el
navegador no sabe abrir. Esa navegación fallida es lo que se aprovecha: el código va en
la URL. Hay dos formas de leerla:

  - Navegador automatizado (Playwright): se abre una ventana, inicias sesión como
    siempre y el programa ve pasar la redirección y se queda con el código. Sin copiar
    nada a mano.
  - Manual: se abre la página en tu navegador y pegas la URL `authredirect://...` que
    aparece en la consola de DevTools al terminar.

Por qué el cliente de la app móvil y no el web: el cliente web solo admite redirigir a
miliga.laliga.com, y ahí el código se lo queda la propia web; un programa local no
llega a verlo nunca.
"""

import base64
import hashlib
import logging
import re
import secrets
import time
import webbrowser
from dataclasses import dataclass
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from fantasy import config
from fantasy.auth import reset_token_cache
from fantasy.auth.b2c import default_scope_for_client, exchange_code_for_tokens, get_authorize_endpoint
from fantasy.auth.errors import AuthExpired, LoginFailed
from fantasy.auth.store import FileTokenStore, SupabaseTokenStore
from fantasy.auth.tokens import TokenSet

logger = logging.getLogger(__name__)

# Tiempo para completar el login en la ventana (Apple puede pedir confirmar en el iPhone).
DEFAULT_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class LoginRequest:
    """Lo que hay que recordar entre abrir la página de login y canjear el código."""
    url: str
    state: str
    code_verifier: str
    client_id: str
    redirect_uri: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def pkce_challenge(code_verifier: str) -> str:
    """Challenge S256 de PKCE: SHA-256 del verifier en base64url sin relleno."""
    return _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())


def new_login_request(
    client_id: str | None = None,
    redirect_uri: str | None = None,
    scope: str | None = None,
) -> LoginRequest:
    """Genera la URL de login con un verifier PKCE y un `state` nuevos."""
    used_client_id = client_id or config.B2C_LOGIN_CLIENT_ID
    used_redirect_uri = redirect_uri or config.B2C_LOGIN_REDIRECT_URI
    code_verifier = _b64url(secrets.token_bytes(32))
    state = _b64url(secrets.token_bytes(16))

    # Sin `prompt=login`: la política de LaLiga puede rechazarlo.
    params = {
        "client_id": used_client_id,
        "response_type": "code",
        "redirect_uri": used_redirect_uri,
        "scope": scope or default_scope_for_client(used_client_id),
        "code_challenge": pkce_challenge(code_verifier),
        "code_challenge_method": "S256",
        "state": state,
        "nonce": _b64url(secrets.token_bytes(16)),
    }
    endpoint = get_authorize_endpoint()
    separator = "&" if "?" in endpoint else "?"
    return LoginRequest(
        url=f"{endpoint}{separator}{urlencode(params)}",
        state=state,
        code_verifier=code_verifier,
        client_id=used_client_id,
        redirect_uri=used_redirect_uri,
    )


def code_from_redirect(redirected: str, expected_state: str | None) -> str:
    """Extrae el código de la URL de vuelta (`authredirect://...?code=...&state=...`).

    Acepta también solo la parte `code=...&state=...` o el código a secas, para el caso
    manual en que se copia de DevTools lo que buenamente se puede. Con el código a secas
    no hay `state` que comprobar.

    Raises:
        LoginFailed: Si B2C devolvió un error, el `state` no coincide o no hay código.
    """
    text = redirected.strip().strip("\"'")
    if not text:
        raise LoginFailed("No se ha recibido ninguna URL.")

    if "=" not in text and "://" not in text and not any(c.isspace() for c in text):
        return text

    if "?" in text or "#" in text:
        parts = urlsplit(text)
        params = {**parse_qs(parts.fragment), **parse_qs(parts.query)}
    else:
        params = parse_qs(text)

    def first(key: str) -> str | None:
        values = params.get(key)
        return values[0] if values else None

    # Errores del propio B2C o del proveedor (p. ej. AADB2C90091: el usuario canceló).
    if first("error"):
        raise LoginFailed(f"{first('error')}: {first('error_description') or 'sin detalle'}")
    if expected_state is not None and first("state") != expected_state:
        raise LoginFailed(
            "El `state` de la respuesta no coincide con el de esta petición. "
            "La URL no corresponde a este intento de login: vuelve a empezar."
        )
    code = first("code")
    if not code:
        raise LoginFailed(f"La URL no contiene ningún código de autorización: {text[:120]}")
    return code


def _launch_browser(playwright, error_cls):
    """Abre un navegador visible, prefiriendo el Chrome o Edge instalados.

    Google bloquea a veces el login desde el Chromium que trae Playwright ("navegador no
    seguro"); con el Chrome del sistema eso pasa mucho menos. Apple no suele poner pegas.
    """
    args = ["--disable-blink-features=AutomationControlled"]
    for channel in ("chrome", "msedge", None):
        try:
            return playwright.chromium.launch(headless=False, channel=channel, args=args)
        except error_cls as e:
            logger.debug(f"No se pudo abrir el navegador (channel={channel}): {e}")
    raise LoginFailed(
        "No se encontró ningún navegador. Instala Chrome o ejecuta `playwright install chromium`."
    )


def capture_redirect_with_browser(
    request: LoginRequest,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Abre la página de login en una ventana y devuelve la URL de vuelta con el código."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise LoginFailed(
            "Falta Playwright para abrir la ventana de login. Instálalo con "
            '`pip install -e ".[login]"` y `playwright install chromium`, '
            "o usa el modo manual (`python scripts/login.py --manual`)."
        ) from e

    captured: list[str] = []
    in_text = re.compile(re.escape(request.redirect_uri) + r"[^\s'\"]*")

    def check(url: str | None) -> None:
        if url and url.startswith(request.redirect_uri) and not captured:
            captured.append(url)

    def check_text(text: str | None) -> None:
        # "Failed to launch 'authredirect://...' because the scheme does not have a
        # registered handler": lo que escribe Chrome si la redirección se hace por JS.
        found = in_text.search(text or "")
        if found:
            check(found.group(0))

    with sync_playwright() as pw:
        browser = _launch_browser(pw, PlaywrightError)
        try:
            context = browser.new_context(locale="es-ES")
            # La vuelta a authredirect:// es una redirección HTTP desde login.laliga.es.
            # Como el navegador no sabe abrir ese esquema, no hay garantía de que llegue
            # a emitirse como petición: por eso se mira también la cabecera Location.
            context.on("response", lambda r: check(r.headers.get("location")))
            context.on("request", lambda r: check(r.url))
            context.on("requestfailed", lambda r: check(r.url))
            context.on("page", lambda p: p.on("framenavigated", lambda f: check(f.url)))
            context.on("console", lambda m: check_text(m.text))

            page = context.new_page()
            try:
                page.goto(request.url, wait_until="domcontentloaded")
            except PlaywrightError as e:
                if not captured:
                    raise LoginFailed(f"No se pudo abrir la página de login de LaLiga: {e}") from e

            deadline = time.monotonic() + timeout_seconds
            while not captured:
                if page.is_closed():
                    raise LoginFailed("Se cerró la ventana antes de terminar el inicio de sesión.")
                if time.monotonic() > deadline:
                    raise LoginFailed(f"No se completó el inicio de sesión en {timeout_seconds} s.")
                try:
                    page.wait_for_timeout(250)
                except PlaywrightError:
                    # El navegador se ha cerrado: la comprobación de arriba decide.
                    if not captured:
                        raise LoginFailed("Se cerró el navegador antes de terminar el inicio de sesión.")
        finally:
            try:
                browser.close()
            except PlaywrightError:
                pass

    return captured[0]


def capture_redirect_manually(
    request: LoginRequest,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
    open_browser: bool = True,
) -> str:
    """Abre la página de login en tu navegador y pide que pegues la URL de vuelta."""
    print_fn(
        "\n1. Abre esta URL en Chrome o Edge (se intenta abrir sola):\n\n"
        f"   {request.url}\n\n"
        "2. ANTES de iniciar sesión, pulsa F12 y ve a la pestaña Console (Consola).\n"
        "3. Inicia sesión con Apple, Google o email, como en la web.\n"
        "4. Al terminar, la página no cambia, pero en la consola aparece:\n"
        "     Failed to launch 'authredirect://com.lfp.laligafantasy?code=...'\n"
        "   Copia esa URL entera (desde authredirect:// hasta la comilla final).\n"
        "   Si no sale, en la pestaña Network (con 'Preserve log') busca la última\n"
        "   petición a login.laliga.es con estado 302 y copia su cabecera 'location'.\n"
        "   El código caduca en pocos minutos y solo sirve una vez.\n"
    )
    if open_browser:
        webbrowser.open(request.url)
    return input_fn("Pega aquí la URL authredirect://... : ")


def login(
    manual: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> TokenSet:
    """Login completo: abre la página, captura el código y lo canjea por tokens.

    Raises:
        LoginFailed: Si el login no termina o B2C rechaza el código.
        AuthBackendChanged: Si el endpoint de token responde algo inesperado.
    """
    request = new_login_request()
    if manual:
        redirected = capture_redirect_manually(request, input_fn=input_fn, print_fn=print_fn)
    else:
        redirected = capture_redirect_with_browser(request, timeout_seconds=timeout_seconds)

    code = code_from_redirect(redirected, expected_state=request.state)
    try:
        return exchange_code_for_tokens(
            code=code,
            code_verifier=request.code_verifier,
            client_id=request.client_id,
            redirect_uri=request.redirect_uri,
        )
    except AuthExpired as e:
        raise LoginFailed(
            f"B2C rechazó el código ({e.details}). Caduca en pocos minutos y solo sirve "
            "una vez: repite el login."
        ) from e


def save_login_tokens(tokens: TokenSet) -> list[str]:
    """Guarda los tokens recién obtenidos en el fichero local y, si está configurado, en Supabase.

    Se escribe en los dos sitios y no solo donde haya algo: Supabase es lo primero que
    se lee, así que dejar allí un token viejo haría que se siguiera usando ese.

    Returns:
        Los destinos donde se ha guardado, para mostrárselos al usuario.
    """
    file_store = FileTokenStore()
    file_store.save(tokens)
    destinations = [str(file_store.file_path)]

    if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
        SupabaseTokenStore().save(tokens)
        destinations.append("Supabase (auth_state)")

    reset_token_cache()
    return destinations

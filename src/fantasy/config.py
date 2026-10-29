"""Configuración general y carga de variables de entorno."""

from datetime import date, datetime, timezone
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

from fantasy.auth.errors import AuthConfigMissing

# Cargar variables desde .env si existe
project_root = Path(__file__).resolve().parent.parent.parent
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file)
else:
    load_dotenv()

# Constantes de Azure AD B2C (valores verificados contra tráfico real).
# Se usa `or` en vez del default de os.getenv: en GitHub Actions un secret no definido
# llega como cadena vacía, y os.getenv devolvería "" en lugar del valor por defecto.
B2C_TENANT: str = os.getenv("B2C_TENANT") or "login.laliga.es"
B2C_TENANT_DOMAIN: str = os.getenv("B2C_TENANT_DOMAIN") or "laligadspprob2c.onmicrosoft.com"
B2C_POLICY: str = os.getenv("B2C_POLICY") or "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"
B2C_CLIENT_ID: str = os.getenv("B2C_CLIENT_ID") or "6457fa17-1224-416a-b21a-ee6ce76e9bc0"
B2C_SCOPE: str = os.getenv("B2C_SCOPE") or "6457fa17-1224-416a-b21a-ee6ce76e9bc0 openid offline_access"

# Cliente OAuth2 de la app móvil oficial, usado por el login interactivo (scripts/login.py).
#
# El cliente web (B2C_CLIENT_ID) solo admite redirigir a miliga.laliga.com, así que un
# programa local nunca llega a ver el código de autorización. El de la app móvil redirige
# a un esquema propio (`authredirect://`) que el navegador no sabe abrir: esa navegación
# fallida es justo lo que se intercepta para leer el código. Mismos valores que usa
# github.com/Externoak/LaLigaApp. Con este cliente el scope NO lleva el client_id delante.
B2C_LOGIN_CLIENT_ID: str = os.getenv("B2C_LOGIN_CLIENT_ID") or "af88bcff-1157-40a0-b579-030728aacf0b"
B2C_LOGIN_REDIRECT_URI: str = os.getenv("B2C_LOGIN_REDIRECT_URI") or "authredirect://com.lfp.laligafantasy"
B2C_LOGIN_SCOPE: str = os.getenv("B2C_LOGIN_SCOPE") or "openid offline_access"

# Rutas y almacén de tokens
FANTASY_TOKEN_PATH: str = os.getenv("FANTASY_TOKEN_PATH", "secrets/token.json")
FANTASY_TOKEN_JSON: str | None = os.getenv("FANTASY_TOKEN_JSON")

# Supabase
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

# Configuración de liga privada. Admite varias separadas por comas. Si se deja vacío,
# el job diario detecta automáticamente todas las ligas de la cuenta (endpoint de ligas del usuario).
FANTASY_LEAGUE_ID: str = os.getenv("FANTASY_LEAGUE_ID", "")


def configured_league_ids() -> list[str]:
    """IDs de liga fijados en FANTASY_LEAGUE_ID (vacío = detectar automáticamente)."""
    return [part.strip() for part in FANTASY_LEAGUE_ID.split(",") if part.strip()]


# El día de juego es el de España. LaLiga recalcula el mercado de madrugada en hora
# española (hacia las 00:30), y el job corre justo después: a las 00:40 de Madrid en
# UTC todavía es el día anterior, así que con la fecha del servidor el snapshot se
# guardaría con la fecha de ayer y pisaría al de ayer.
ZONA_JUEGO = "Europe/Madrid"

# Antes de esta hora (de Madrid), el job no guarda un mercado idéntico al de ayer:
# casi seguro LaLiga aún no lo ha recalculado. Después la guarda igualmente, para
# que un día sin cambios reales no se quede sin snapshot.
HORA_LIMITE_ESPERA_MERCADO = 7

# Recolectar aunque el día ya esté completo (lo pone el botón manual del workflow).
FORZAR_SNAPSHOT: bool = os.getenv("FORZAR_SNAPSHOT", "").lower() in ("1", "true", "yes")


def ahora_juego(ahora: datetime | None = None) -> datetime:
    """La hora actual en España (o `ahora` convertida). Sin base de zonas, en UTC."""
    ahora = ahora or datetime.now(timezone.utc)
    try:
        return ahora.astimezone(ZoneInfo(ZONA_JUEGO))
    except ZoneInfoNotFoundError:
        return ahora.astimezone(timezone.utc)


def hoy_juego(ahora: datetime | None = None) -> date:
    """La fecha del snapshot: el día en España, no el del servidor."""
    return ahora_juego(ahora).date()


# Contraseña del dashboard. Vacía (lo normal en local) = sin contraseña. En la nube
# conviene ponerla: el panel puede pagar cláusulas con tu cuenta.
APP_PASSWORD: str = os.getenv("APP_PASSWORD", "")

# Constantes de la API de LaLiga Fantasy
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://fantasy-api.llt-services.com/api")
COMPETITION_ID: str = os.getenv("COMPETITION_ID", "1")


def validate_supabase_config() -> None:
    """Valida que las credenciales de Supabase estén configuradas."""
    if not SUPABASE_URL:
        raise AuthConfigMissing("SUPABASE_URL", "Es la URL de tu proyecto Supabase (ej. https://xyz.supabase.co).")
    if not SUPABASE_SERVICE_KEY:
        raise AuthConfigMissing("SUPABASE_SERVICE_KEY", "Es la clave service_role de tu proyecto Supabase.")


def validate_league_config() -> None:
    """Valida que el ID de liga esté configurado."""
    if not FANTASY_LEAGUE_ID:
        raise AuthConfigMissing("FANTASY_LEAGUE_ID", "Es el identificador numérico de tu liga privada.")

"""Configuración general y carga de variables de entorno."""

import os
from pathlib import Path
from dotenv import load_dotenv

from fantasy.auth.errors import AuthConfigMissing

# Cargar variables desde .env si existe
project_root = Path(__file__).resolve().parent.parent.parent
env_file = project_root / ".env"
if env_file.exists():
    load_dotenv(dotenv_path=env_file)
else:
    load_dotenv()

# Constantes de Azure AD B2C (Valores verificados contra tráfico real)
B2C_TENANT: str = os.getenv("B2C_TENANT", "login.laliga.es")
B2C_POLICY: str = os.getenv("B2C_POLICY", "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN")
B2C_CLIENT_ID: str = os.getenv("B2C_CLIENT_ID", "6457fa17-1224-416a-b21a-ee6ce76e9bc0")
B2C_SCOPE: str = os.getenv("B2C_SCOPE", "6457fa17-1224-416a-b21a-ee6ce76e9bc0 openid offline_access")

# Rutas y almacén de tokens
FANTASY_TOKEN_PATH: str = os.getenv("FANTASY_TOKEN_PATH", "secrets/token.json")
FANTASY_TOKEN_JSON: str | None = os.getenv("FANTASY_TOKEN_JSON")

# Supabase
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

# Configuración de liga privada
FANTASY_LEAGUE_ID: str = os.getenv("FANTASY_LEAGUE_ID", "")

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

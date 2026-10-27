"""Definición centralizada de todas las rutas y URLs de la API de LaLiga Fantasy."""

from fantasy import config


def get_base_url() -> str:
    """Devuelve la URL base de la API sin barra final."""
    return config.API_BASE_URL.rstrip("/")


def teams_master_url() -> str:
    """Maestro de equipos (escudos, colores, nombres cortos y slugs)."""
    return f"{get_base_url()}/v3/teams-master?x-lang=es"


def all_players_url() -> str:
    """Listado completo de todos los jugadores de LaLiga con valores y estadísticas acumuladas."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/players?x-lang=es"


def player_detail_url(player_id: str | int, league_id: str | int) -> str:
    """Detalle de un jugador en el contexto de una liga específica."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/player/{player_id}/league/{league_id}?x-lang=es"


def league_market_url(league_id: str | int) -> str:
    """Jugadores disponibles en el mercado actual de una liga privada."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/league/{league_id}/market?x-lang=es"


def league_standing_url(league_id: str | int) -> str:
    """Clasificación actual de una liga privada (mánager, puntos, valor de plantilla)."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/leagues/{league_id}/standing?x-lang=es"


def league_activity_url(league_id: str | int, index: int = 0) -> str:
    """Histórico de actividad y movimientos de mercado de la liga privada (fichajes, ventas, cláusulas)."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/leagues/{league_id}/activity/{index}?x-lang=es"


def user_me_url() -> str:
    """Perfil del usuario autenticado."""
    return f"{get_base_url()}/v4/user/me?x-lang=es"


def user_leagues_url() -> str:
    """Listado de ligas en las que participa el usuario."""
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/leagues?x-lang=es"


def league_team_url(league_id: str | int, team_id: str | int) -> str:
    """Plantilla de un equipo de la liga privada, con cláusulas y escudos.

    VERIFICADO en vivo: es el único endpoint que devuelve, por cada jugador,
    `buyoutClause`, `buyoutClauseLockedEndTime` e `isShielded`. Ni el mercado ni
    la clasificación los traen, así que sin esto no hay forma de saber a quién se
    puede clausular ni cuándo se abre la cláusula.
    """
    return f"{get_base_url()}/v1/competition/{config.COMPETITION_ID}/leagues/{league_id}/teams/{team_id}?x-lang=es"

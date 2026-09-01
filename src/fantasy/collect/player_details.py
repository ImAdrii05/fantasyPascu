"""Sub-job de recolección del detalle de cada jugador (minutos y estadísticas finas).

Por qué existe este módulo aparte: el listado global de jugadores NO trae minutos.
Verificado contra la API real, solo devuelve `weekPoints` (puntos por jornada). Los
minutos y el resto de estadísticas viven en el detalle individual, un endpoint por
jugador. Son ~813 peticiones diarias, así que esto va aislado del sub-job principal:
si falla a medias, el snapshot de precios y puntos ya está guardado igualmente.

El JSON crudo del detalle NO se persiste uno a uno (serían 813 filas diarias en
`raw_snapshots`). A cambio, el diccionario íntegro de estadísticas de cada jornada
se guarda en la columna `stats` JSONB, que preserva la misma información.
"""

import logging
from typing import Any

from fantasy.api.client import FantasyApiClient
from fantasy.api import endpoints
from fantasy.api.models import PlayerGameweekStat

logger = logging.getLogger(__name__)

# Cada cuántos jugadores se registra el progreso en el log.
PROGRESS_EVERY = 100

# Si falla más de esta fracción de las peticiones, se considera que algo va mal
# de verdad (backend caído, token revocado a media ejecución) y se aborta el
# sub-job en vez de seguir martilleando la API durante 800 peticiones más.
MAX_FAILURE_RATIO = 0.25


def parse_player_detail(raw: Any, player_id: str) -> list[PlayerGameweekStat]:
    """Extrae las estadísticas por jornada del payload de detalle de un jugador.

    Estructura real verificada: {"playerMaster": {"playerStats": [ {...}, ... ]}}.
    Se tolera que la respuesta venga sin envoltorio `playerMaster` por si cambia.
    """
    if not isinstance(raw, dict):
        return []

    master = raw.get("playerMaster")
    if not isinstance(master, dict):
        master = raw

    week_stats = master.get("playerStats")
    if not isinstance(week_stats, list):
        return []

    out: list[PlayerGameweekStat] = []
    for week in week_stats:
        if not isinstance(week, dict):
            continue
        stat = PlayerGameweekStat.from_detail(player_id, week)
        if stat is not None:
            out.append(stat)
    return out


def collect_player_details(
    player_ids: list[str],
    league_id: str,
    api_client: FantasyApiClient,
) -> tuple[list[PlayerGameweekStat], dict[str, int], int]:
    """Descarga el detalle de cada jugador y devuelve sus estadísticas por jornada.

    Args:
        player_ids: Identificadores de los jugadores a consultar.
        league_id: Liga privada requerida por el endpoint de detalle.
        api_client: Cliente ya autenticado (aplica su propio throttle entre llamadas).

    Returns:
        Tupla (estadísticas, minutos_totales_por_jugador, número_de_fallos).
        `minutos_totales_por_jugador` agrega los minutos de todas las jornadas y
        sirve para rellenar `player_daily.minutes_played`.

    Raises:
        RuntimeError: Si falla una fracción de peticiones mayor que MAX_FAILURE_RATIO.
    """
    all_stats: list[PlayerGameweekStat] = []
    total_minutes: dict[str, int] = {}
    failures = 0
    total = len(player_ids)

    logger.info(f"Descargando detalle de {total} jugadores (minutos y estadísticas finas)...")

    for idx, player_id in enumerate(player_ids, start=1):
        try:
            raw = api_client.get(endpoints.player_detail_url(player_id, league_id))
            stats = parse_player_detail(raw, player_id)
            all_stats.extend(stats)

            minutes = sum(s.minutes for s in stats if s.minutes is not None)
            if minutes:
                total_minutes[player_id] = minutes
        except Exception as e:
            failures += 1
            logger.debug(f"Fallo al descargar detalle del jugador {player_id}: {e}")

            # Cortar pronto si esto no es un fallo puntual sino algo sistémico.
            if idx >= 20 and failures / idx > MAX_FAILURE_RATIO:
                raise RuntimeError(
                    f"Abortando detalle de jugadores: {failures} fallos en {idx} peticiones "
                    f"(>{MAX_FAILURE_RATIO:.0%}). Probablemente el backend o el token fallan."
                ) from e

        if idx % PROGRESS_EVERY == 0:
            logger.info(f"  ... {idx}/{total} jugadores procesados ({failures} fallos)")

    logger.info(
        f"Detalle completado: {len(all_stats)} estadísticas de jornada, "
        f"{len(total_minutes)} jugadores con minutos, {failures} fallos de {total}."
    )
    return all_stats, total_minutes, failures

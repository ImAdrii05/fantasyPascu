"""Sub-job de recolección de equipos y jugadores (mercado global)."""

import logging
from datetime import date
from fantasy.api.client import FantasyApiClient
from fantasy.collect.raw import persist_raw
from fantasy.store.supabase import SupabaseStore

logger = logging.getLogger(__name__)


def collect_players(
    api_client: FantasyApiClient,
    store: SupabaseStore,
    snapshot_date: str | date | None = None,
) -> dict[str, int]:
    """Descarga el maestro de equipos y la lista global de jugadores de LaLiga.

    1. Descarga /v3/teams-master y persiste crudo.
    2. Hace upsert en tabla `teams`.
    3. Descarga /v1/competition/1/players y persiste crudo.
    4. Hace upsert en tabla `players` (dimensional) y `player_daily` (snapshot diario).

    Returns:
        Diccionario con conteos de filas afectadas: {"teams": N, "players": N, "player_daily": N}.
    """
    counts = {"teams": 0, "players": 0, "player_daily": 0}

    # 1. Equipos maestros
    logger.info("Descargando maestro de equipos...")
    teams, raw_teams = api_client.get_teams_master()
    persist_raw("teams_master", raw_teams, store=store)
    counts["teams"] = store.upsert_teams(teams)

    # 2. Jugadores
    logger.info("Descargando listado completo de jugadores...")
    players, raw_players = api_client.get_all_players()
    persist_raw("all_players", raw_players, store=store)
    counts["players"] = store.upsert_players(players)
    counts["player_daily"] = store.upsert_player_daily(players, snapshot_date=snapshot_date)

    logger.info(
        f"Recolección global de jugadores finalizada: {counts['teams']} equipos, "
        f"{counts['players']} jugadores, {counts['player_daily']} snapshots diarios."
    )
    return counts

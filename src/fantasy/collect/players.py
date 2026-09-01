"""Sub-job de recolección de equipos y jugadores (mercado global)."""

import logging
from datetime import date
from fantasy.api.client import FantasyApiClient
from fantasy.api.models import PlayerGameweekStat
from fantasy.collect.raw import persist_raw
from fantasy.store.supabase import SupabaseStore

logger = logging.getLogger(__name__)


def extract_gameweek_stats(raw_players: any) -> list[PlayerGameweekStat]:
    """Extrae estadísticas desglosadas por jornada si vienen embebidas en el payload de jugadores."""
    stats: list[PlayerGameweekStat] = []
    items = (
        raw_players
        if isinstance(raw_players, list)
        else (
            raw_players.get("elements")
            or (raw_players.get("data") or {}).get("elements")
            or (raw_players.get("data") if isinstance(raw_players.get("data"), list) else [])
        )
    )

    for item in items:
        if not isinstance(item, dict):
            continue
        player_id = str(item.get("id") or item.get("playerId") or "")
        if not player_id:
            continue

        # Inspeccionar arrays habituales de jornadas (stats, weeks, playerStats, weekStats)
        week_list = (
            item.get("playerStats")
            or item.get("stats")
            or item.get("weeks")
            or item.get("weekStats")
            or item.get("gameweeks")
            or []
        )
        if isinstance(week_list, list):
            for w in week_list:
                if not isinstance(w, dict):
                    continue
                gw = w.get("weekNumber") or w.get("gameweek") or w.get("week") or w.get("id")
                if gw is not None:
                    try:
                        gw_int = int(gw)
                        stats.append(PlayerGameweekStat.from_api(player_id=player_id, gameweek=gw_int, data=w))
                    except (ValueError, TypeError):
                        continue

    return stats


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
    5. Si el payload contiene desglose por jornada, hace upsert en `player_gameweek_stats`.

    Returns:
        Diccionario con conteos de filas afectadas: {"teams": N, "players": N, "player_daily": N, "player_gameweek_stats": N}.
    """
    counts = {"teams": 0, "players": 0, "player_daily": 0, "player_gameweek_stats": 0}

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

    # 3. Estadísticas por jornada (si vienen embebidas en el listado)
    gw_stats = extract_gameweek_stats(raw_players)
    if gw_stats:
        logger.info(f"Detectadas {len(gw_stats)} estadísticas de jornadas en el listado de jugadores.")
        counts["player_gameweek_stats"] = store.upsert_player_gameweek_stats(gw_stats)
    else:
        logger.info("El listado global de jugadores no incluye desglose por jornada embebido (se conserva en raw_snapshots).")

    logger.info(
        f"Recolección global de jugadores finalizada: {counts['teams']} equipos, "
        f"{counts['players']} jugadores, {counts['player_daily']} snapshots diarios, "
        f"{counts['player_gameweek_stats']} estadísticas de jornada."
    )
    return counts

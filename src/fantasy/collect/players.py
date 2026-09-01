"""Sub-job de recolección de equipos y jugadores (mercado global)."""

import logging
from datetime import date
from fantasy.api.client import FantasyApiClient
from fantasy.api.models import PlayerGameweekStat
from fantasy.collect.player_details import collect_player_details
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

        # VERIFICADO contra la API real: el listado global trae `weekPoints`, una lista
        # de {"weekNumber": N, "points": P}. Solo puntos por jornada; los minutos y el
        # resto de estadísticas NO vienen aquí, hay que pedir el detalle del jugador.
        # Los demás nombres se mantienen como red de seguridad por si cambia el backend.
        week_list = (
            item.get("weekPoints")
            or item.get("playerStats")
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
    league_id: str | None = None,
    fetch_details: bool = True,
) -> dict[str, int]:
    """Descarga el maestro de equipos y la lista global de jugadores de LaLiga.

    1. Maestro de equipos -> crudo + upsert en `teams`.
    2. Listado global de jugadores -> crudo + upsert en `players`.
    3. Puntos por jornada del listado (`weekPoints`): útil pero sin minutos.
    4. Detalle de cada jugador (si hay `league_id`): minutos y estadísticas finas.
       Sustituye a lo del paso 3 porque comparte PK y contiene estrictamente más.
    5. Upsert en `player_daily` (ya con minutos) y en `player_gameweek_stats`.

    Args:
        league_id: Necesario para el endpoint de detalle. Sin él no hay minutos.
        fetch_details: Permite desactivar las ~813 peticiones de detalle (tests, pruebas rápidas).

    Returns:
        Conteos de filas afectadas por tabla, más `detail_failures` (-1 si el
        sub-job de detalle se abortó por completo).
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

    # 3. Puntos por jornada embebidos en el listado (`weekPoints`): sin minutos.
    gw_stats = extract_gameweek_stats(raw_players)
    if gw_stats:
        logger.info(f"Detectadas {len(gw_stats)} estadísticas de jornada en el listado (solo puntos).")
    else:
        logger.warning("El listado global no trajo `weekPoints`. ¿Ha cambiado el formato?")

    # 4. Detalle por jugador: la ÚNICA fuente de minutos y estadísticas finas.
    #    Aislado en su propio try: si falla, el snapshot de precios se guarda igual.
    detail_minutes: dict[str, int] = {}
    if fetch_details and league_id:
        try:
            detail_stats, detail_minutes, failures = collect_player_details(
                player_ids=[p.id for p in players if p.id],
                league_id=str(league_id),
                api_client=api_client,
            )
            if detail_stats:
                # El detalle es más rico que `weekPoints` (trae minutos y stats), así que
                # sustituye a lo extraído del listado en lugar de competir con ello:
                # ambos comparten la PK (player_id, gameweek) y el detalle debe ganar.
                gw_stats = detail_stats
            counts["detail_failures"] = failures
        except Exception as e:
            logger.warning(f"Sub-job de detalle de jugadores fallido, se continúa sin minutos: {e}")
            counts["detail_failures"] = -1
    elif fetch_details:
        logger.info("Sin FANTASY_LEAGUE_ID no se puede pedir el detalle de jugador: no habrá minutos.")

    # 5. Snapshot diario, ya con los minutos agregados del detalle si están disponibles.
    counts["player_daily"] = store.upsert_player_daily(
        players, snapshot_date=snapshot_date, minutes_by_player=detail_minutes
    )

    if gw_stats:
        counts["player_gameweek_stats"] = store.upsert_player_gameweek_stats(gw_stats)

    logger.info(
        f"Recolección global de jugadores finalizada: {counts['teams']} equipos, "
        f"{counts['players']} jugadores, {counts['player_daily']} snapshots diarios, "
        f"{counts['player_gameweek_stats']} estadísticas de jornada."
    )
    return counts

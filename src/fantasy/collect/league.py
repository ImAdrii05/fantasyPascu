"""Sub-job de recolección de mercado, clasificación y movimientos de la liga privada."""

import logging
from datetime import date
from fantasy.api.client import FantasyApiClient
from fantasy.collect.raw import persist_raw
from fantasy.store.supabase import SupabaseStore

logger = logging.getLogger(__name__)


def collect_league(
    league_id: str | int,
    api_client: FantasyApiClient,
    store: SupabaseStore,
    snapshot_date: str | date | None = None,
) -> dict[str, int]:
    """Descarga el mercado, la clasificación y el histórico de actividad de la liga privada.

    NOTA DE ARQUITECTURA:
    La API de LaLiga Fantasy expone la clasificación con `team_value` y `points`,
    así como los movimientos individuales en `activity`. NO expone el dinero líquido
    en caja disponible de cada rival. Este módulo almacena estrictamente los datos
    reales sin realizar estimaciones inventadas de saldo en caja.

    Returns:
        Diccionario con conteos de filas afectadas: {"league_standings": N, "league_movements": N}.
    """
    counts = {"league_standings": 0, "league_movements": 0}
    str_league_id = str(league_id)

    # 1. Mercado actual de la liga
    logger.info(f"Descargando mercado de la liga privada {str_league_id}...")
    try:
        market_items, raw_market = api_client.get_league_market(str_league_id)
        persist_raw(f"league_{str_league_id}_market", raw_market, store=store)
        logger.info(f"Mercado de la liga procesado: {len(market_items)} items disponibles.")
    except Exception as e:
        logger.warning(f"Error al descargar mercado de la liga: {e}")

    # 2. Clasificación de la liga
    logger.info(f"Descargando clasificación de la liga privada {str_league_id}...")
    standings, raw_standings = api_client.get_league_standing(str_league_id)
    persist_raw(f"league_{str_league_id}_standing", raw_standings, store=store)
    counts["league_standings"] = store.upsert_league_standings(standings, snapshot_date=snapshot_date)

    # 3. Actividad y movimientos recientes de la liga
    logger.info(f"Descargando histórico de actividad de la liga privada {str_league_id}...")
    movements, raw_activity = api_client.get_league_activity(str_league_id, index=0)
    persist_raw(f"league_{str_league_id}_activity", raw_activity, store=store)
    counts["league_movements"] = store.upsert_league_movements(movements)

    logger.info(
        f"Recolección de liga {str_league_id} finalizada: "
        f"{counts['league_standings']} clasificados, {counts['league_movements']} movimientos."
    )
    return counts

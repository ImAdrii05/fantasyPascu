"""Sub-job de recolección de mercado, clasificación y movimientos de la liga privada."""

import logging
from datetime import date
from fantasy.api.client import FantasyApiClient
from fantasy.api.models import MarketItem
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

    NOTA DE ARQUITECTURA (VERIFICADO contra la API real):
    El endpoint de clasificación devuelve `teamMoney`, pero SIEMPRE a NULL para los
    rivales (en el equipo propio la clave ni aparece). Por tanto NO tenemos el dinero
    líquido de los rivales: solo valor de plantilla, puntos y movimientos. El saldo
    propio sí está disponible, pero por otra vía (`team.money` en el endpoint de ligas).
    No estimar el saldo ajeno a partir del valor de plantilla: sería inventárselo.

    Returns:
        Diccionario con conteos de filas afectadas: {"league_market": N, "league_standings": N, "league_movements": N}.
    """
    counts = {"league_market": 0, "league_standings": 0, "league_movements": 0}
    str_league_id = str(league_id)

    # 1. Mercado actual de la liga
    logger.info(f"Descargando mercado de la liga privada {str_league_id}...")
    try:
        raw_market_items, raw_market = api_client.get_league_market(str_league_id)
        persist_raw(f"league_{str_league_id}_market", raw_market, store=store)
        market_models = [
            MarketItem.from_api(str_league_id, item)
            for item in raw_market_items
            if isinstance(item, dict)
        ]
        counts["league_market"] = store.upsert_league_market(market_models, snapshot_date=snapshot_date)
        logger.info(f"Mercado de la liga procesado: {counts['league_market']} items guardados en tabla league_market.")
    except Exception as e:
        logger.warning(f"Error al descargar o procesar mercado de la liga: {e}")

    # 2. Clasificación de la liga
    logger.info(f"Descargando clasificación de la liga privada {str_league_id}...")
    standings, raw_standings = api_client.get_league_standing(str_league_id)
    persist_raw(f"league_{str_league_id}_standing", raw_standings, store=store)
    counts["league_standings"] = store.upsert_league_standings(standings, snapshot_date=snapshot_date)

    # 3. Actividad y movimientos recientes de la liga
    logger.info(f"Descargando histórico de actividad de la liga privada {str_league_id}...")
    # Todas las páginas: pedir solo index=0 dejaba fuera la mitad del histórico, y sin
    # el principio no se puede reconstruir el dinero de nadie.
    movements, raw_pages = api_client.get_league_activity_all(str_league_id)
    persist_raw(f"league_{str_league_id}_activity", raw_pages, store=store)
    counts["league_movements"] = store.upsert_league_movements(movements)

    logger.info(
        f"Recolección de liga {str_league_id} finalizada: {counts['league_market']} mercado, "
        f"{counts['league_standings']} clasificados, {counts['league_movements']} movimientos."
    )
    return counts

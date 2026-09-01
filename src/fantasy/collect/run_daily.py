"""Orquestador principal del snapshot diario de LaLiga Fantasy.

Ejecuta los sub-jobs con aislamiento de fallos:
- Si el sub-job global de jugadores tiene éxito pero la liga privada falla,
  el proceso finaliza en éxito parcial (código de salida 0) con avisos en el log.
- Solo si falla el cimiento (mercado global de jugadores), el proceso devuelve código de salida 1.
"""

from datetime import date
import logging
import sys
import time

from fantasy.api.client import FantasyApiClient
from fantasy.collect.players import collect_players
from fantasy.collect.league import collect_league
from fantasy.store.supabase import get_supabase_store
from fantasy import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fantasy.collect.daily")


def run_daily() -> int:
    """Ejecuta el ciclo de recolección diario de snapshots.

    Returns:
        int: 0 en caso de éxito total o éxito parcial, 1 si falla el mercado global.
    """
    start_time = time.time()
    today = date.today().isoformat()
    logger.info(f"============================================================")
    logger.info(f"INICIANDO SNAPSHOT DIARIO LA LIGA FANTASY - FECHA: {today}")
    logger.info(f"============================================================")

    api_client = FantasyApiClient(throttle_seconds=0.5, max_retries=3)
    store = get_supabase_store()

    summary: dict[str, int] = {
        "teams": 0,
        "players": 0,
        "player_daily": 0,
        "player_gameweek_stats": 0,
        "league_market": 0,
        "league_standings": 0,
        "league_movements": 0,
    }
    errors: list[str] = []
    players_success = False

    # SUB-JOB 1: Jugadores y mercado global (CIMIENTO PRINCIPAL)
    logger.info("--- [1/2] Recolección Global de Jugadores y Equipos ---")
    try:
        player_counts = collect_players(api_client=api_client, store=store, snapshot_date=today)
        summary.update(player_counts)
        players_success = True
        logger.info("✅ Sub-job de jugadores completado correctamente.")
    except Exception as e:
        err_msg = f"Fallo crítico en recolección global de jugadores: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

    # SUB-JOB 2: Liga Privada (Clasificación, Movimientos y Mercado)
    league_id = config.FANTASY_LEAGUE_ID
    if league_id:
        logger.info(f"--- [2/2] Recolección de Liga Privada (ID: {league_id}) ---")
        try:
            league_counts = collect_league(
                league_id=league_id,
                api_client=api_client,
                store=store,
                snapshot_date=today,
            )
            summary.update(league_counts)
            logger.info("✅ Sub-job de liga privada completado correctamente.")
        except Exception as e:
            warn_msg = f"Fallo en recolección de liga privada {league_id}: {e}"
            logger.warning(warn_msg, exc_info=True)
            errors.append(warn_msg)
    else:
        logger.info("ℹ️ FANTASY_LEAGUE_ID no está configurado. Omitiendo recolección de liga privada.")

    # RESUMEN FINAL
    elapsed = time.time() - start_time
    logger.info(f"============================================================")
    logger.info(f"RESUMEN DE EJECUCIÓN (Tiempo transcurrido: {elapsed:.2f}s)")
    logger.info(f"============================================================")
    for k, v in summary.items():
        logger.info(f"  • {k:<18}: {v:>5} filas")

    if errors:
        logger.info("------------------------------------------------------------")
        logger.info("INCIDENCIAS REGISTRADAS:")
        for err in errors:
            logger.warning(f"  ⚠️ {err}")

    if not players_success:
        logger.error("❌ LA RECOLECCIÓN GLOBAL FALLÓ. Saliendo con código de error 1.")
        return 1

    if errors:
        logger.warning("⚠️ RECOLECCIÓN FINALIZADA CON ÉXITO PARCIAL (datos globales guardados).")
    else:
        logger.info("🎉 RECOLECCIÓN FINALIZADA CON ÉXITO TOTAL.")

    return 0


if __name__ == "__main__":
    sys.exit(run_daily())

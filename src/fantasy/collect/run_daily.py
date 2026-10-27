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
from fantasy.api.models import League
from fantasy.collect.players import collect_players
from fantasy.collect.league import collect_league
from fantasy.collect.raw import persist_raw
from fantasy.store.supabase import SupabaseStore, get_supabase_store
from fantasy import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("fantasy.collect.daily")


def resolve_leagues(api_client: FantasyApiClient, store: SupabaseStore, errors: list[str]) -> list[League]:
    """Ligas a recolectar: las de FANTASY_LEAGUE_ID o, si está vacío, todas las de la cuenta.

    Las ligas del usuario se piden siempre, aunque haya IDs fijados: es una sola
    petición y es la que trae los nombres. Si falla y hay IDs fijados, se sigue con
    ellos; si falla y no los hay, no hay ligas que recolectar (y queda registrado).
    """
    fixed_ids = config.configured_league_ids()
    try:
        user_leagues, raw = api_client.get_user_leagues()
    except Exception as e:
        msg = f"No se pudieron obtener las ligas de la cuenta: {e}"
        logger.warning(msg, exc_info=True)
        errors.append(msg)
        return [League(id=league_id, name=f"Liga {league_id}") for league_id in fixed_ids]

    try:
        persist_raw("user_leagues", raw, store=store)
    except Exception as e:
        logger.warning(f"No se pudo guardar el JSON crudo de las ligas: {e}")

    if fixed_ids:
        by_id = {league.id: league for league in user_leagues}
        leagues = [by_id.get(league_id) or League(id=league_id, name=f"Liga {league_id}") for league_id in fixed_ids]
    else:
        leagues = user_leagues
        logger.info(f"FANTASY_LEAGUE_ID vacío: detectadas {len(leagues)} ligas en la cuenta.")

    try:
        store.upsert_leagues(leagues)
    except Exception as e:
        # Sin la migración 004 la tabla no existe. No impide recolectar: solo deja el
        # dashboard sin nombres de liga.
        logger.warning(f"No se pudieron guardar las ligas (¿falta la migración 004_leagues.sql?): {e}")

    return leagues


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

    leagues = resolve_leagues(api_client, store, errors)
    for league in leagues:
        logger.info(f"  • Liga {league.id}: {league.name}")

    # SUB-JOB 1: Jugadores y mercado global (CIMIENTO PRINCIPAL)
    logger.info("--- [1/2] Recolección Global de Jugadores y Equipos ---")
    try:
        player_counts = collect_players(
            api_client=api_client,
            store=store,
            snapshot_date=today,
            # El detalle (minutos y stats finas) exige un league_id: el endpoint lo pide.
            # Los datos del jugador no dependen de la liga, así que basta con una.
            league_id=leagues[0].id if leagues else None,
        )
        summary.update(player_counts)
        players_success = True
        logger.info("✅ Sub-job de jugadores completado correctamente.")
    except Exception as e:
        err_msg = f"Fallo crítico en recolección global de jugadores: {e}"
        logger.error(err_msg, exc_info=True)
        errors.append(err_msg)

    # SUB-JOB 2: Ligas Privadas (Clasificación, Movimientos y Mercado), una a una:
    # el fallo de una liga no impide recolectar las demás.
    for league in leagues:
        logger.info(f"--- [2/2] Recolección de Liga Privada {league.name} (ID: {league.id}) ---")
        try:
            league_counts = collect_league(
                league_id=league.id,
                api_client=api_client,
                store=store,
                snapshot_date=today,
            )
            for key, value in league_counts.items():
                summary[key] += value
            logger.info(f"✅ Liga {league.name} completada correctamente.")
        except Exception as e:
            warn_msg = f"Fallo en recolección de liga privada {league.id}: {e}"
            logger.warning(warn_msg, exc_info=True)
            errors.append(warn_msg)
    if not leagues:
        logger.info("ℹ️ No hay ligas que recolectar. Omitiendo recolección de liga privada.")

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
